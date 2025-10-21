"""
Robust audio alignment utilities for multi-camera composition.

This module implements a multi-window GCC-PHAT based time delay estimation
to robustly estimate per-camera offsets (and optional drift) relative to
the chosen reference camera.

Design goals:
- Use multiple overlapping windows across the overlapping regions to avoid
  brittle single-window estimates.
- Aggregate per-window offsets robustly (median) and optionally fit a
  linear drift model offset(t) = a + b * t.
- Keep dependencies minimal (numpy + ffmpeg for extraction).

Inputs/Outputs contract:
- Inputs: list of CameraClip-like dicts or dataclasses with fields
  (path, camera, start_time, duration), reference camera name, and config.
- Output: two dicts: offsets[camera] = seconds, drifts[camera] = seconds/second.

Note: This module does not modify files; it only computes alignment metadata.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple, Optional
import numpy as np


@dataclass
class ClipLike:
    path: str
    camera: str
    start_time: float
    duration: float


def _extract_audio_segment(
    video_path: str,
    source_start: float,
    duration: float,
    sr: int,
    bandpass: bool,
    hp: int,
    lp: int,
) -> np.ndarray:
    """Extract a mono PCM audio segment as float32 numpy array in [-1, 1].

    Uses ffmpeg for robust media decode without inflating memory usage.
    Returns empty array on failure.
    """
    filter_chain: List[str] = []
    if bandpass:
        if hp and hp > 0:
            filter_chain.append(f"highpass=f={hp}")
        if lp and lp > 0:
            filter_chain.append(f"lowpass=f={lp}")
    af = ",".join(filter_chain) if filter_chain else None

    cmd: List[str] = [
        "ffmpeg",
        "-ss",
        f"{max(0.0, source_start):.3f}",
        "-t",
        f"{max(0.0, duration):.3f}",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
    ]
    if af:
        cmd.extend(["-af", af])
    cmd.append("pipe:1")

    try:
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not proc.stdout:
            return np.array([], dtype=np.float32)
        data = np.frombuffer(proc.stdout, dtype=np.int16)
        if data.size == 0:
            return np.array([], dtype=np.float32)
        return (data.astype(np.float32) / 32768.0).copy()
    except Exception:
        return np.array([], dtype=np.float32)


def gcc_phat(
    sig: np.ndarray,
    refsig: np.ndarray,
    fs: int,
    max_tau: Optional[float] = None,
    interp: int = 16,
) -> float:
    """Estimate time delay using GCC-PHAT.

    Returns the estimated delay in seconds where positive means sig lags refsig.

    Implementation based on standard GCC-PHAT:
    - Compute cross-power spectrum SIG * conj(REFSIG)
    - Normalize by magnitude (PHAT weighting)
    - Inverse FFT to obtain correlation function
    - Take the argmax within a bounded lag window
    """
    # Ensure 1-D arrays
    sig = np.asarray(sig, dtype=np.float32).ravel()
    refsig = np.asarray(refsig, dtype=np.float32).ravel()
    n = sig.shape[0] + refsig.shape[0]
    if n <= 2:
        return 0.0

    SIG = np.fft.rfft(sig, n=n)
    REFSIG = np.fft.rfft(refsig, n=n)
    R = SIG * np.conj(REFSIG)
    denom = np.abs(R)
    # Avoid division by zero
    denom[denom == 0] = 1e-12
    cc = np.fft.irfft(R / denom, n=(interp * n))
    max_shift = int(interp * n / 2)
    if max_tau is not None:
        max_shift = min(int(interp * fs * max_tau), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    shift = int(np.argmax(cc) - max_shift)
    tau = shift / float(interp * fs)
    return float(tau)


def estimate_offsets_and_drift(
    camera_clips: Iterable[ClipLike],
    ref_camera: str,
    *,
    sample_rate: int = 16000,
    window_seconds: float = 12.0,
    hop_seconds: Optional[float] = None,
    max_shift_seconds: float = 1.0,
    bandpass: bool = True,
    hp: int = 300,
    lp: int = 3000,
    min_windows: int = 2,
    estimate_drift: bool = True,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Estimate per-camera alignment offsets and optional linear drift.

    Strategy:
    - For each non-reference camera, find overlapping intervals with the reference
      camera across the event timeline.
    - Slide windows of size window_seconds with hop_seconds (default: window/2)
      across the overlap.
    - For each window, extract audio and compute GCC-PHAT delay.
    - Aggregate window delays with median (robust) to get base offset.
    - Optionally fit linear regression offset(t) = a + b * t to estimate drift.

    Returns:
        (offsets, drifts) where drifts are seconds per second.
    """
    clips = list(camera_clips)
    if not clips:
        return {}, {}

    hop_seconds = float(hop_seconds) if hop_seconds else window_seconds / 2.0
    # Group clips by camera
    by_cam: Dict[str, List[ClipLike]] = {}
    for c in clips:
        by_cam.setdefault(c.camera, []).append(c)
    for cam in by_cam:
        by_cam[cam].sort(key=lambda x: x.start_time)

    if ref_camera not in by_cam:
        # Choose the earliest starting camera as fallback
        ref_camera = sorted(by_cam.keys())[0]
    ref_clips = by_cam[ref_camera]

    # Build event boundaries from all clips to estimate rough timeline
    event_start = min(c.start_time for c in clips)
    event_end = max(c.start_time + c.duration for c in clips)
    event_duration = max(0.0, event_end - event_start)
    if event_duration <= 0:
        return {}, {}

    offsets: Dict[str, float] = {ref_camera: 0.0}
    drifts: Dict[str, float] = {ref_camera: 0.0}

    # Helper: find overlap between camera cam and reference across all clip pairs
    def _overlaps_with_ref(cam: str) -> List[Tuple[float, float, ClipLike, ClipLike]]:
        res: List[Tuple[float, float, ClipLike, ClipLike]] = []
        cam_clips = by_cam.get(cam, [])
        for rc in ref_clips:
            r0, r1 = rc.start_time, rc.start_time + rc.duration
            for cc in cam_clips:
                c0, c1 = cc.start_time, cc.start_time + cc.duration
                o0 = max(r0, c0)
                o1 = min(r1, c1)
                if o1 - o0 > 0.5:  # at least some overlap
                    res.append((o0, o1, rc, cc))
        return res

    for cam, cam_list in by_cam.items():
        if cam == ref_camera:
            continue

        overlaps = _overlaps_with_ref(cam)
        if not overlaps:
            offsets[cam] = 0.0
            drifts[cam] = 0.0
            continue

        times: List[float] = []
        delays: List[float] = []

        for o0, o1, rc, cc in overlaps:
            ov_dur = o1 - o0
            if ov_dur <= 0.2:
                continue
            w = min(window_seconds, ov_dur)
            if w <= 0.2:
                continue
            hop = max(0.1, min(hop_seconds, w))
            # slide windows
            t = o0
            safety = 0
            while t + w <= o1 + 1e-6 and safety < 10000:
                safety += 1
                # position within each clip
                ref_src = max(0.0, t - rc.start_time)
                cam_src = max(0.0, t - cc.start_time)
                ref_samples = _extract_audio_segment(rc.path, ref_src, w, sample_rate, bandpass, hp, lp)
                cam_samples = _extract_audio_segment(cc.path, cam_src, w, sample_rate, bandpass, hp, lp)
                if ref_samples.size == 0 or cam_samples.size == 0:
                    t += hop
                    continue
                # normalize for robustness
                ref_samples = ref_samples - float(np.mean(ref_samples))
                cam_samples = cam_samples - float(np.mean(cam_samples))
                ref_norm = float(np.linalg.norm(ref_samples)) or 1.0
                cam_norm = float(np.linalg.norm(cam_samples)) or 1.0
                ref_samples /= ref_norm
                cam_samples /= cam_norm
                delay = gcc_phat(cam_samples, ref_samples, fs=sample_rate, max_tau=max_shift_seconds)
                # bound
                delay = max(-max_shift_seconds, min(max_shift_seconds, delay))
                times.append(t - event_start)  # relative to event start
                delays.append(delay)
                t += hop

        if len(delays) < max(min_windows, 1):
            offsets[cam] = 0.0
            drifts[cam] = 0.0
            continue

        # robust center via median
        base = float(np.median(np.asarray(delays)))
        offsets[cam] = base

        if estimate_drift and len(delays) >= max(min_windows, 3):
            # Fit linear model y = a + b*x via least squares
            x = np.asarray(times, dtype=np.float64)
            y = np.asarray(delays, dtype=np.float64)
            # Center x for numerical stability
            x0 = x - np.mean(x)
            A = np.vstack([np.ones_like(x0), x0]).T
            sol, *_ = np.linalg.lstsq(A, y, rcond=None)
            a = float(sol[0])
            b = float(sol[1])
            # Our base was median; reconcile by using a as refinement
            offsets[cam] = float(a + np.median(x0) * b)
            # Bound drift to reasonable small values (e.g., <= 1ms per second)
            b = max(-1e-3, min(1e-3, b))
            drifts[cam] = b
        else:
            drifts[cam] = 0.0

    return offsets, drifts
