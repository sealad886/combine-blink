"""
Video validation and repair preprocessing module.

This module provides upfront validation and repair of all discovered videos
before they enter the main processing pipeline. Videos are validated and
repaired exactly once, with results cached for subsequent runs.

Key principles:
- Single repair cache directory for all repaired videos
- Each video repaired at most once
- Later stages work with validated files only
- Clear separation: raw input → validation/repair → processing
"""

import json
import logging
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from blink_pipeline.media_utils import (
    build_repair_cache_path,
    legacy_repair_cache_path,
    probe_media_info,
    repair_video,
)


def _init_worker():
    """Initialize worker process with optimized settings."""
    logging.getLogger().setLevel(logging.ERROR)


def _get_progress_file_path(cache_dir: str) -> Path:
    """Get the path to the progress tracking file."""
    return Path(cache_dir) / ".preprocessing_progress.json"


def _load_progress(cache_dir: str) -> dict | None:
    """
    Load progress from previous interrupted run.

    Returns:
        Dict with progress data, or None if no valid progress file exists
    """
    progress_file = _get_progress_file_path(cache_dir)

    if not progress_file.exists():
        return None

    try:
        with open(progress_file) as f:
            progress = json.load(f)

        # Validate structure
        if not isinstance(progress, dict) or 'completed' not in progress:
            logging.warning("Invalid progress file format, starting fresh")
            return None

        return progress
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"Could not load progress file: {e}, starting fresh")
        return None


def _save_progress(cache_dir: str, progress_data: dict) -> None:
    """
    Atomically save progress to file.

    Uses atomic write (temp file + rename) to prevent corruption.
    """
    progress_file = _get_progress_file_path(cache_dir)
    tmp_path: str | None = None

    # Write to temporary file first
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=cache_dir,
            prefix='.preprocessing_progress_',
            suffix='.tmp',
            delete=False
        ) as tmp_file:
            json.dump(progress_data, tmp_file, indent=2)
            tmp_path = tmp_file.name

        # Atomic rename
        os.rename(tmp_path, progress_file)
        tmp_path = None  # Successfully renamed, no cleanup needed
    except Exception as e:
        logging.error(f"Failed to save progress: {e}")
        # Clean up temp file if it exists
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                # Best-effort cleanup; ignore failures
                pass


def _delete_progress(cache_dir: str) -> None:
    """Delete progress file after successful completion."""
    progress_file = _get_progress_file_path(cache_dir)
    try:
        if progress_file.exists():
            progress_file.unlink()
            logging.info("Deleted progress file (preprocessing complete)")
    except Exception as e:
        logging.warning(f"Could not delete progress file: {e}")


def _get_cache_path(video_path: str, cache_dir: str, strategy: str) -> Path:
    """
    Generate collision-safe cache path for a video.

    Uses a hash of the full path to prevent collisions when videos
    from different directories have the same filename.

    Args:
        video_path: Original video path
        cache_dir: Cache directory
        strategy: Repair strategy name

    Returns:
        Path object for the cache file
    """
    return build_repair_cache_path(video_path, cache_dir, strategy)


def _get_cache_path_legacy(video_path: str, cache_dir: str, strategy: str) -> Path:
    """Legacy cache path format for backward compatibility."""
    return legacy_repair_cache_path(video_path, cache_dir, strategy)


def _validate_video_job(args: tuple[str, str, str, bool]) -> tuple[str, str, str]:
    """
    Worker: Validate a single video and repair if necessary.

    Args:
        args: Tuple of (video_path, cache_dir, strategy, always_repair)

    Returns:
        Tuple of (original_path, validated_path, status)
        where status is 'cached', 'repaired', or 'original'
    """
    video_path, cache_dir, strategy, always_repair = args

    # Check cache first (with backward compatibility)
    cache_path = _get_cache_path(video_path, cache_dir, strategy)
    legacy_cache_path = _get_cache_path_legacy(video_path, cache_dir, strategy)

    if cache_path.exists():
        # Cached repair exists - use it
        return (video_path, str(cache_path), 'cached')
    elif legacy_cache_path.exists():
        # Migrate legacy cache to new format
        try:
            legacy_cache_path.rename(cache_path)
            logging.info(f"Migrated cache file: {legacy_cache_path.name} → {cache_path.name}")
        except Exception as e:
            logging.warning(f"Cache migration failed: {e}, using legacy path")
            cache_path = legacy_cache_path
        return (video_path, str(cache_path), 'cached')

    # Probe video to check if repair needed
    media_info = probe_media_info(video_path)

    # Determine if repair needed
    needs_repair = False
    if not media_info.has_audio:
        # No audio - can't repair, use original
        return (video_path, video_path, 'original')

    duration_diff = abs(media_info.video_duration - media_info.audio_duration)
    needs_repair = duration_diff > 0.1  # More than 100ms difference

    if not needs_repair and not always_repair:
        # Video is valid, no repair needed
        return (video_path, video_path, 'original')

    # Repair needed or always_repair enabled
    os.makedirs(cache_dir, exist_ok=True)
    success = repair_video(video_path, str(cache_path), cache_dir=cache_dir, strategy=strategy)

    if success:
        return (video_path, str(cache_path), 'repaired')
    else:
        # Repair failed, fall back to original
        logging.warning(f"Repair failed for {video_path}, using original")
        return (video_path, video_path, 'original')


