cd /Users/andrew/zzApps/combine-blink
set -euo pipefail

# Safety: refuse to run with pending changes
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: You have uncommitted changes. Commit or stash first."; exit 1
fi

###############################################################################
# PR 1 — FFmpeg tooling: prefer VideoToolbox, add robust flags
###############################################################################
git checkout -B pr/as-ffmpeg-tooling

mkdir -p src
cat > src/video.py <<'PY'
import logging
import os
import subprocess
import tempfile
from typing import List
from src.media_utils import probe_media_info

def _hw_encode_enabled() -> bool:
    return os.environ.get("CB_USE_HW", "1") == "1"

def _hw_codec() -> str:
    # h264_videotoolbox | hevc_videotoolbox
    return os.environ.get("CB_HW_CODEC", "h264_videotoolbox")

def merge_video_clips(video_paths: List[str], output_path: str, crossfade_duration: float) -> bool:
    """Merge clips sequentially, delegating heavy lifting to ffmpeg for low RAM usage."""
    if not video_paths:
        logging.warning("No video paths provided for merging.")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if len(video_paths) == 1:
        return _copy_single_clip(video_paths[0], output_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        current_source = video_paths[0]
        for index, next_clip in enumerate(video_paths[1:], start=1):
            merge_target = os.path.join(tmpdir, f"merge_{index}.mp4")
            if crossfade_duration > 0:
                merged = _crossfade_pair(current_source, next_clip, merge_target, crossfade_duration)
            else:
                merged = _concat_pair(current_source, next_clip, merge_target)
            if not merged:
                return False
            current_source = merge_target
        os.replace(current_source, output_path)

    logging.info("Merged %d clips into %s", len(video_paths), output_path)
    return True

def _copy_single_clip(source: str, destination: str) -> bool:
    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
           "-hwaccel","videotoolbox","-hwaccel_output_format","videotoolbox",
           "-i", source]
    if _hw_encode_enabled():
        cmd += ["-c:v", _hw_codec(), "-realtime","true", "-c:a","aac", "-movflags","+faststart"]
    else:
        cmd += ["-c","copy"]
    cmd += [destination]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        logging.error("ffmpeg failed to duplicate %s", source)
        return False
    return True

def _crossfade_pair(first_clip: str, second_clip: str, output_path: str, duration: float) -> bool:
    fi = probe_media_info(first_clip)
    si = probe_media_info(second_clip)
    if (not fi.has_audio or not si.has_audio or fi.duration <= 0.0 or si.duration <= 0.0 or fi.duration <= duration):
        logging.debug("xfade fallback to concat for %s and %s", first_clip, second_clip)
        return _concat_pair(first_clip, second_clip, output_path)

    offset = max(fi.duration - duration, 0.0)
    filter_complex = (
        f"[0:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v0];"
        f"[1:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v1];"
        f"[0:a]asetpts=PTS-STARTPTS[a0];"
        f"[1:a]asetpts=PTS-STARTPTS[a1];"
        f"[v0][v1]xfade=transition=fade:duration={duration}:offset={offset}[vout];"
        f"[a0][a1]acrossfade=d={duration}[aout]"
    )
    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
           "-i", first_clip, "-i", second_clip,
           "-filter_complex", filter_complex,
           "-map","[vout]","-map","[aout]"]
    if _hw_encode_enabled():
        cmd += ["-c:v", _hw_codec(), "-realtime","true","-c:a","aac","-movflags","+faststart"]
    else:
        cmd += ["-c:v","libx264","-c:a","aac","-movflags","+faststart"]
    cmd += [output_path]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        logging.error("ffmpeg crossfade failed for %s and %s", first_clip, second_clip)
        return False
    return True

def _concat_pair(first_clip: str, second_clip: str, output_path: str) -> bool:
    """Re-encode concat via filtergraph for robustness across H.264 param mismatches."""
    fi = probe_media_info(first_clip)
    si = probe_media_info(second_clip)
    both_have_audio = bool(fi.has_audio and si.has_audio)

    if both_have_audio:
        filter_complex = (
            "[0:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v0];"
            "[1:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v1];"
            "[0:a]asetpts=PTS-STARTPTS[a0];"
            "[1:a]asetpts=PTS-STARTPTS[a1];"
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
        )
        cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
               "-i", first_clip, "-i", second_clip,
               "-filter_complex", filter_complex,
               "-map","[v]","-map","[a]"]
        if _hw_encode_enabled():
            cmd += ["-c:v", _hw_codec(), "-realtime","true","-c:a","aac","-movflags","+faststart", output_path]
        else:
            cmd += ["-c:v","libx264","-c:a","aac","-movflags","+faststart", output_path]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            logging.error("ffmpeg concat (filter) failed for %s and %s", first_clip, second_clip)
            return False
        return True

    # Video-only or mismatched audio: concat video, keep best-effort audio
    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
           "-i", first_clip, "-i", second_clip,
           "-filter_complex","[0:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v0];[1:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v1];[v0][v1]concat=n=2:v=1:a=0[v]",
           "-map","[v]"]
    if _hw_encode_enabled():
        cmd += ["-c:v", _hw_codec(), "-realtime","true","-movflags","+faststart"]
    else:
        cmd += ["-c:v","libx264","-movflags","+faststart"]
    cmd += [output_path]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        logging.error("ffmpeg concat (video-only) failed for %s and %s", first_clip, second_clip)
        return False
    return True
