import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

# Optional heavy dependencies: make imports resilient so utility functions
# and tests that don't require these libs can still run in lightweight envs.
try:  # torch is used to pick device when device=="auto"; optional for tests
    import torch  # type: ignore
except Exception:  # pragma: no cover - absence is acceptable for non-ML paths/tests
    torch = None  # type: ignore

try:  # openai-whisper backend; optional if using whisper.cpp or for unit tests
    import whisper  # type: ignore
except Exception:  # pragma: no cover
    whisper = None  # type: ignore

try:  # diarization backend; optional for unit tests that don't run diarization
    from pyannote.audio import Pipeline  # type: ignore
    from pyannote.core import Annotation  # type: ignore
    from pyannote.core import Segment  # type: ignore
except Exception:  # pragma: no cover
    Pipeline = None  # type: ignore
    Annotation = None  # type: ignore
    Segment = None  # type: ignore
from src.media_utils import MediaInfo, extract_audio_segment, probe_media_info
from src.whisper_cpp_wrapper import WhisperCppWrapper, is_ggml_model


@dataclass
class WhisperSettings:
    model_name: str
    device: str
    compute_type: str
    temperature: float
    beam_size: int
    language: Optional[str] = None
    ggml_model_path: Optional[str] = None
    whisper_cpp_binary: Optional[str] = None


@dataclass
class DiarizationSettings:
    model_id: str
    auth_token: Optional[str]
    min_overlap_ratio: float


def process_audio_for_transcription(
    video_paths: List[str], config: Dict[str, Any], progress_callback=None
) -> Optional[Dict[str, Any]]:
    """Transcribe and diarise a list of clips while keeping resource usage bounded.

    Args:
        video_paths: List of paths to video files to process
        config: Configuration dictionary
        progress_callback: Optional callable(completed_count: int) to report progress
    """

    if whisper is None:
        raise RuntimeError(
            "openai-whisper is not installed. Install it via 'pip install openai-whisper' to enable transcription."
        )

    if Pipeline is None or Segment is None:
        raise RuntimeError(
            "pyannote.audio is not installed. Install it via 'pip install pyannote.audio' and provide a Hugging Face token."
        )

    if not video_paths:
        logging.warning("No video paths provided for transcription.")
        return None

    transcription_config = config.get("transcription", {})
    whisper_settings = _parse_whisper_settings(transcription_config.get("whisper", {}))
    diarization_settings = _parse_diarization_settings(transcription_config.get("diarization", {}))

    transcriber = _WhisperTranscriber(whisper_settings)
    diarizer = _PyannoteDiarizer(diarization_settings)

    logging.info("Processing %d clips sequentially for transcription", len(video_paths))

    timeline: List[Dict[str, Any]] = []
    full_segments: List[Dict[str, Any]] = []
    running_offset = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        for index, path in enumerate(video_paths):
            clip_name = os.path.basename(path)
            logging.info(f"  [{index+1}/{len(video_paths)}] Processing clip: {clip_name}")

            # Probe video metadata (all videos are pre-validated in Stage 0)
            media_info: MediaInfo = probe_media_info(path)

            if not media_info.has_audio or media_info.duration <= 0.0:
                logging.warning(f"    ⚠ Clip has no usable audio track, skipping")
                clip_entry = {
                    "path": path,
                    "offset": running_offset,
                    "duration": media_info.duration,
                    "has_audio": media_info.has_audio,
                }
                timeline.append(clip_entry)
                running_offset += media_info.duration
                continue

            # Create timeline entry (path already points to validated/repaired video from Stage 0)
            clip_entry = {
                "path": path,
                "offset": running_offset,
                "duration": media_info.duration,
                "has_audio": media_info.has_audio,
            }
            timeline.append(clip_entry)

            scratch_audio_path = os.path.join(tmpdir, f"clip_{index}.wav")
            if not extract_audio_segment(path, scratch_audio_path):
                logging.error(f"    ✗ Failed to extract audio")
                running_offset += media_info.duration
                continue

            logging.info(f"    → Transcribing audio ({media_info.duration:.1f}s)...")
            transcript_segments = transcriber.transcribe_file(scratch_audio_path)
            if not transcript_segments:
                logging.warning(f"    ⚠ No speech detected in audio")
                running_offset += media_info.duration
                continue
            logging.info(f"    ✓ Found {len(transcript_segments)} speech segment(s)")

            logging.info(f"    → Running speaker diarization...")
            diarization_annotation = diarizer.diarize_file(scratch_audio_path)
            labelled_segments = _assign_speakers(
                transcript_segments,
                diarization_annotation,
                diarization_settings.min_overlap_ratio,
            )
            logging.info(f"    ✓ Assigned speakers to {len(labelled_segments)} segment(s)")

            for segment in labelled_segments:
                full_segments.append(
                    {
                        "start": round(segment["start"] + running_offset, 2),
                        "end": round(segment["end"] + running_offset, 2),
                        "speaker": segment["speaker"],
                        "text": segment["text"],
                    }
                )

            running_offset += media_info.duration

            # Report progress after completing each clip
            if progress_callback:
                progress_callback(index + 1)

    if not full_segments:
        logging.warning("No transcript segments were produced.")
        return None

    return {"segments": full_segments, "timeline": timeline}