def preprocess_videos(
    video_paths: list[str],
    cache_dir: str,
    strategy: str = "fill",
    always_repair: bool = False,
    max_workers: int = 8,
    progress_callback: Callable[[int, int], None] | None = None,
    enable_resume: bool = True
) -> dict[str, str]:
    """
    Validate and repair all videos upfront, returning a path mapping.

    This function processes all discovered videos before the main pipeline stages,
    ensuring each video is validated and repaired exactly once. The results are
    cached for subsequent runs.

    Supports resuming from interrupted runs: if preprocessing is interrupted,
    the next run will skip already-processed videos and continue from where it left off.

    Args:
        video_paths: List of paths to all discovered videos
        cache_dir: Directory for caching repaired videos
        strategy: Repair strategy ('fill' or 'remove_blank')
        always_repair: If True, repair all videos regardless of detected issues
        max_workers: Number of parallel repair workers
        progress_callback: Optional callback(completed, total) for progress tracking
        enable_resume: If True, resume from interrupted runs (default: True)

    Returns:
        Dictionary mapping original_path → validated_path
        (validated_path is either repaired cache path or original if no repair needed)
    """
    if not video_paths:
        return {}

    # Create cache directory
    os.makedirs(cache_dir, exist_ok=True)

    total = len(video_paths)
    path_mapping: dict[str, str] = {}

    # Load previous progress if resuming
    prior_progress = _load_progress(cache_dir) if enable_resume else None
    start_time = datetime.now().isoformat()

    if prior_progress:
        # Restore completed videos from previous run
        completed_videos = prior_progress.get('completed', {})
        start_time = prior_progress.get('start_time', start_time)

        for video_path in video_paths:
            if video_path in completed_videos:
                path_mapping[video_path] = completed_videos[video_path]['validated_path']

        if path_mapping:
            logging.info(
                f"Resuming from previous run: {len(path_mapping)}/{total} videos already completed"
            )

    # Build job list for videos that still need processing
    jobs = [(path, cache_dir, strategy, always_repair)
            for path in video_paths
            if path not in path_mapping]

    if not jobs:
        # All videos already completed
        logging.info(f"All {total} videos already completed, nothing to process")
        if enable_resume:
            _delete_progress(cache_dir)
        return path_mapping

    # Process remaining videos
    logging.info(f"Processing {len(jobs)} video(s)...")
    completed_count = len(path_mapping)  # Start from already-completed count
    save_interval = max(1, len(jobs) // 20)  # Save progress every ~5%
    videos_since_save = 0

    with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker) as executor:
        futures = {executor.submit(_validate_video_job, job): job[0] for job in jobs}

        for future in as_completed(futures):
            original_path = futures[future]
            try:
                orig_path, validated_path, status = future.result()
                path_mapping[orig_path] = validated_path
                completed_count += 1
                videos_since_save += 1

                # Batch progress saves (every N videos or at end)
                if enable_resume and videos_since_save >= save_interval:
                    progress_data = {
                        'start_time': start_time,
                        'total': total,
                        'completed': {path: {'validated_path': vpath}
                                     for path, vpath in path_mapping.items()},
                        'strategy': strategy,
                        'always_repair': always_repair
                    }
                    _save_progress(cache_dir, progress_data)
                    videos_since_save = 0

                # Report progress
                if progress_callback:
                    progress_callback(completed_count, total)

            except Exception as exc:
                logging.error(f"Validation failed for {original_path}: {exc}")
                # Fall back to original path
                path_mapping[original_path] = original_path
                completed_count += 1

                if progress_callback:
                    progress_callback(completed_count, total)

    # Final progress save if needed
    if enable_resume and videos_since_save > 0:
        progress_data = {
            'start_time': start_time,
            'total': total,
            'completed': {path: {'validated_path': vpath}
                         for path, vpath in path_mapping.items()},
            'strategy': strategy,
            'always_repair': always_repair
        }
        _save_progress(cache_dir, progress_data)

    # Delete progress file on successful completion
    if enable_resume:
        _delete_progress(cache_dir)

    # Calculate final statistics
    total_repaired = sum(1 for orig, validated in path_mapping.items() if orig != validated)
    total_original = total - total_repaired

    # Log summary
    logging.info(
        f"Video validation complete: {total} videos total, "
        f"{total_repaired} repaired, {total_original} used as-is"
    )

    return path_mapping


def get_validation_stats(path_mapping: dict[str, str]) -> tuple[int, int, int]:
    """
    Analyze path mapping to get validation statistics.

    Args:
        path_mapping: Dictionary from preprocess_videos()

    Returns:
        Tuple of (total_videos, repaired_count, original_count)
    """
    total = len(path_mapping)
    repaired = sum(1 for orig, validated in path_mapping.items() if orig != validated)
    original = total - repaired

    return (total, repaired, original)
