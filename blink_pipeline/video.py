import logging
import os
import subprocess
import tempfile

from blink_pipeline.media_utils import probe_media_info


def _hw_encode_enabled() -> bool:
    return os.environ.get("CB_USE_HW", "1") == "1"

def _hw_codec() -> str:
    # h264_videotoolbox | hevc_videotoolbox
    return os.environ.get("CB_HW_CODEC", "h264_videotoolbox")

def merge_video_clips(video_paths: list[str], output_path: str, crossfade_duration: float) -> bool:
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
    # Prefer hardware-assisted remux/encode path if available and configured
    use_hw = os.environ.get("CB_USE_HW", "1") == "1"
    hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")
    command = [
        "ffmpeg",
        "-y",
        "-nostdin", "-hide_banner", "-loglevel", "error",
        "-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox",
        "-i",
        source,
    ]
    if use_hw:
        command += ["-c:v", hw_codec, "-realtime", "true", "-c:a", "aac", "-movflags", "+faststart"]
    else:
        command += ["-c", "copy"]
    command += [
        destination,
    ]
    result = subprocess.run(command)
    if result.returncode != 0:
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
        f"[0:v]setpts=PTS-STARTPTS[v0];"
        f"[1:v]setpts=PTS-STARTPTS[v1];"
        f"[0:a]asetpts=PTS-STARTPTS[a0];"
        f"[1:a]asetpts=PTS-STARTPTS[a1];"
        f"[v0][v1]xfade=transition=fade:duration={duration}:offset={offset}[vout];"
        f"[a0][a1]acrossfade=d={duration}[aout]"
    )

    use_hw = os.environ.get("CB_USE_HW", "1") == "1"
    hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")
    command = [
        "ffmpeg",
        "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
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
    ]
    if use_hw:
        command += ["-c:v", hw_codec, "-realtime", "true", "-c:a", "aac", "-movflags", "+faststart"]
    else:
        command += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]
    command += [
        output_path,
    ]

    result = subprocess.run(command)
    if result.returncode != 0:
        logging.error("ffmpeg crossfade failed for %s and %s", first_clip, second_clip)
        return False
    return True

def _concat_pair(first_clip: str, second_clip: str, output_path: str) -> bool:
    """Re-encode concat via filtergraph for robustness across H.264 param mismatches."""
    fi = probe_media_info(first_clip)
    si = probe_media_info(second_clip)
    both_have_audio = bool(fi.has_audio and si.has_audio)

    use_hw = os.environ.get("CB_USE_HW", "1") == "1"
    hw_codec = os.environ.get("CB_HW_CODEC", "h264_videotoolbox")

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
        if use_hw:
            cmd += ["-c:v", hw_codec, "-realtime","true","-c:a","aac","-movflags","+faststart", output_path]
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
    if use_hw:
        cmd += ["-c:v", hw_codec, "-realtime","true","-movflags","+faststart"]
    else:
        cmd += ["-c:v","libx264","-movflags","+faststart"]
    cmd += [output_path]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        logging.error("ffmpeg concat (video-only) failed for %s and %s", first_clip, second_clip)
        return False
    return True