def _parse_whisper_settings(config: Dict[str, Any]) -> WhisperSettings:
    model_name = config.get("model_name", "small")
    device_setting = config.get("device", "auto")
    compute_type = config.get("compute_type", "float16")
    temperature = float(config.get("temperature", 0.0))
    beam_size = int(config.get("beam_size", 5))
    language = config.get("language")  # None for auto-detect
    ggml_model_path = config.get("ggml_model_path")
    whisper_cpp_binary = config.get("whisper_cpp_binary")

    # Core ML support for Apple Silicon
    if device_setting == "coreml":
        # Require Core ML model path (.mlmodelc or .mlpackage directory)
        if not ggml_model_path:
            raise RuntimeError(
                "Core ML device selected, but ggml_model_path is not set. "
                "Set ggml_model_path to a Core ML model directory (.mlmodelc or .mlpackage)."
            )
        if not (ggml_model_path.endswith(".mlmodelc") or ggml_model_path.endswith(".mlpackage")):
            raise RuntimeError(
                f"Core ML device selected, but ggml_model_path does not end in .mlmodelc or .mlpackage: {ggml_model_path}\n"
                "Convert your GGML model to Core ML format and set ggml_model_path accordingly."
            )
        compute_type = "float32"  # Not used, but set for compatibility
    elif device_setting == "auto":
        if torch is not None and torch.cuda.is_available():
            device_setting = "cuda"
        else:
            device_setting = "cpu"
    if device_setting == "cpu":
        compute_type = "float32"  # whisper expects fp32 on CPU for stability

    return WhisperSettings(
        model_name=model_name,
        device=device_setting,
        compute_type=compute_type,
        temperature=temperature,
        beam_size=beam_size,
        language=language,
        ggml_model_path=ggml_model_path,
        whisper_cpp_binary=whisper_cpp_binary,
    )


def _parse_diarization_settings(config: Dict[str, Any]) -> DiarizationSettings:
    model_id = config.get("model_id", "pyannote/speaker-diarization-3.1")
    token = config.get("auth_token")
    token_env = config.get("auth_token_env", ["HUGGINGFACE_TOKEN", "HF_TOKEN"])
    if isinstance(token_env, str):
        env_candidates = [token_env]
    else:
        env_candidates = list(token_env)

    if token is None:
        for env_name in env_candidates:
            token = os.getenv(env_name)
            if token:
                break
    if token is None:
        raise RuntimeError(
            "pyannote diarization requires an authentication token. Set 'auth_token' in the config "
            "or define one of the environment variables: "
            + ", ".join(env_candidates)
            + "."
        )

    min_overlap_ratio = float(config.get("min_overlap_ratio", 0.6))

    return DiarizationSettings(
        model_id=model_id,
        auth_token=token,
        min_overlap_ratio=min_overlap_ratio,
    )


