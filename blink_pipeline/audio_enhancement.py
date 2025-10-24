"""
Audio Enhancement Module

Advanced audio enhancement using DeepFilterNet and VAD-based preprocessing.
This module is applied during Stage 3 (transcription) to improve speech
recognition accuracy by reducing noise and normalizing speech levels.

Key Features:
- DeepFilterNet: Neural network-based noise reduction
- VAD Pregain: Voice Activity Detection-based level normalization
- Caching: Enhanced audio is cached to avoid reprocessing
- Graceful Fallback: Pipeline continues with raw audio if enhancement fails

Dependencies:
    - torch
    - torchaudio
    - deepfilternet (pip install deepfilternet)
    - silero-vad (loaded via torch.hub)

Author: Integrated from audio_extract
Date: 2025-10-24
"""

import contextlib
import hashlib
import io
import json
import logging
import shutil
import warnings
from pathlib import Path
from typing import Optional, Tuple

import torch

logger = logging.getLogger(__name__)


def _suppress_audio_warnings() -> None:
    """Suppress common torchaudio and DeepFilterNet warnings."""
    warnings.filterwarnings("ignore", category=UserWarning, module=r"^torchaudio(\.|$)")
    warnings.filterwarnings("ignore", category=FutureWarning, module=r"^torchaudio(\.|$)")
    warnings.filterwarnings("ignore", category=UserWarning, module=r"^df(\.|$)")
    logging.getLogger("torchaudio").setLevel(logging.ERROR)


# Apply warning suppression early
_suppress_audio_warnings()


