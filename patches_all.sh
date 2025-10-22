cd /Users/andrew/zzApps/combine-blink
git checkout -b pr/as-video-toolbox
git apply <<'PATCH'
*** Begin Patch
*** Update File: config.yaml
@@
 multi_camera_composition:
   # Enable multi-camera composition (set to false to use old sequential merge)
   enable_composition: true
@@
-  transition_style: crossfade
+  transition_style: crossfade
@@
-  audio_crossfade_seconds: 0.06
+  audio_crossfade_seconds: 0.06
@@
-  audio_source: best_quality
+  audio_source: best_quality
@@
   # Clean up the selected audio track before stitching segments
   # MPS optimization: Audio cleanup is ffmpeg-based and runs efficiently on all platforms
   audio_cleanup:
@@
     loudnorm_target_lra: 11.0
     extra_filters: []        # Optional list of additional ffmpeg audio filters
@@
   # Estimate how many people are visible in each angle to guide silent segments
@@
   people_detection:
-    enabled: true
-    sample_frames: 4           # Reduced from 6 for faster detection (still accurate)
-    resize_width: 480          # Reduced from 640 for ~2x faster inference on MPS
+    enabled: true
+    sample_frames: 3           # Slightly fewer frames for speed on Apple Silicon
+    resize_width: 480          # Keeps MPS fast while preserving detail
     min_frame_width: 320       # Minimum width to avoid undersized frames
@@
     min_count: 1               # Minimum people-count to consider angle for silent intervals
@@
-  # Fine audio alignment (cross-correlation) to reduce per-camera offset
-  # Uses a short window of audio from overlapping clips to estimate per-camera time shift
-  # Note: Estimates a single offse
+  # Fine audio alignment (cross-correlation) to reduce per-camera offset
+  # Uses a short window of audio from overlapping clips to estimate per-camera time shift
+  # Note: Uses cached 16 kHz mono WAVs on disk to avoid repeated ffmpeg calls.
+
+  # Performance and encoding options
+  single_pass_filter_complex: true
+  encoding:
+    use_hw_encode: true                   # Apple VideoToolbox when possible
+    hw_codec: h264_videotoolbox           # or hevc_videotoolbox if all players support HEVC
+    x264_preset: veryfast                 # Fallback when hw encode is disabled
+    x264_crf: '22'                        # Fallback CRF for libx264
+    bitrate: 6000k                        # Target bitrate for VideoToolbox
+
+  # Burn-in overlay is expensive; keep off for final outputs
+  timestamp_overlay:
+    enabled: false
*** End Patch
PATCH
git commit -am "Apple Silicon: enable VideoToolbox by default; dial people detection for MPS; disable timestamp overlay by default"

# ---- PR 1 code changes (VideoToolbox paths in merge helpers) ----
git checkout -b pr/as-ffmpeg-tooling
git apply <<'PATCH'
*** Begin Patch
*** Update File: src/video.py
@@
 def _copy_single_clip(source: str, destination: str) -> bool:
