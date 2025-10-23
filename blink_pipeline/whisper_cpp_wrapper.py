"""
Wrapper for whisper.cpp to enable GGML model support in Python pipeline.

This module provides a bridge between the Python-based transcription pipeline
and whisper.cpp's native GGML model format, allowing custom Whisper models
to be used without conversion.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class WhisperCppWrapper:
    """
    Wrapper class for whisper.cpp binary execution.

    Provides a Python interface to whisper.cpp's command-line tool,
    enabling GGML model usage within the Python pipeline.
    """

    def __init__(
        self,
        model_path: str,
        whisper_cpp_binary: Optional[str] = None,
        device: str = "auto",
        compute_type: str = "default"
    ):
        """
        Initialize whisper.cpp wrapper.

        Args:
            model_path: Path to GGML model file (.bin) or Core ML model (.mlpackage/.mlmodelc)
            whisper_cpp_binary: Path to whisper-cli binary (auto-detect if None)
            device: Device to use ("auto", "cpu", "cuda", "metal", "coreml")
            compute_type: Compute type (ignored for whisper.cpp, kept for compatibility)
        """
        self.model_path = Path(model_path)

        # Handle Core ML models (.mlpackage -> .mlmodelc compilation)
        if str(model_path).endswith('.mlpackage'):
            self.model_path = self._compile_mlpackage_if_needed(self.model_path)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        # Auto-detect or validate whisper.cpp binary
        self.binary = self._find_whisper_cpp_binary(whisper_cpp_binary)
        self.device = device

        logger.info(f"Initialized whisper.cpp wrapper: binary={self.binary}, model={self.model_path}")

    def _compile_mlpackage_if_needed(self, mlpackage_path: Path) -> Path:
        """
        Compile .mlpackage to .mlmodelc if needed for whisper.cpp.

        Args:
            mlpackage_path: Path to .mlpackage directory

        Returns:
            Path to compiled .mlmodelc directory
        """
        mlmodelc_path = mlpackage_path.with_suffix('.mlmodelc')

        if mlmodelc_path.exists():
            logger.info(f"Using existing compiled Core ML model: {mlmodelc_path}")
            return mlmodelc_path

        logger.info(f"Compiling Core ML model from {mlpackage_path} to {mlmodelc_path}...")

        try:
            result = subprocess.run(
                [
                    "xcrun",
                    "coremlcompiler",
                    "compile",
                    str(mlpackage_path),
                    str(mlpackage_path.parent)
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=120
            )
            logger.info(f"Successfully compiled Core ML model to {mlmodelc_path}")
            return mlmodelc_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to compile Core ML model: {e.stderr}\n"
                "Ensure Xcode command-line tools are installed: xcode-select --install"
            )
        except FileNotFoundError:
            raise RuntimeError(
                "coremlcompiler not found. Install Xcode command-line tools: xcode-select --install"
            )

    def _find_whisper_cpp_binary(self, binary_path: Optional[str]) -> str:
        """
        Find whisper.cpp binary in common locations.

        Args:
            binary_path: User-specified path or None for auto-detection

        Returns:
            Path to whisper.cpp binary

        Raises:
            FileNotFoundError: If binary not found
        """
        if binary_path:
            # User-specified path
            if Path(binary_path).exists():
                return str(Path(binary_path).resolve())
            raise FileNotFoundError(f"whisper.cpp binary not found: {binary_path}")

        # Auto-detect in common locations
        candidates = [
            "whisper-cli",  # In PATH
            "whisper",      # Alternative name
            "./whisper-cli",
            "./build/bin/whisper-cli",
            "../whisper.cpp/build/bin/whisper-cli",
            "/usr/local/bin/whisper-cli",
            os.path.expanduser("~/bin/whisper-cli"),
        ]

        for candidate in candidates:
            try:
                # Check if command exists
                result = subprocess.run(
                    [candidate, "--help"],
                    capture_output=True,
                    timeout=5,
                    check=False
                )
                if result.returncode in (0, 1):  # Help command may return 1
                    logger.info(f"Found whisper.cpp binary: {candidate}")
                    return candidate
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                continue

        raise FileNotFoundError(
            "whisper.cpp binary not found. Install from: "
            "https://github.com/ggerganov/whisper.cpp or specify path in config"
        )

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = "en",
        task: str = "transcribe",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Transcribe audio using whisper.cpp.

        Args:
            audio_path: Path to audio file
            language: Language code (e.g., "en", "es")
            task: "transcribe" or "translate"
            **kwargs: Additional arguments (word_timestamps, etc.)

        Returns:
            Dictionary with transcription results matching openai-whisper format:
            {
                "text": str,
                "segments": List[Dict],
                "language": str
            }
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Build whisper.cpp command
        cmd = [
            self.binary,
            "-m", str(self.model_path),
            "-f", str(audio_file),
            "--output-json",  # JSON output for easy parsing
        ]

        # Add language if specified
        if language:
            cmd.extend(["-l", language])

        # Add task (translate vs transcribe)
        if task == "translate":
            cmd.append("--translate")

        # Device selection (whisper.cpp auto-detects, but we can hint)
        if self.device == "cpu":
            cmd.extend(["-t", str(os.cpu_count() or 4)])

        # Execute whisper.cpp
        logger.debug(f"Executing whisper.cpp: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
                check=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"whisper.cpp failed: {e.stderr}")
            raise RuntimeError(f"whisper.cpp transcription failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("whisper.cpp transcription timed out (>10 minutes)")

        # Parse output
        return self._parse_output(result.stdout, result.stderr, audio_path)

    def _parse_output(self, stdout: str, stderr: str, audio_path: str) -> Dict[str, Any]:
        """
        Parse whisper.cpp output into openai-whisper compatible format.

        Args:
            stdout: Standard output from whisper.cpp
            stderr: Standard error from whisper.cpp
            audio_path: Original audio file path

        Returns:
            Formatted transcription results
        """
        # whisper.cpp with --output-json appends .json to the original filename
        # e.g., audio.wav -> audio.wav.json
        json_output = Path(str(audio_path) + ".json")

        try:
            if json_output.exists():
                # Load JSON output
                with open(json_output, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Convert to openai-whisper format
                segments = []
                for i, segment in enumerate(data.get("transcription", [])):
                    # Use offsets (in milliseconds) and convert to seconds for compatibility
                    offsets = segment.get("offsets", {})
                    start_ms = offsets.get("from", 0)
                    end_ms = offsets.get("to", 0)

                    segments.append({
                        "id": i,
                        "start": start_ms / 1000.0,  # Convert to seconds
                        "end": end_ms / 1000.0,      # Convert to seconds
                        "text": segment.get("text", "").strip(),
                    })

                result = {
                    "text": " ".join(s["text"] for s in segments),
                    "segments": segments,
                    "language": data.get("result", {}).get("language", "unknown")
                }

                # Clean up JSON file
                json_output.unlink()

                return result
            else:
                # Fallback: parse plain text output
                logger.warning("JSON output not found, parsing plain text")
                return self._parse_plain_text(stdout)

        except Exception as e:
            logger.error(f"Failed to parse whisper.cpp output: {e}")
            # Return minimal result from plain text
            return self._parse_plain_text(stdout)

    def _parse_plain_text(self, output: str) -> Dict[str, Any]:
        """
        Parse plain text output from whisper.cpp.

        Args:
            output: Plain text output

        Returns:
            Minimal transcription result
        """
        # Extract timestamps and text from plain output
        segments = []
        full_text = []

        for line in output.split('\n'):
            line = line.strip()
            if not line or line.startswith('['):
                continue

            # Look for timestamp pattern: [00:00:00.000 --> 00:00:03.000]
            if '-->' in line:
                try:
                    timestamp_part, text = line.split(']', 1)
                    start, end = timestamp_part.strip('[]').split('-->')
                    segments.append({
                        "id": len(segments),
                        "start": start.strip(),
                        "end": end.strip(),
                        "text": text.strip()
                    })
                    full_text.append(text.strip())
                except ValueError:
                    continue

        return {
            "text": " ".join(full_text) if full_text else output.strip(),
            "segments": segments,
            "language": "unknown"
        }


def is_ggml_model(model_path: str) -> bool:
    """
    Check if a model path points to a GGML format file.

    Args:
        model_path: Path to model file or model name

    Returns:
        True if path points to .bin file, False otherwise
    """
    if not model_path:
        return False

    path = Path(model_path)

    # Check file extension
    if path.suffix.lower() == '.bin':
        return True

    # Check if path contains 'ggml' (common naming convention)
    if 'ggml' in model_path.lower():
        return True

    return False