class _WhisperTranscriber:
    """Thin wrapper around openai-whisper or whisper.cpp with sensible defaults."""

    def __init__(self, settings: WhisperSettings) -> None:
        self.settings = settings
        # Pre-init to keep __init__ free of any return value and satisfy type checkers
        self.model: Any = None
        self.use_whisper_cpp: bool = False

        # Core ML support: use whisper.cpp with Core ML model
        if settings.device == "coreml":
            logging.info("Using whisper.cpp with Core ML model: %s", settings.ggml_model_path)
            self.use_whisper_cpp = True
            self.model = WhisperCppWrapper(
                model_path=settings.ggml_model_path,
                whisper_cpp_binary=settings.whisper_cpp_binary,
                device="coreml",
                compute_type=settings.compute_type
            )
        # GGML model (whisper.cpp)
        elif settings.ggml_model_path and is_ggml_model(settings.ggml_model_path):
            logging.info("Using whisper.cpp with GGML model: %s", settings.ggml_model_path)
            self.use_whisper_cpp = True
            self.model = WhisperCppWrapper(
                model_path=settings.ggml_model_path,
                whisper_cpp_binary=settings.whisper_cpp_binary,
                device=settings.device,
                compute_type=settings.compute_type
            )
        else:
            # Standard openai-whisper path
            if whisper is None:
                raise RuntimeError(
                    "openai-whisper is required to instantiate the transcription engine."
                )
            self.use_whisper_cpp = False
            logging.info("Loading Whisper model '%s' on %s", settings.model_name, settings.device)
            self.model = whisper.load_model(settings.model_name, device=settings.device)

    def transcribe_file(self, audio_path: str) -> List[Dict[str, Any]]:
        if self.use_whisper_cpp:
            # Use whisper.cpp wrapper
            result = self.model.transcribe(
                audio_path,
                language=self.settings.language,
                task="transcribe",
                # Note: whisper.cpp doesn't support all openai-whisper options
            )
        else:
            # Use openai-whisper
            transcribe_kwargs = {
                "fp16": self.settings.compute_type == "float16",
                "temperature": self.settings.temperature,
                "beam_size": self.settings.beam_size,
                "condition_on_previous_text": False,
                "verbose": False,
            }

            # Add language parameter if specified (None means auto-detect)
            if self.settings.language:
                transcribe_kwargs["language"] = self.settings.language

            result = self.model.transcribe(audio_path, **transcribe_kwargs)

        segments = []
        for seg in result.get("segments", []):
            text = seg.get("text", "").strip()
            if not text:
                continue

            # Handle different timestamp formats
            start = seg.get("start", 0.0)
            end = seg.get("end", 0.0)

            # Convert timestamp strings to floats if needed (from whisper.cpp)
            if isinstance(start, str):
                start = self._parse_timestamp(start)
            if isinstance(end, str):
                end = self._parse_timestamp(end)

            segments.append(
                {
                    "start": float(start),
                    "end": float(end),
                    "text": text,
                }
            )
        return segments

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> float:
        """Convert timestamp string like '00:00:03.450' to float seconds."""
        try:
            parts = timestamp_str.strip().replace(',', '.').split(':')
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
            elif len(parts) == 2:
                minutes, seconds = parts
                return float(minutes) * 60 + float(seconds)
            else:
                return float(timestamp_str)
        except (ValueError, AttributeError):
            return 0.0

class _PyannoteDiarizer:
    """Wrapper around pyannote speaker diarization Pipeline."""

    def __init__(self, settings: DiarizationSettings) -> None:
        if Pipeline is None:
            raise RuntimeError(
                "pyannote.audio is required to instantiate the diarization engine."
            )
        self.settings = settings
        logging.info("Loading pyannote pipeline '%s'", settings.model_id)
        # Avoid strict typing here so module can import without pyannote installed in test envs
        self.pipeline = Pipeline.from_pretrained(settings.model_id, token=settings.auth_token)

    def diarize_file(self, audio_path: str) -> Any:
        """Run diarization and return Annotation object."""
        if self.pipeline is None:
            raise RuntimeError(
                "pyannote.audio Pipeline is not initialized. Ensure dependencies are installed."
            )
        diarization_output = self.pipeline(audio_path)
        # Extract the Annotation from DiarizeOutput
        return diarization_output.speaker_diarization


def _assign_speakers(
    transcript_segments: Iterable[Dict[str, Any]],
    diarization_annotation: Any,
    min_overlap_ratio: float,
) -> List[Dict[str, Any]]:
    """Annotate transcript segments with speaker labels from diarization output."""

    diarization_tracks = list(diarization_annotation.itertracks(yield_label=True))
    labelled_segments: List[Dict[str, Any]] = []

    for segment in transcript_segments:
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        text = segment.get("text", "").strip()
        if not text or end <= start:
            continue

        speaker = _select_speaker(diarization_tracks, start, end, min_overlap_ratio)
        labelled_segments.append({"start": start, "end": end, "text": text, "speaker": speaker})

    return labelled_segments


def _select_speaker(tracks, start: float, end: float, min_overlap_ratio: float) -> str:
    if Segment is None:
        raise RuntimeError(
            "pyannote.core Segment is unavailable. Ensure pyannote.audio is installed correctly."
        )

    candidate_segment = Segment(start, end)
    overlap_by_speaker: Dict[str, float] = {}

    for diarization_segment, _, speaker_label in tracks:
        intersection = diarization_segment & candidate_segment
        if intersection:
            overlap_by_speaker[speaker_label] = overlap_by_speaker.get(speaker_label, 0.0) + intersection.duration

    if not overlap_by_speaker:
        return "unknown-speaker"

    best_speaker, best_overlap = max(overlap_by_speaker.items(), key=lambda item: item[1])
    duration = candidate_segment.duration
    if duration <= 0:
        return best_speaker

    if (best_overlap / duration) < min_overlap_ratio:
        return "unknown-speaker"

    return best_speaker