PY

git add src/video.py
git commit -m "FFmpeg: prefer VideoToolbox on Apple Silicon; add -nostdin/-hide_banner; safe x264 fallback"

###############################################################################
# PR 2 — Audio cache module + use in alignment (no repeated video decodes)
###############################################################################
git checkout -B pr/as-audio-cache

mkdir -p src

cat > src/audio_cache.py <<'PY'
import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional
import numpy as np

def _cache_wav_path(video_path: str, sr: int, base_dir: Optional[str]) -> Path:
    h8 = hashlib.md5(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
    out_dir = Path(base_dir or os.path.join("output","audio_cache"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    return out_dir / f"{stem}_{h8}_{sr}Hz_mono.wav"

def ensure_wav_cache(video_path: str, sr: int = 16000,
                     bandpass: bool = False, hp: int = 0, lp: int = 0,
                     base_dir: Optional[str] = None) -> Optional[str]:
    wav = _cache_wav_path(video_path, sr, base_dir)
    if wav.exists():
        return str(wav)
    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error",
           "-i", video_path, "-vn", "-ac","1","-ar",str(sr)]
    af = []
    if bandpass:
        if hp and hp>0: af += [f"highpass=f={hp}"]
        if lp and lp>0: af += [f"lowpass=f={lp}"]
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
PY

# Replace extractor in av_alignment to use cache
cat > src/av_alignment.py <<'PY'
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
PY

git add src/audio_cache.py src/av_alignment.py
git commit -m "Alignment: add audio cache + slice from cached 16k mono WAV; avoid repeated video decode"

###############################################################################
# PR 3 — People detector on MPS with inference_mode + non-blocking moves
###############################################################################
git checkout -B pr/as-mps-people

cat > src/people_detection.py <<'PY'
"""
People detection utilities using Hugging Face Transformers (no OpenCV).
Optimized for Apple Silicon: use MPS when available.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any
import threading
from PIL import Image

try:
    import torch  # type: ignore
    from transformers import AutoImageProcessor, AutoModelForObjectDetection  # type: ignore
except Exception:  # pragma: no cover
    torch = None  # type: ignore
    AutoImageProcessor = None  # type: ignore
    AutoModelForObjectDetection = None  # type: ignore

@dataclass
class PeopleDetectorConfig:
    model_name: str = "hustvl/yolos-tiny"
    revision: Optional[str] = None
    score_threshold: float = 0.7

class PeopleDetector:
    """Counts people in images using a Hugging Face object detection model."""
    def __init__(self, config: Optional[PeopleDetectorConfig] = None) -> None:
        self.config = config or PeopleDetectorConfig()
        self._processor: Any = None
        self._model: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        if AutoImageProcessor is None or AutoModelForObjectDetection is None or torch is None:
            raise RuntimeError("Hugging Face transformers + torch are required for PeopleDetector")
        with self._lock:
            if self._model is not None and self._processor is not None:
                return
            kwargs = {}
            if self.config.revision:
                kwargs["revision"] = self.config.revision
            self._processor = AutoImageProcessor.from_pretrained(self.config.model_name, **kwargs)
            self._model = AutoModelForObjectDetection.from_pretrained(self.config.model_name, **kwargs)
            self._model.eval()
            # Prefer MPS on Apple Silicon
            try:
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self._model.to("mps")  # type: ignore[arg-type]
                    if hasattr(torch, "set_float32_matmul_precision"):
                        torch.set_float32_matmul_precision("high")
            except Exception:
                pass

    def count_people(self, image: Image.Image) -> int:
        """Return number of detected people (COCO class 'person') in the given image."""
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None

        inputs = self._processor(images=image, return_tensors="pt")
        # Move tensors to model device
        model_device = next(self._model.parameters()).device  # type: ignore[attr-defined]
        for k in list(inputs.keys()):
            try:
                inputs[k] = inputs[k].to(model_device, non_blocking=True)  # type: ignore[assignment]
            except Exception:
                pass

        with torch.inference_mode():  # type: ignore[attr-defined]
            outputs = self._model(**inputs)  # type: ignore[call-arg]

        try:
            import torch as _torch
            target_sizes = _torch.tensor([image.size[::-1]], device=model_device)
        except Exception:
            target_sizes = None

        results = self._processor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=float(self.config.score_threshold)
        )[0]

        id2label = self._model.config.id2label
        count = 0
        for label_id in results.get("labels", []):
            try:
                if id2label[int(label_id)] == "person":
                    count += 1
            except Exception:
                continue
        return count
PY

git add src/people_detection.py
git commit -m "People detection: use MPS, inference_mode, non-blocking device moves on Apple Silicon"

###############################################################################
# Done — show branches
###############################################################################
git branch --list
echo "Branches ready. Push with:  git push -u origin pr/as-ffmpeg-tooling pr/as-audio-cache pr/as-mps-people"
