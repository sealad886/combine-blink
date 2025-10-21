import logging
import os
import subprocess
import tempfile
from typing import List

from src.media_utils import probe_media_info


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
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        source,
        "-c",
        "copy",
        destination,
    ]
    result = subprocess.run(command)
    if result.returncode != 0:
        logging.error("ffmpeg failed to duplicate %s", source)
        return False
    return True


def _crossfade_pair(first_clip: str, second_clip: str, output_path: str, duration: float) -> bool:
    first_info = probe_media_info(first_clip)
    second_info = probe_media_info(second_clip)

    if (
        not first_info.has_audio
        or not second_info.has_audio
        or first_info.duration <= 0.0
        or second_info.duration <= 0.0
        or first_info.duration <= duration
    ):
        logging.debug(
            "Falling back to concat for %s and %s due to missing audio metadata or short clips.",
            first_clip,
            second_clip,
        )
        return _concat_pair(first_clip, second_clip, output_path)

    offset = max(first_info.duration - duration, 0.0)
    filter_complex = (
        f"[0:v]setpts=PTS-STARTPTS[v0];"
        f"[1:v]setpts=PTS-STARTPTS[v1];"
        f"[0:a]asetpts=PTS-STARTPTS[a0];"
        f"[1:a]asetpts=PTS-STARTPTS[a1];"
        f"[v0][v1]xfade=transition=fade:duration={duration}:offset={offset}[vout];"
        f"[a0][a1]acrossfade=d={duration}[aout]"
    )

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
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
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = subprocess.run(command)
    if result.returncode != 0:
        logging.error("ffmpeg crossfade failed for %s and %s", first_clip, second_clip)
        return False
    return True


def _concat_pair(first_clip: str, second_clip: str, output_path: str) -> bool:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as concat_file:
        concat_file.write(f"file '{os.path.abspath(first_clip)}'\n")
        concat_file.write(f"file '{os.path.abspath(second_clip)}'\n")
        list_path = concat_file.name

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path,
        "-c",
        "copy",
        output_path,
    ]

    result = subprocess.run(command)
    os.remove(list_path)

    if result.returncode != 0:
        logging.error("ffmpeg concat failed for %s and %s", first_clip, second_clip)
        return False

    return True