class AudioEnhancer:
    """
    Audio enhancement using DeepFilterNet and VAD-based pregain normalization.

    This class provides advanced audio enhancement for speech recognition.
    Enhancement is applied to extracted audio before transcription to improve
    speech recognition accuracy in noisy environments.

    Caching:
        Enhanced audio files are cached to avoid reprocessing on subsequent runs.
        Cache keys include the source video path and enhancement configuration.

    Error Handling:
        All enhancement operations are wrapped in try-except blocks. If any
        enhancement step fails, the pipeline falls back to using raw audio.
    """

    def __init__(self, config: dict):
        """
        Initialize the AudioEnhancer with configuration.

        Parameters:
            config: Audio enhancement configuration dictionary with structure:
                {
                    "enabled": bool,
                    "cache_dir": str,
                    "deepfilternet": {
                        "enabled": bool,
                        "model": str,  # "DeepFilterNet", "DeepFilterNet2", "DeepFilterNet3"
                        "post_filter": bool,
                        "pf_beta": float,
                        "atten_lim_db": int,
                        "min_thresh": float,
                        "max_erb_thresh": float,
                        "max_df_thresh": float
                    },
                    "vad_pregain": {
                        "enabled": bool,
                        "target_rms": float,
                        "vad_threshold": float
                    }
                }
        """
        self.config = config
        self.cache_dir = config.get("cache_dir", "output/enhanced_audio_cache")
        self.df_config = config.get("deepfilternet", {})
        self.vad_config = config.get("vad_pregain", {})

        # Create cache directory if it doesn't exist
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

        # Compute config hash for cache invalidation
        self.config_hash = self._compute_config_hash()

        # Lazy initialization state
        self._df_initialized = False
        self._df_handles: Optional[tuple] = None  # (model, df_state, suffix)
        self._vad_initialized = False
        self._vad_model: Optional[torch.nn.Module] = None
        self._vad_utils: Optional[tuple] = None

        logger.info("AudioEnhancer initialized")
        if self.df_config.get("enabled"):
            logger.info(f"  DeepFilterNet: enabled (model: {self.df_config.get('model', 'DeepFilterNet3')})")
        if self.vad_config.get("enabled"):
            logger.info(f"  VAD Pregain: enabled (target RMS: {self.vad_config.get('target_rms', 0.9):.2f})")
        logger.info(f"  Cache directory: {self.cache_dir}")

    def _compute_config_hash(self) -> str:
        """Compute hash of enhancement config for cache invalidation."""
        key_params = {
            "df_model": self.df_config.get("model"),
            "df_enabled": self.df_config.get("enabled"),
            "df_post_filter": self.df_config.get("post_filter"),
            "df_atten_lim": self.df_config.get("atten_lim_db"),
            "vad_enabled": self.vad_config.get("enabled"),
            "vad_target_rms": self.vad_config.get("target_rms"),
            "vad_threshold": self.vad_config.get("vad_threshold"),
        }
        config_str = json.dumps(key_params, sort_keys=True)
        return hashlib.md5(config_str.encode("utf-8")).hexdigest()[:8]

    def _build_cache_path(self, video_path: str) -> Path:
        """Generate cache path for enhanced audio."""
        path_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:8]
        filename = f"enhanced_{self.config_hash}_{Path(video_path).stem}_{path_hash}.wav"
        return Path(self.cache_dir) / filename

    def _check_cache(self, video_path: str, output_path: str) -> bool:
        """Check if cached enhanced audio exists and copy it to output path.

        Returns:
            True if cache hit (output_path populated), False if cache miss
        """
        cache_path = self._build_cache_path(video_path)
        if cache_path.exists():
            try:
                shutil.copy2(cache_path, output_path)
                logger.info(f"Using cached enhanced audio: {cache_path.name}")
                return True
            except Exception as e:
                logger.warning(f"Failed to copy cached audio: {e}")
                return False
        return False

    def _save_to_cache(self, video_path: str, enhanced_path: str) -> None:
        """Save enhanced audio to cache."""
        try:
            cache_path = self._build_cache_path(video_path)
            shutil.copy2(enhanced_path, cache_path)
            logger.debug(f"Cached enhanced audio: {cache_path.name}")
        except Exception as e:
            logger.warning(f"Failed to cache enhanced audio: {e}")

    # ----------------------- VAD Components -----------------------

    def _init_vad(self) -> bool:
        """Lazy-load Silero VAD model and utils.

        Note: VAD model is kept on CPU because Silero's utils operate on CPU
        tensors by default.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._vad_initialized:
            return True
        try:
            logger.info("Loading Silero VAD model...")
            # Load model from torch.hub
            model, utils = torch.hub.load(  # type: ignore
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
            )
            # Extract get_speech_timestamps utility
            try:
                get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks = utils
            except Exception:
                # Some hub versions pack differently
                get_speech_timestamps = utils[0] if isinstance(utils, (list, tuple)) and len(utils) > 0 else None

            self._vad_model = model  # keep on CPU
            self._vad_utils = (get_speech_timestamps,)
            self._vad_initialized = True
            logger.info("Silero VAD initialized (CPU)")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize VAD (pregain will be disabled): {e}")
            return False

    def _apply_vad_pregain(self, wav_path: Path) -> Tuple[bool, str]:
        """Apply VAD-based RMS normalization to boost speech signal.

        Analyzes only speech segments to calculate RMS, avoiding background noise.
        Applies gain to entire audio to reach target RMS level.

        Parameters:
            wav_path: Path to WAV file to normalize (modified in-place)

        Returns:
            (success, message)
        """
        target_rms = self.vad_config.get("target_rms")
        if target_rms is None:
            return True, "Pregain disabled"

        try:
            import torchaudio
            import numpy as np

            if not self._init_vad():
                logger.warning("VAD not available, skipping pregain")
                return True, "VAD unavailable"

            # Load audio
            waveform, sample_rate = torchaudio.load(str(wav_path))

            # Ensure mono for VAD
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)

            # Resample to 16kHz for VAD if needed (CPU)
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(
                    orig_freq=sample_rate,
                    new_freq=16000
                )
                waveform_16k = resampler(waveform)
            else:
                waveform_16k = waveform

            # Use Silero helper to get speech timestamps at 16kHz
            get_speech_timestamps = self._vad_utils[0] if self._vad_utils else None
            if get_speech_timestamps is None or self._vad_model is None:
                logger.warning("VAD utils not available, skipping pregain")
                return True, "VAD utils unavailable"

            # Get speech timestamps (expects 1D tensor)
            wav_1d = waveform_16k.squeeze(0)
            vad_threshold = float(self.vad_config.get("vad_threshold", 0.5))
            with torch.no_grad():
                speech_ts = get_speech_timestamps(
                    wav_1d, self._vad_model, threshold=vad_threshold, sampling_rate=16000
                )

            # Create speech mask for original waveform
            speech_mask = np.zeros(waveform.shape[1], dtype=bool)
            for seg in speech_ts or []:
                start16 = int(seg.get("start", 0))
                end16 = int(seg.get("end", 0))
                if end16 <= start16:
                    continue
                # Map to original sample rate
                start = int(start16 * sample_rate / 16000)
                end = int(end16 * sample_rate / 16000)
                start = max(0, min(start, speech_mask.size - 1))
                end = max(start + 1, min(end, speech_mask.size))
                speech_mask[start:end] = True

            # Calculate RMS only on speech segments
            waveform_np = waveform.cpu().numpy()
            speech_samples = waveform_np[0, speech_mask]

            if len(speech_samples) == 0:
                logger.warning(f"No speech detected in {wav_path.name}, skipping pregain")
                return True, "No speech detected"

            current_rms = np.sqrt(np.mean(speech_samples ** 2))

            if current_rms < 1e-6:
                logger.warning(f"Audio too quiet in {wav_path.name}, skipping pregain")
                return True, "Audio too quiet"

            # Calculate gain to reach target RMS
            gain = target_rms / current_rms

            # Clamp gain to reasonable range (prevent extreme amplification)
            gain = np.clip(gain, 0.1, 10.0)

            # Apply gain
            waveform_normalized = waveform * gain

            # Check for clipping and reduce gain if needed
            max_val = waveform_normalized.abs().max().item()
            if max_val > 0.99:
                gain = gain * (0.99 / max_val)
                waveform_normalized = waveform * gain
                logger.info(f"Reduced gain to {gain:.2f}x to prevent clipping")

            # Save normalized audio
            torchaudio.save(
                str(wav_path),
                waveform_normalized.cpu(),
                sample_rate
            )

            speech_ratio = len(speech_samples) / len(waveform_np[0])
            logger.info(
                f"Applied VAD-based pregain: {current_rms:.4f} → {target_rms:.4f} "
                f"(gain: {gain:.2f}x, speech: {speech_ratio*100:.1f}%)"
            )

            return True, f"Pregain applied: {gain:.2f}x"

        except Exception as e:
            logger.error(f"Pregain normalization failed: {e}")
            return False, f"Pregain error: {e}"

    # ----------------------- DeepFilterNet Components -----------------------

    def _init_deepfilter(self) -> bool:
        """Lazy-load and initialize DeepFilterNet model/state once.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._df_initialized:
            return True
        try:
            # Import only when needed to avoid heavy imports if denoise is off
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module=r"^torchaudio(\.|$)")
                warnings.filterwarnings("ignore", category=FutureWarning, module=r"^torchaudio(\.|$)")
                warnings.filterwarnings("ignore", category=UserWarning, module=r"^df(\.|$)")
                from df.enhance import init_df  # type: ignore

            # Silence git stderr invoked inside DeepFilterNet's df.utils
            try:
                import df.utils as df_utils  # type: ignore
                import subprocess as _sub

                # Save the original function BEFORE patching
                _original_check_output = _sub.check_output

                def _quiet_check_output(args, *pargs, **kwargs):
                    kwargs.setdefault("stderr", _sub.DEVNULL)
                    return _original_check_output(args, *pargs, **kwargs)

                df_utils.subprocess.check_output = _quiet_check_output
            except Exception:
                pass  # Patching is optional

        except Exception as e:
            logger.error("DeepFilterNet not available. Install with: pip install torch torchaudio deepfilternet")
            logger.error(f"Import error: {e}")
            return False

        try:
            logger.info("Loading DeepFilterNet model...")
            # Suppress noisy git stderr
            with contextlib.redirect_stderr(io.StringIO()):
                model_name = self.df_config.get("model", "DeepFilterNet3")
                post_filter = self.df_config.get("post_filter", False)
                out = init_df(
                    model_base_dir=model_name,
                    post_filter=post_filter,
                    log_level="INFO",
                )

            # Handle different return signatures
            try:
                if isinstance(out, tuple) and len(out) == 4:
                    model, df_state, suffix, _epoch = out   # type: ignore
                else:
                    model, df_state, suffix = out
            except Exception:
                model, df_state, suffix = out[0], out[1], out[2]

            self._df_handles = (model, df_state, suffix)
            self._df_initialized = True
            logger.info(f"DeepFilterNet model initialized: {model_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize DeepFilterNet: {e}")
            return False

    def _denoise_with_deepfilter(self, in_wav: Path, out_wav: Path) -> Tuple[bool, str]:
        """Run DeepFilterNet denoising from input WAV to output WAV.

        Uses df.enhance utilities to load, enhance, and save audio at model sr.
        Optionally applies VAD-based pregain normalization before denoising.

        Parameters:
            in_wav: Input WAV file path
            out_wav: Output WAV file path

        Returns:
            (success, message or output path)
        """
        try:
            # Apply VAD-based pregain normalization if enabled
            if self.vad_config.get("enabled"):
                ok, msg = self._apply_vad_pregain(in_wav)
                if not ok:
                    logger.warning(f"Pregain failed, proceeding with denoise: {msg}")

            if not self._init_deepfilter():
                return False, "DeepFilterNet not initialized"

            from df.enhance import enhance, load_audio, save_audio  # type: ignore

            assert self._df_handles is not None
            model, df_state, _ = self._df_handles

            # Select device: prefer MPS (Apple Silicon) > CUDA > CPU
            device_str = (
                "mps" if torch.backends.mps.is_available() else (
                    "cuda:0" if torch.cuda.is_available() else "cpu"
                )
            )

            # Ensure DeepFilterNet uses the same device internally
            try:
                from df.config import config as df_config  # type: ignore
                df_config.set("DEVICE", device_str, str, section="train")
            except Exception:
                pass  # If this fails, DF will fall back to auto-detect

            # Load audio at DeepFilterNet's sample rate
            audio, _meta = load_audio(str(in_wav), sr=df_state.sr())

            # Move model to chosen device
            model = model.to(torch.device(device_str))
            logger.info(f"DeepFilterNet enhancing on device: {device_str}")

            # Get attenuation limit from config
            atten_lim_db = self.df_config.get("atten_lim_db", 100)

            try:
                enhanced = enhance(
                    model,
                    df_state,
                    audio,
                    pad=True,
                    atten_lim_db=atten_lim_db,
                )
            except Exception as e:
                # Fallback: if MPS/CUDA path fails, retry on CPU
                if device_str != "cpu":
                    try:
                        from df.config import config as df_config  # type: ignore
                        df_config.set("DEVICE", "cpu", str, section="train")
                    except Exception:
                        pass
                    model = model.to(torch.device("cpu"))
                    logger.warning(f"DeepFilterNet enhance failed on {device_str}, retrying on CPU: {e}")
                    enhanced = enhance(
                        model,
                        df_state,
                        audio,
                        pad=True,
                        atten_lim_db=atten_lim_db,
                    )
                else:
                    raise

            # Save enhanced audio
            save_audio(str(out_wav), enhanced, df_state.sr())
            return True, str(out_wav)

        except Exception as e:
            return False, f"DeepFilterNet error: {e}"

    # ----------------------- Public API -----------------------

    def enhance_audio_file(
        self,
        input_wav: str,
        output_wav: str,
        video_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Enhance audio file using DeepFilterNet and VAD pregain.

        This is the main entry point for audio enhancement. It handles caching,
        error recovery, and graceful fallback to raw audio if enhancement fails.

        Parameters:
            input_wav: Path to input WAV file (raw extracted audio)
            output_wav: Path to write enhanced WAV file
            video_path: Optional path to source video (for cache key)

        Returns:
            (success, message)
            - success: True if output_wav contains valid audio (enhanced or raw)
            - message: Status message describing what happened
        """
        input_path = Path(input_wav)
        output_path = Path(output_wav)

        # Check cache first
        if video_path and self._check_cache(video_path, str(output_path)):
            return True, "Using cached enhanced audio"

        # If enhancement is disabled, just copy input to output
        if not self.df_config.get("enabled"):
            try:
                shutil.copy2(input_path, output_path)
                return True, "Enhancement disabled, using raw audio"
            except Exception as e:
                return False, f"Failed to copy audio: {e}"

        # Perform enhancement
        try:
            success, msg = self._denoise_with_deepfilter(input_path, output_path)

            if success:
                # Save to cache
                if video_path:
                    self._save_to_cache(video_path, str(output_path))
                return True, "Enhanced successfully"
            else:
                # Enhancement failed, use raw audio
                logger.warning(f"Enhancement failed: {msg}, using raw audio")
                shutil.copy2(input_path, output_path)
                return True, "Enhancement failed, using raw audio"

        except Exception as e:
            # Critical failure, ensure output exists
            logger.error(f"Audio enhancement failed critically: {e}")
            try:
                if not output_path.exists():
                    shutil.copy2(input_path, output_path)
                return True, f"Using raw audio due to error: {e}"
            except Exception as copy_error:
                return False, f"Failed to provide fallback audio: {copy_error}"


__all__ = ["AudioEnhancer"]