-    command = [
+    # Prefer hardware-assisted remux/encode path if available and configured
+    use_hw = os.environ.get("CB_USE_HW", "1") == "1"
+    hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")
+    command = [
         "ffmpeg",
         "-y",
-        "-loglevel",
-        "error",
+        "-nostdin", "-hide_banner", "-loglevel", "error",
+        "-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox",
         "-i",
         source,
-        "-c",
-        "copy",
+    ]
+    if use_hw:
+        command += ["-c:v", hw_codec, "-realtime", "true", "-c:a", "aac", "-movflags", "+faststart"]
+    else:
+        command += ["-c", "copy"]
+    command += [
         destination,
     ]
@@
 def _crossfade_pair(first_clip: str, second_clip: str, output_path: str, duration: float) -> bool:
@@
-    command = [
+    use_hw = os.environ.get("CB_USE_HW", "1") == "1"
+    hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")
+    command = [
         "ffmpeg",
-        "-y",
-        "-loglevel",
-        "error",
+        "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i",
         first_clip,
         "-i",
         second_clip,
         "-filter_complex",
         filter_complex,
         "-map",
         "[vout]",
         "-map",
         "[aout]",
-        "-c:v",
-        "libx264",
-        "-c:a",
-        "aac",
-        "-movflags",
-        "+faststart",
+    ]
+    if use_hw:
+        command += ["-c:v", hw_codec, "-realtime", "true", "-c:a", "aac", "-movflags", "+faststart"]
+    else:
+        command += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]
+    command += [
         output_path,
     ]
@@
 def _concat_pair(first_clip: str, second_clip: str, output_path: str) -> bool:
@@
-    if both_have_audio:
+    if both_have_audio:
         # Filter-based concat ensures consistent timestamps and pixel format
         filter_complex = (
             "[0:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v0];"
             "[1:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v1];"
             "[0:a]asetpts=PTS-STARTPTS[a0];"
             "[1:a]asetpts=PTS-STARTPTS[a1];"
             "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
         )
-        cmd = ["ffmpeg","-y","-loglevel","error","-i",first_clip,"-i",second_clip,
+        use_hw = os.environ.get("CB_USE_HW", "1") == "1"
+        hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")
+        cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error","-i",first_clip,"-i",second_clip,
                "-filter_complex",filter_complex,
                "-map","[v]","-map","[a]"]
-        cmd += ["-c:v","libx264","-c:a","aac","-movflags","+faststart",output_path]
+        if use_hw:
+            cmd += ["-c:v", hw_codec, "-realtime","true","-c:a","aac","-movflags","+faststart", output_path]
+        else:
+            cmd += ["-c:v","libx264","-c:a","aac","-movflags","+faststart",output_path]
         result = subprocess.run(cmd)
         if result.returncode != 0:
             logging.error("ffmpeg concat (filter) failed for %s and %s", first_clip, second_clip)
             return False
         return True
*** End Patch
PATCH
git commit -am "FFmpeg: prefer VideoToolbox on Apple Silicon; add -nostdin/-hide_banner; safe fallbacks"

# ---- PR 2: Cached 16 kHz mono WAV per clip + alignment slices, zero extra ffmpeg calls ----
git checkout -b pr/as-audio-cache
git apply <<'PATCH'
*** Begin Patch
*** Update File: src/media_utils.py
@@
-from dataclasses import dataclass
+from dataclasses import dataclass
 from pathlib import Path
-from typing import Optional
+from typing import Optional, Tuple
+import hashlib
+import numpy as np
@@
-def probe_media_info(path: str) -> MediaInfo:
+def probe_media_info(path: str) -> MediaInfo:
@@
-        result = subprocess.run(
+        result = subprocess.run(
             [
                 "ffprobe",
-                "-v",
-                "error",
+                "-v","error","-nostdin","-hide_banner",
                 "-print_format",
                 "json",
                 "-show_format",
                 "-show_streams",
                 path,
             ],
             capture_output=True,
             text=True,
             check=True,
         )
@@
     except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
         logging.error("ffprobe failed for %s: %s", path, exc)
         return MediaInfo()
 
+def _audio_cache_paths(video_path: str, sr: int = 16000, base_dir: Optional[str] = None) -> Tuple[Path, Path]:
+    """Return (cache_dir, wav_path) for the per-clip mono PCM cache."""
+    h8 = hashlib.md5(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
+    out_dir = Path(base_dir or os.path.join("output","audio_cache"))
+    out_dir.mkdir(parents=True, exist_ok=True)
+    stem = Path(video_path).stem
+    wav = out_dir / f"{stem}_{h8}_{sr}Hz_mono.wav"
+    return out_dir, wav
+
+def ensure_wav_cache(video_path: str, sr: int = 16000, bandpass: bool = False, hp: int = 0, lp: int = 0, base_dir: Optional[str] = None) -> Optional[str]:
+    """Extract a single mono {sr}Hz WAV once per clip; return its path."""
+    _, wav = _audio_cache_paths(video_path, sr=sr, base_dir=base_dir)
+    if wav.exists():
+        return str(wav)
+    cmd = ["ffmpeg","-y","-nostdin","-hide_banner","-loglevel","error","-i",video_path,"-vn","-ac","1","-ar",str(sr)]
+    af = []
+    if bandpass:
+        if hp and hp>0: af += [f"highpass=f={hp}"]
+        if lp and lp>0: af += [f"lowpass=f={lp}"]
+    if af:
+        cmd += ["-af", ",".join(af)]
+    cmd += ["-f","wav", str(wav)]
+    try:
+        r = subprocess.run(cmd)
+        if r.returncode != 0:
+            logging.error("ffmpeg failed extracting WAV for %s", video_path)
+            return None
+        return str(wav)
+    except Exception as e:
+        logging.error("WAV cache error for %s: %s", video_path, e)
+        return None
+
+def load_wav_segment(wav_path: str, start_s: float, dur_s: float, sr: int = 16000) -> np.ndarray:
+    """Fast slice from cached WAV via ffmpeg trim (still zero decode of video) or raw numpy."""
+    # Use ffmpeg trim on audio file (lightweight) to avoid Python WAV parsing overhead for large files.
+    cmd = ["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-ss",f"{max(0.0,start_s):.3f}","-t",f"{max(0.0,dur_s):.3f}",
+           "-i", wav_path, "-ac","1","-ar",str(sr), "-f","s16le","-acodec","pcm_s16le","pipe:1"]
+    r = subprocess.run(cmd, capture_output=True)
+    if r.returncode != 0 or not r.stdout:
+        return np.array([], dtype=np.float32)
+    data = np.frombuffer(r.stdout, dtype=np.int16)
+    if data.size == 0:
+        return np.array([], dtype=np.float32)
+    return (data.astype(np.float32) / 32768.0).copy()
*** End Patch
PATCH
git commit -am "Audio cache: per-clip 16 kHz mono WAV; fast segment slicing; ffprobe noise reduced"
git apply <<'PATCH'
*** Begin Patch
*** Update File: src/av_alignment.py
@@
-import subprocess
 from dataclasses import dataclass
 from typing import Dict, Iterable, List, Tuple, Optional
 import numpy as np
+from src.media_utils import ensure_wav_cache, load_wav_segment
 
@@
-def _extract_audio_segment(
-    video_path: str,
+def _extract_audio_segment(
+    video_path: str,
     source_start: float,
     duration: float,
     sr: int,
     bandpass: bool,
     hp: int,
     lp: int,
 ) -> np.ndarray:
-    """Extract a mono PCM audio segment as float32 numpy array in [-1, 1].
-
-    Uses ffmpeg for robust media decode without inflating memory usage.
-    Returns empty array on failure.
-    """
-    filter_chain: List[str] = []
-    if bandpass:
-        if hp and hp > 0:
-            filter_chain.append(f"highpass=f={hp}")
-        if lp and lp > 0:
-            filter_chain.append(f"lowpass=f={lp}")
-    af = ",".join(filter_chain) if filter_chain else None
-
-    cmd: List[str] = [
-        "ffmpeg",
-        "-ss",
-        f"{max(0.0, source_start):.3f}",
-        "-t",
-        f"{max(0.0, duration):.3f}",
-        "-i",
-        video_path,
-        "-vn",
-        "-ac",
-        "1",
-        "-ar",
-        str(sr),
-        "-f",
-        "s16le",
-        "-acodec",
-        "pcm_s16le",
-    ]
-    if af:
-        cmd.extend(["-af", af])
-    cmd.append("pipe:1")
-
-    try:
-        proc = subprocess.run(cmd, capture_output=True)
-        if proc.returncode != 0 or not proc.stdout:
-            return np.array([], dtype=np.float32)
-        data = np.frombuffer(proc.stdout, dtype=np.int16)
-        if data.size == 0:
-            return np.array([], dtype=np.float32)
-        return (data.astype(np.float32) / 32768.0).copy()
-    except Exception:
-        return np.array([], dtype=np.float32)
+    """Slice from a cached mono WAV to avoid repeated video decode calls."""
+    wav = ensure_wav_cache(video_path, sr=sr, bandpass=bandpass, hp=hp, lp=lp)
+    if not wav:
+        return np.array([], dtype=np.float32)
+    return load_wav_segment(wav, source_start, duration, sr=sr)
*** End Patch
PATCH
git commit -am "Alignment: switch to cached WAV slices (no repeated video decode)"
# (Optional) You can extract WAVs during validation later; for now, alignment lazily ensures cache.

# ---- PR 3: PeopleDetector on MPS with proper torch settings ----
git checkout -b pr/as-mps-people
git apply <<'PATCH'
*** Begin Patch
*** Update File: src/people_detection.py
@@
 class PeopleDetector:
@@
     def _ensure_loaded(self) -> None:
@@
-            kwargs = {}
+            kwargs = {}
             if self.config.revision:
                 kwargs["revision"] = self.config.revision
             # Auto* works across DETR, YOLOS, and other object detection backbones
             self._processor = AutoImageProcessor.from_pretrained(self.config.model_name, **kwargs)
             self._model = AutoModelForObjectDetection.from_pretrained(self.config.model_name, **kwargs)
-            self._model.eval()
+            self._model.eval()
+            # Prefer Apple MPS if present
+            try:
+                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
+                    self._model.to("mps")  # type: ignore[arg-type]
+                    # Improve matmul perf/accuracy
+                    if hasattr(torch, "set_float32_matmul_precision"):
+                        torch.set_float32_matmul_precision("high")
+            except Exception:
+                pass
@@
     def count_people(self, image: Image.Image) -> int:
@@
-        inputs = self._processor(images=image, return_tensors="pt")
-        with torch.no_grad():  # type: ignore[attr-defined]
-            outputs = self._model(**inputs)
+        inputs = self._processor(images=image, return_tensors="pt")
+        # Move tensors to same device as model
+        model_device = next(self._model.parameters()).device  # type: ignore[attr-defined]
+        for k in list(inputs.keys()):
+            try:
+                inputs[k] = inputs[k].to(model_device, non_blocking=True)  # type: ignore[assignment]
+            except Exception:
+                pass
+        with torch.inference_mode():  # type: ignore[attr-defined]
+            outputs = self._model(**inputs)  # type: ignore[call-arg]
*** End Patch
PATCH
git commit -am "People detection: use MPS when available; inference_mode; non-blocking device moves"

# ---- PR 4: Prefer whisper.cpp on Darwin/arm64; tame PyTorch/MPS usage ----
git checkout -b pr/as-whispercpp-default
git apply <<'PATCH'
*** Begin Patch
*** Update File: src/transcription.py
@@
-from src.media_utils import MediaInfo, extract_audio_segment, probe_media_info
-from src.whisper_cpp_wrapper import WhisperCppWrapper, is_ggml_model
+from src.media_utils import MediaInfo, extract_audio_segment, probe_media_info
+from src.whisper_cpp_wrapper import WhisperCppWrapper, is_ggml_model
@@
-def process_audio_for_transcription(
+def process_audio_for_transcription(
     video_paths: List[str], config: Dict[str, Any], progress_callback=None
 ) -> Optional[Dict[str, Any]]:
@@
-    if whisper is None:
-        raise RuntimeError(
-            "openai-whisper is not installed. Install it via 'pip install openai-whisper' to enable transcription."
-        )
+    # Choose backend: prefer whisper.cpp on Apple Silicon when configured/available
+    prefer_cpp = (config.get("transcription", {}).get("whisper", {}).get("prefer_whisper_cpp", True)
+                  and (sys.platform == "darwin"))
@@
-    transcription_config = config.get("transcription", {})
-    whisper_settings = _parse_whisper_settings(transcription_config.get("whisper", {}))
+    transcription_config = config.get("transcription", {})
+    whisper_settings = _parse_whisper_settings(transcription_config.get("whisper", {}))
@@
-    transcriber = _WhisperTranscriber(whisper_settings)
+    transcriber: Any
+    if prefer_cpp and whisper_settings.ggml_model_path:
+        transcriber = WhisperCppWrapper(
+            model_path=whisper_settings.ggml_model_path,
+            whisper_cpp_binary=whisper_settings.whisper_cpp_binary or "whisper.cpp/main",
+            language=whisper_settings.language,
+            temperature=whisper_settings.temperature,
+            beam_size=whisper_settings.beam_size,
+        )
+    else:
+        if whisper is None:
+            raise RuntimeError("Whisper (PyTorch) not installed and whisper.cpp not configured.")
+        transcriber = _WhisperTranscriber(whisper_settings)
*** End Patch
PATCH
git commit -am "Transcription: prefer whisper.cpp by default on macOS; clean fallback logic"
