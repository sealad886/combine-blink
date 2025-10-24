"""
Audio-Video Alignment Engine
============================

Modular, testable alignment implementation using GCC-PHAT algorithm.

Features:
- GCC-PHAT cross-correlation for sub-sample precision
- Multi-window analysis with 50% overlap
- Median filtering for robustness
- Optional drift estimation
- Caching support for performance

Algorithm Details:
- FFT-based cross-correlation: R = SIG × conj(REFSIG)
- PHAT weighting: R / |R| for robustness to noise
- 16x interpolation for sub-sample precision
- Multi-window analysis (12s windows, 6s hop)
- Median filtering to reject outliers

Performance:
- 16kHz downsampling for speed
- Bandpass filter (300-3000 Hz) for speech frequencies
- Audio caching via audio_cache module
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..audio_cache import ensure_wav_cache


@dataclass(frozen=True)
class AlignmentConfig:
    """Configuration for audio alignment.

    Attributes:
        enabled: Whether alignment is enabled
        max_shift: Maximum time shift to search in seconds
        window_seconds: Window size for multi-window analysis
        sample_rate: Sample rate for alignment (lower = faster)
        bandpass_enabled: Whether to apply bandpass filter
        bandpass_lowcut: Low-frequency cutoff (Hz)
        bandpass_highcut: High-frequency cutoff (Hz)
        interpolation_factor: Interpolation factor for sub-sample precision
        estimate_drift: Whether to estimate drift (currently not recommended)
    """
    enabled: bool = True
    max_shift: float = 1.5
    window_seconds: float = 12.0
    sample_rate: int = 16000
    bandpass_enabled: bool = True
    bandpass_lowcut: float = 300.0
    bandpass_highcut: float = 3000.0
    interpolation_factor: int = 16
    estimate_drift: bool = False


@dataclass(frozen=True)
class AlignmentResult:
    """Result of audio alignment for a single camera.

    Attributes:
        camera: Camera identifier
        offset_seconds: Time offset in seconds (positive = camera ahead of reference)
        drift: Drift coefficient (if estimate_drift=True, otherwise None)
        confidence: Confidence score (0-1, based on cross-correlation peak)
        num_windows: Number of windows analyzed
        offset_std: Standard deviation of offset across windows
    """
    camera: str
    offset_seconds: float
    drift: Optional[float] = None
    confidence: float = 1.0
    num_windows: int = 1
    offset_std: float = 0.0


class AlignmentEngine:
    """Audio-Video alignment engine using GCC-PHAT algorithm.

    This engine analyzes audio from multiple camera clips to determine
    time offsets and optional drift coefficients.

    Algorithm:
    1. Extract audio segments from each camera clip
    2. Downsample to configured sample rate (default 16kHz)
    3. Apply bandpass filter (300-3000 Hz for speech)
    4. Run GCC-PHAT cross-correlation on multiple windows
    5. Use median filtering to reject outliers
    6. Optionally estimate drift (linear time scaling)

    Example:
        ```python
        config = AlignmentConfig(
            enabled=True,
            max_shift=1.5,
            window_seconds=12.0,
            sample_rate=16000
        )
        engine = AlignmentEngine(config)

        results = engine.align_clips(
            camera_clips={"cam1": [clip1], "cam2": [clip2]},
            ref_camera="cam1"
        )

        for result in results:
            print(f"{result.camera}: {result.offset_seconds:.3f}s offset")
        ```
    """

    def __init__(self, config: AlignmentConfig):
        """Initialize alignment engine with configuration.

        Args:
            config: Alignment configuration
        """
        self.config = config
        # Adapter: allow using either dataclass AlignmentConfig or pydantic config
        # with different field names (e.g., max_shift_seconds vs max_shift).

    # Internal config accessor with alias and default support
    def _cfg(self, name: str, default, alias: Optional[str] = None):
        val = getattr(self.config, name, None)
        if val is None and alias is not None:
            val = getattr(self.config, alias, None)
        return default if val is None else val

    def align_clips(
        self,
        camera_clips: Dict[str, List[Path]],
        ref_camera: str
    ) -> List[AlignmentResult]:
        """Align all cameras to reference camera.

        Args:
            camera_clips: Dict mapping camera -> list of clip paths
            ref_camera: Reference camera identifier

        Returns:
            List of AlignmentResult for each camera (excluding reference)

        Raises:
            ValueError: If ref_camera not in camera_clips
            ValueError: If any camera has no clips
        """
        if ref_camera not in camera_clips:
            raise ValueError(f"Reference camera '{ref_camera}' not found in camera_clips")

        if not camera_clips[ref_camera]:
            raise ValueError(f"Reference camera '{ref_camera}' has no clips")

        # Use first clip from each camera for alignment
        ref_clip = camera_clips[ref_camera][0]

        results: List[AlignmentResult] = []
        estimate_drift = bool(self._cfg('estimate_drift', False))
        for camera, clips in camera_clips.items():
            if camera == ref_camera:
                continue  # Don't align reference to itself

            if not clips:
                raise ValueError(f"Camera '{camera}' has no clips")

            camera_clip = clips[0]

            # Estimate offset and drift
            offset, drift, confidence, num_windows, offset_std = self._estimate_offset(
                camera_clip=camera_clip,
                ref_clip=ref_clip
            )

            results.append(AlignmentResult(
                camera=camera,
                offset_seconds=offset,
                drift=drift if estimate_drift else None,
                confidence=confidence,
                num_windows=num_windows,
                offset_std=offset_std
            ))

        return results

    def _estimate_offset(
        self,
        camera_clip: Path,
        ref_clip: Path
    ) -> Tuple[float, float | None, float, int, float]:
        """Estimate offset and optional drift between two clips.

        Args:
            camera_clip: Path to camera clip
            ref_clip: Path to reference clip

        Returns:
            Tuple of (offset_seconds, drift, confidence, num_windows, offset_std)
        """
        # Extract audio segments
        camera_audio = self._extract_audio_segment(camera_clip)
        ref_audio = self._extract_audio_segment(ref_clip)

        if camera_audio is None or ref_audio is None:
            # No audio - return zero offset
            return 0.0, None, 0.0, 0, 0.0

        # Multi-window analysis
        window_seconds = float(self._cfg('window_seconds', 12.0, 'analysis_window_seconds'))
        sample_rate = int(self._cfg('sample_rate', 16000))
        window_samples = int(window_seconds * sample_rate)
        hop_samples = window_samples // 2  # 50% overlap

        min_length = min(len(camera_audio), len(ref_audio))
        if min_length < window_samples:
            # Single window analysis
            max_shift = float(self._cfg('max_shift', 1.5, 'max_shift_seconds'))
            interp = int(getattr(self.config, 'interpolation_factor', 16))
            offset = self._gcc_phat(
                sig=camera_audio,
                refsig=ref_audio,
                fs=sample_rate,
                max_tau=max_shift,
                interp=interp
            )
            return offset, None, 1.0, 1, 0.0

        # Multiple windows
        offsets = []
        num_windows = (min_length - window_samples) // hop_samples + 1

        for i in range(num_windows):
            start = i * hop_samples
            end = start + window_samples

            if end > min_length:
                break

            camera_window = camera_audio[start:end]
            ref_window = ref_audio[start:end]

            max_shift = float(self._cfg('max_shift', 1.5, 'max_shift_seconds'))
            interp = int(getattr(self.config, 'interpolation_factor', 16))
            offset = self._gcc_phat(
                sig=camera_window,
                refsig=ref_window,
                fs=sample_rate,
                max_tau=max_shift,
                interp=interp
            )
            offsets.append(offset)

        if not offsets:
            return 0.0, None, 0.0, 0, 0.0

        # Use median for robustness
        median_offset = float(np.median(offsets))
        offset_std = float(np.std(offsets))

        # Estimate drift if enabled
        drift = None
        estimate_drift = bool(self._cfg('estimate_drift', False))
        if estimate_drift and len(offsets) > 1:
            # Linear regression: offset = drift * time + intercept
            times = np.array([i * window_seconds / 2 for i in range(len(offsets))])
            offsets_array = np.array(offsets)

            # Fit line
            coeffs = np.polyfit(times, offsets_array, 1)
            drift = float(coeffs[0])  # Slope = drift

        # Confidence based on offset_std (lower std = higher confidence)
        confidence = 1.0 / (1.0 + offset_std)

        return median_offset, drift, confidence, len(offsets), offset_std

    def _gcc_phat(
        self,
        sig: np.ndarray,
        refsig: np.ndarray,
        fs: int,
        max_tau: float,
        interp: int = 1
    ) -> float:
        """Generalized Cross-Correlation Phase Transform (GCC-PHAT).

        This algorithm estimates the time delay between two signals using
        FFT-based cross-correlation with PHAT (PHase Transform) weighting.

        Algorithm:
        1. Compute FFT of both signals
        2. Compute cross-power spectrum: R = SIG × conj(REFSIG)
        3. Apply PHAT weighting: R / |R| (normalizes magnitude, keeps phase)
        4. Compute IFFT to get cross-correlation
        5. Find peak to determine time delay
        6. Optional: interpolate for sub-sample precision

        Args:
            sig: Signal to align (camera audio)
            refsig: Reference signal
            fs: Sample rate in Hz
            max_tau: Maximum time delay to search (seconds)
            interp: Interpolation factor for sub-sample precision (1=no interp)

        Returns:
            Time delay in seconds (positive = sig ahead of refsig)
        """
        # Ensure same length
        n = max(len(sig), len(refsig))

        if n <= 2:
            return 0.0

        # Zero-pad to same length
        sig_padded = np.zeros(n)
        sig_padded[:len(sig)] = sig

        refsig_padded = np.zeros(n)
        refsig_padded[:len(refsig)] = refsig

        # FFT
        SIG = np.fft.rfft(sig_padded)
        REFSIG = np.fft.rfft(refsig_padded)

        # Cross-power spectrum
        R = SIG * np.conj(REFSIG)

        # PHAT weighting: R / |R|
        denom = np.abs(R)
        denom[denom == 0] = 1e-12

        # IFFT to get cross-correlation (with interpolation)
        cc = np.fft.irfft(R / denom, n=(interp * n))

        # Calculate max_shift based on interpolation
        max_shift = int(interp * n / 2)
        if max_tau is not None:
            max_shift = min(int(interp * fs * max_tau), max_shift)

        # Extract search region
        cc_search = np.concatenate([cc[-max_shift:], cc[:max_shift + 1]])

        # Find peak
        peak_idx = int(np.argmax(cc_search))
        shift_samples = peak_idx - max_shift

        # Convert to seconds
        tau_seconds = float(shift_samples) / float(interp * fs)

        return tau_seconds

    def _extract_audio_segment(
        self,
        clip_path: Path,
        start_seconds: float = 0.0,
        duration_seconds: Optional[float] = None
    ) -> np.ndarray | None:
        """Extract audio segment from clip.

        Uses audio_cache module for caching WAV files. Applies bandpass
        filter if configured.

        Args:
            clip_path: Path to video/audio clip
            start_seconds: Start time in seconds
            duration_seconds: Duration in seconds (None = entire clip)

        Returns:
            Audio as numpy array, or None if no audio
        """
        try:
            # Resolve configuration with compatibility aliases
            sr = int(self._cfg('sample_rate', 16000))
            bandpass = bool(self._cfg('bandpass_enabled', True, 'bandpass'))
            hp = int(self._cfg('bandpass_lowcut', 300, 'highpass_hz')) if bandpass else 0
            lp = int(self._cfg('bandpass_highcut', 3000, 'lowpass_hz')) if bandpass else 0

            # Use audio_cache for efficient extraction
            wav_path = ensure_wav_cache(
                str(clip_path),
                sr=sr,
                bandpass=bandpass,
                hp=hp,
                lp=lp
            )

            if wav_path is None:
                return None

            # Load audio
            import librosa

            audio, _ = librosa.load(
                wav_path,
                sr=sr,
                offset=start_seconds,
                duration=duration_seconds
            )

            return audio

        except Exception:
            return None


class CachedAlignmentEngine(AlignmentEngine):
    """Alignment engine with result caching.

    Caches alignment results to avoid re-computing for identical inputs.
    Cache key is based on (camera_clip_path, ref_clip_path, config).

    Example:
        ```python
        config = AlignmentConfig()
        engine = CachedAlignmentEngine(config)

        # First call computes alignment
        results1 = engine.align_clips(camera_clips, ref_camera)

        # Second call uses cache
        results2 = engine.align_clips(camera_clips, ref_camera)
        assert results1 == results2
        ```
    """

    def __init__(self, config: AlignmentConfig):
        """Initialize cached alignment engine.

        Args:
            config: Alignment configuration
        """
        super().__init__(config)
        self._cache: Dict[tuple, AlignmentResult] = {}

    def _estimate_offset(
        self,
        camera_clip: Path,
        ref_clip: Path
    ) -> Tuple[float, float | None, float, int, float]:
        """Estimate offset with caching.

        Args:
            camera_clip: Path to camera clip
            ref_clip: Path to reference clip

        Returns:
            Tuple of (offset_seconds, drift, confidence, num_windows, offset_std)
        """
        # Create cache key
        cache_key = (
            str(camera_clip),
            str(ref_clip),
            float(self._cfg('max_shift', 1.5, 'max_shift_seconds')),
            float(self._cfg('window_seconds', 12.0, 'analysis_window_seconds')),
            int(self._cfg('sample_rate', 16000)),
            bool(self._cfg('bandpass_enabled', True, 'bandpass')),
            int(getattr(self.config, 'interpolation_factor', 16)),
            bool(self._cfg('estimate_drift', False))
        )

        if cache_key in self._cache:
            result = self._cache[cache_key]
            return (
                result.offset_seconds,
                result.drift,
                result.confidence,
                result.num_windows,
                result.offset_std
            )

        # Compute alignment
        offset, drift, confidence, num_windows, offset_std = super()._estimate_offset(
            camera_clip, ref_clip
        )

        # Cache result
        self._cache[cache_key] = AlignmentResult(
            camera="",  # Not used in cache
            offset_seconds=offset,
            drift=drift,
            confidence=confidence,
            num_windows=num_windows,
            offset_std=offset_std
        )

        return offset, drift, confidence, num_windows, offset_std

    def clear_cache(self) -> None:
        """Clear alignment cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


__all__ = ['AlignmentConfig', 'AlignmentResult', 'AlignmentEngine', 'CachedAlignmentEngine']
