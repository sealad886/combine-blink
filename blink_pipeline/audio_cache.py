import hashlib
import logging
import os
import subprocess
from pathlib import Path

import numpy as np


def _cache_wav_path(video_path: str, sr: int, base_dir: str | None) -> Path:
    """Generate cache path for audio extraction.

    Uses BLAKE2s (8 hex) hash of absolute path for collision resistance.
    """
    abs_src = os.path.abspath(video_path)
    # 4-byte BLAKE2s -> 8 hex chars, good balance of brevity vs collisions
    h8 = hashlib.blake2s(abs_src.encode("utf-8"), digest_size=4).hexdigest()
    out_dir = Path(base_dir or os.path.join("output","audio_cache"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    return out_dir / f"{stem}_{h8}_{sr}Hz_mono.wav"

def ensure_wav_cache(video_path: str, sr: int = 16000,
                     bandpass: bool = False, hp: int = 0, lp: int = 0,
                     base_dir: str | None = None) -> str | None:
    wav = _cache_wav_path(video_path, sr, base_dir)
    if wav.exists():
        return str(wav)
    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
           "-i", video_path, "-vn", "-ac","1","-ar",str(sr)]
    af = []
    if bandpass:
        if hp and hp > 0:
            af += [f"highpass=f={hp}"]
        if lp and lp > 0:
            af += [f"lowpass=f={lp}"]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-f","wav", str(wav)]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        logging.error("ffmpeg failed extracting WAV for %s", video_path)
        return None
    return str(wav)

def load_wav_segment(wav_path: str, start_s: float, dur_s: float, sr: int = 16000) -> np.ndarray:
    cmd = ["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
           "-ss", f"{max(0.0,start_s):.3f}", "-t", f"{max(0.0,dur_s):.3f}",
           "-i", wav_path, "-ac","1","-ar",str(sr),
           "-f","s16le","-acodec","pcm_s16le","pipe:1"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return np.array([], dtype=np.float32)
    data = np.frombuffer(r.stdout, dtype=np.int16)
    if data.size == 0:
        return np.array([], dtype=np.float32)
    return (data.astype(np.float32) / 32768.0).copy()
