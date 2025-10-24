import logging
from typing import Any


def group_videos(video_files: list[dict[str, Any]], max_diff_seconds: int) -> list[list[dict[str, Any]]]:
    """
    Groups video files into multi-camera events based on overlapping timestamps.

    All cameras point into the same room from different angles. When motion is detected,
    multiple cameras may record overlapping clips. This function groups all clips that
    occurred during overlapping time periods into a single multi-camera event.

    Args:
        video_files (list): A list of video file dictionaries from discover_files.
                           Each dict must have 'datetime', 'camera', and 'path' keys.
        max_diff_seconds (int): Max time difference to consider clips as part of the same event.
                               Clips starting within this window from the most recent clip
                               in the group are added to that group.

    Returns:
        list: A list of lists, where each inner list contains all video clips from
              different cameras that overlap in time and belong to the same event.
              Groups are sorted chronologically by their earliest timestamp.
    """
    if not video_files:
        return []

    # Sort all files chronologically regardless of camera
    sorted_files = sorted(video_files, key=lambda x: x['datetime'])

    all_groups = []
    current_group = [sorted_files[0]]

    for video in sorted_files[1:]:
        # Calculate time difference from the MOST RECENT clip in current group
        # This allows for overlapping windows where cameras trigger sequentially
        most_recent_in_group = max(clip['datetime'] for clip in current_group)
        time_diff = (video['datetime'] - most_recent_in_group).total_seconds()

        # If this video starts within the grouping window from most recent, add to current group
        if time_diff <= max_diff_seconds:
            current_group.append(video)
        else:
            # Start a new group
            all_groups.append(current_group)
            current_group = [video]

    # Add the last group
    if current_group:
        all_groups.append(current_group)

    # Log grouping statistics
    _log_grouping_stats(all_groups)

    return all_groups
def _log_grouping_stats(groups: list[list[dict[str, Any]]]) -> None:
    """Log statistics about the grouping results."""
    if not groups:
        return

    total_clips = sum(len(group) for group in groups)
    multi_camera_groups = sum(1 for group in groups if len(group) > 1)
    single_camera_groups = len(groups) - multi_camera_groups

    # Get camera distribution
    cameras_per_group = [len(set(clip['camera'] for clip in group)) for group in groups]
    max_cameras = max(cameras_per_group) if cameras_per_group else 0

    logging.info(f"Grouped {total_clips} clips into {len(groups)} events")
    logging.info(f"  - {multi_camera_groups} multi-camera events (2+ cameras)")
    logging.info(f"  - {single_camera_groups} single-camera events")
    logging.info(f"  - Max cameras in one event: {max_cameras}")

    # Log details for multi-camera groups
    for idx, group in enumerate(groups, 1):
        cameras = set(clip['camera'] for clip in group)
        if len(cameras) > 1:
            start_time = min(clip['datetime'] for clip in group)
            end_time = max(clip['datetime'] for clip in group)
            duration = (end_time - start_time).total_seconds()
            logging.debug(
                f"Event {idx}: {len(group)} clips from {len(cameras)} cameras "
                f"({', '.join(sorted(cameras))}) spanning {duration:.1f}s"
            )
