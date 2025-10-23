import hashlib
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MediaInfo:
    """Lightweight container for basic media metadata."""

    duration: float = 0.0
    has_audio: bool = False
    video_duration: float = 0.0
    audio_duration: float = 0.0


def build_repair_cache_path(video_path: str, cache_dir: str, strategy: str) -> Path:
    """Return canonical cache path for a repaired video."""
    path_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:8]
    filename = f"repaired_{strategy}_{Path(video_path).stem}_{path_hash}.mp4"
    return Path(cache_dir) / filename


def legacy_repair_cache_path(video_path: str, cache_dir: str, strategy: str) -> Path:
    """Return legacy cache path (without hashed suffix)."""
    return Path(cache_dir) / f"repaired_{strategy}_{Path(video_path).name}"


def probe_media_info(path: str) -> MediaInfo:
    """Return clip duration (seconds) and whether an audio stream is present."""

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
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
        payload = json.loads(result.stdout) if result.stdout else {}
        fmt = payload.get("format", {})
        duration_str: Optional[str] = fmt.get("duration")
        duration = float(duration_str) if duration_str is not None else 0.0

        streams = payload.get("streams", [])
        has_audio = False
        video_duration = 0.0
        audio_duration = 0.0

        for stream in streams:
            codec_type = stream.get("codec_type")
            if codec_type == "audio":
                has_audio = True
                # Get audio stream duration
                stream_duration = stream.get("duration")
                if stream_duration:
                    audio_duration = float(stream_duration)
            elif codec_type == "video":
                # Get video stream duration
                stream_duration = stream.get("duration")
                if stream_duration:
                    video_duration = float(stream_duration)

        return MediaInfo(
            duration=duration or 0.0,
            has_audio=has_audio,
            video_duration=video_duration or duration or 0.0,
            audio_duration=audio_duration or duration or 0.0
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logging.error("ffprobe failed for %s: %s", path, exc)
        return MediaInfo()



def repair_video(video_path: str, output_path: str, cache_dir: Optional[str] = None, strategy: str = "fill") -> bool:
    """
    Repair damaged video clips by either filling missing frames or removing blank frames, and synchronizing audio/video.

    Args:
        video_path: Path to potentially damaged video file
        output_path: Path where repaired video will be saved
        cache_dir: Optional directory for caching repaired videos
        strategy: 'fill' (default) to fill missing frames, 'remove_blank' to remove blank/static frames

    Returns:
        True if repair successful, False otherwise
    """
    cache_path: Optional[Path] = None
    legacy_cache_path: Optional[Path] = None

    # Check if already repaired (cached) and always use it if present
    if cache_dir:
        cache_path = build_repair_cache_path(video_path, cache_dir, strategy)
        legacy_cache_path = legacy_repair_cache_path(video_path, cache_dir, strategy)

        existing_cache: Optional[Path] = None
        if cache_path.exists():
            existing_cache = cache_path
        elif legacy_cache_path.exists():
            try:
                legacy_cache_path.rename(cache_path)
                existing_cache = cache_path
                logging.info(f"Migrated legacy cache file to {cache_path.name}")
            except OSError as exc:
                logging.warning(f"Legacy cache migration failed: {exc}")
                try:
                    shutil.copy2(legacy_cache_path, cache_path)
                    if legacy_cache_path.exists():
                        legacy_cache_path.unlink()
                    existing_cache = cache_path
                    logging.info(f"Copied legacy cache file to {cache_path.name}")
                except Exception as copy_exc:
                    logging.warning(f"Legacy cache copy failed: {copy_exc}")
                    existing_cache = legacy_cache_path

        if existing_cache:
            logging.info(f"Using cached repaired video: {existing_cache}")
            if str(existing_cache) != output_path:
                try:
                    shutil.copy2(existing_cache, output_path)
                except Exception as exc:
                    logging.error(f"Failed to copy cached repaired video: {exc}")
                    return False
            return True

    media_info = probe_media_info(video_path)
    if not media_info.has_audio:
        logging.warning(f"No audio stream in {video_path}, skipping repair")
        return False

    duration_diff = abs(media_info.video_duration - media_info.audio_duration)
    needs_sync = duration_diff > 0.1

    logging.info(f"Repairing video: {Path(video_path).name} with strategy '{strategy}'")
    if needs_sync:
        logging.info(f"  Video duration: {media_info.video_duration:.2f}s, Audio duration: {media_info.audio_duration:.2f}s")

    command = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-err_detect", "ignore_err",
        "-i", video_path,
    ]

    video_filters = []
    audio_filters = []

    if strategy == "fill":
        # Fill missing frames: duplicate last good frame for missing sections
        video_filters.append("fps=fps=25")
        if media_info.video_duration > media_info.audio_duration + 0.1:
            trim_duration = media_info.audio_duration
            video_filters.append(f"trim=duration={trim_duration}")
            video_filters.append("setpts=PTS-STARTPTS")
        if media_info.audio_duration < media_info.video_duration - 0.1:
            pad_duration = media_info.video_duration - media_info.audio_duration
            audio_filters.append(f"apad=pad_dur={pad_duration}")
    elif strategy == "remove_blank":
        # Remove blank/static frames using mpdecimate (removes near-duplicate frames)
        # Optionally, use blackframe to detect pure black frames
        # mpdecimate removes frames that are nearly identical to previous
        video_filters.append("mpdecimate")
        video_filters.append("fps=fps=25")
        # After removing blanks, trim video to audio duration if needed
        if media_info.video_duration > media_info.audio_duration + 0.1:
            trim_duration = media_info.audio_duration
            video_filters.append(f"trim=duration={trim_duration}")
            video_filters.append("setpts=PTS-STARTPTS")
        if media_info.audio_duration < media_info.video_duration - 0.1:
            pad_duration = media_info.video_duration - media_info.audio_duration
            audio_filters.append(f"apad=pad_dur={pad_duration}")
    else:
        logging.error(f"Unknown repair strategy: {strategy}")
        return False

    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])
    if audio_filters:
        command.extend(["-af", ",".join(audio_filters)])

    command.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ])

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logging.error(f"ffmpeg repair failed for {video_path} (strategy: {strategy})")
            if result.stderr:
                logging.error(f"ffmpeg stderr: {result.stderr[:500]}")
            return False

        # Cache the repaired video if cache_dir provided
        if cache_dir and cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if Path(output_path) != cache_path:
                shutil.copy2(output_path, cache_path)
            if legacy_cache_path and legacy_cache_path.exists() and legacy_cache_path != cache_path:
                try:
                    legacy_cache_path.unlink()
                except Exception:
                    pass

        logging.info(f"✓ Video repaired successfully (strategy: {strategy})")
        return True

    except subprocess.TimeoutExpired:
        logging.error(f"ffmpeg repair timed out for {video_path} (strategy: {strategy})")
        return False
    except Exception as exc:
        logging.error(f"Unexpected error during repair (strategy: {strategy}): {exc}")
        return False


def extract_audio_segment(
    video_path: str,
    output_path: str,
    start: Optional[float] = None,
    end: Optional[float] = None,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bool:
    """Extract a portion of audio to WAV using ffmpeg to avoid buffering media in RAM."""

    command = ["ffmpeg", "-y", "-loglevel", "error"]
    if start is not None:
        command.extend(["-ss", f"{start:.3f}"])
    if end is not None:
        command.extend(["-to", f"{end:.3f}"])
    command.extend(
        [
            "-i",
            video_path,
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            output_path,
        ]
    )
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        logging.error("ffmpeg failed to extract audio segment from %s", video_path)
        return False
    return True
