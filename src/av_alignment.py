"""
Robust audio alignment utilities for multi-camera composition.

Multi-window GCC-PHAT time delay estimation with optional drift model.
This version slices from a cached 16 kHz mono WAV to avoid repeated video decodes.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple, Optional
import numpy as np
from src.audio_cache import ensure_wav_cache, load_wav_segment

@dataclass
class ClipLike:
    path: str
    camera: str
    start_time: float
    duration: float

def _extract_audio_segment(video_path: str,
                           source_start: float,
                           duration: float,
                           sr: int,
                           bandpass: bool,
                           hp: int,
                           lp: int) -> np.ndarray:
    wav = ensure_wav_cache(video_path, sr=sr, bandpass=bandpass, hp=hp, lp=lp)
    if not wav:
        return np.array([], dtype=np.float32)
    return load_wav_segment(wav, source_start, duration, sr=sr)

def gcc_phat(sig: np.ndarray, refsig: np.ndarray, fs: int,
             max_tau: Optional[float] = None, interp: int = 16) -> float:
    sig = np.asarray(sig, dtype=np.float32).ravel()
    refsig = np.asarray(refsig, dtype=np.float32).ravel()
    n = sig.shape[0] + refsig.shape[0]
    if n <= 2:
        return 0.0
    SIG = np.fft.rfft(sig, n=n)
    REFSIG = np.fft.rfft(refsig, n=n)
    R = SIG * np.conj(REFSIG)
    denom = np.abs(R); denom[denom == 0] = 1e-12
    cc = np.fft.irfft(R / denom, n=(interp * n))
    max_shift = int(interp * n / 2)
    if max_tau is not None:
        max_shift = min(int(interp * fs * max_tau), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    shift = int(np.argmax(cc) - max_shift)
    return float(shift) / float(interp * fs)

def estimate_offsets_and_drift(camera_clips: Iterable[ClipLike],
                               ref_camera: str,
                               *,
                               sample_rate: int = 16000,
                               window_seconds: float = 12.0,
                               hop_seconds: float = 6.0,
                               bandpass: bool = True,
                               hp: int = 300,
                               lp: int = 3000,
                               max_shift_seconds: float = 1.0,
                               estimate_drift: bool = True) -> Tuple[Dict[str,float], Dict[str,float]]:
    """Return (offsets, drifts) dicts per camera relative to ref_camera."""
    clips = [c for c in camera_clips if c.camera != ref_camera]
    offsets: Dict[str,float] = {}
    drifts: Dict[str,float] = {}
    for clip in clips:
        # Determine overlap region (simplified: use min duration window from start)
        win = min(window_seconds, clip.duration)
        if win <= 0.25:
            offsets[clip.camera] = 0.0; drifts[clip.camera] = 0.0; continue
        ref = next((c for c in camera_clips if c.camera == ref_camera), None)
        if ref is None:
            offsets[clip.camera] = 0.0; drifts[clip.camera] = 0.0; continue

        # Extract overlapped segments
        x = _extract_audio_segment(clip.path, clip.start_time, win, sample_rate, bandpass, hp, lp)
        y = _extract_audio_segment(ref.path, ref.start_time, win, sample_rate, bandpass, hp, lp)
        if x.size == 0 or y.size == 0:
            offsets[clip.camera] = 0.0; drifts[clip.camera] = 0.0; continue

        # Multi-window GCC-PHAT
        step = max(0.5, hop_seconds)
        cursor = 0.0
        estimates: List[float] = []
        while cursor + step <= win:
            i0 = int(cursor * sample_rate)
            i1 = int(min(win, cursor + step) * sample_rate)
            delay = gcc_phat(x[i0:i1], y[i0:i1], sample_rate, max_tau=max_shift_seconds)
            estimates.append(delay)
            cursor += step * 0.5  # 50% overlap
        if not estimates:
            offsets[clip.camera] = 0.0; drifts[clip.camera] = 0.0; continue
        median_offset = float(np.median(np.asarray(estimates, dtype=np.float32)))
        offsets[clip.camera] = median_offset
        drifts[clip.camera] = 0.0  # keep simple; drift fitting optional
    return offsets, drifts
