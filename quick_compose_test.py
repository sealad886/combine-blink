"""
Quick real-data test: discover clips, group by overlap, pick one multi-camera event,
compose a composite video using the new MultiCameraComposer (skips transcription).
"""
import os
import sys
import yaml
import logging
from typing import Any, Dict, List
from datetime import datetime

# Ensure project root on path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blink_pipeline.discovery import discover_files
from blink_pipeline.grouping import group_videos
from blink_pipeline.multi_camera_composer import MultiCameraComposer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_config(path: str = 'config.yaml') -> Dict[str, Any]:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def pick_test_group(groups: List[List[Dict[str, Any]]], file_offset: int = 36) -> List[Dict[str, Any]]:
    """Pick a group whose cumulative clip index passes file_offset, preferring multi-camera.

    If no multi-camera group is found at or after the offset, return the group at/after
    the offset regardless, otherwise fall back to first multi-camera or first group.
    """
    if not groups:
        return []

    cumulative = 0
    candidate_after_offset = None
    for idx, group in enumerate(groups):
        start_idx = cumulative
        end_idx = cumulative + len(group) - 1
        cumulative += len(group)

        if start_idx < file_offset:
            continue

        # This is at/after the desired offset
        cameras = {c['camera'] for c in group}
        if len(cameras) >= 2:
            logging.info(
                "Selected group #%d at cumulative index [%d..%d] with %d cameras",
                idx + 1,
                start_idx,
                end_idx,
                len(cameras),
            )
            return group
        # Save as fallback while we search for a multi-camera group after offset
        if candidate_after_offset is None:
            candidate_after_offset = group

    # No multi-camera found after offset; return fallback at/after offset
    if candidate_after_offset is not None:
        cameras = {c['camera'] for c in candidate_after_offset}
        logging.info(
            "Selected (fallback) single-camera group at/after offset with %d clips and %d cameras",
            len(candidate_after_offset),
            len(cameras),
        )
        return candidate_after_offset

    # Fallbacks: first multi-camera group, else first group
    for group in groups:
        if len({c['camera'] for c in group}) >= 2:
            return group
    return groups[0]


def main() -> int:
    config = load_config()

    # Prepare paths
    input_dir = config['paths']['input_dir']
    output_dir = config['paths']['output_dir']
    videos_dir = os.path.join(output_dir, config['paths']['videos_dir'])
    os.makedirs(videos_dir, exist_ok=True)

    # Discover
    logging.info("Discovering files in %s", input_dir)
    files = discover_files(
        input_dir,
        config['discovery']['filename_pattern'],
        config,
    )
    if not files:
        logging.error("No files discovered under %s", input_dir)
        return 2

    logging.info("Discovered %d files", len(files))

    # Group
    max_diff = config['grouping']['max_time_diff_seconds']
    groups = group_videos(files, max_diff)
    if not groups:
        logging.error("No groups formed - check filename patterns and timestamps")
        return 3

    logging.info("Formed %d groups", len(groups))

    # Pick a test group at or beyond the desired file offset (default ~3 dozen)
    offset = int(os.environ.get('QC_FILE_OFFSET', '36'))
    group = pick_test_group(groups, file_offset=offset)
    if not group:
        logging.error("Could not pick a group for testing")
        return 4

    cameras = sorted({c['camera'] for c in group})
    t0 = min(c['datetime'] for c in group)
    group_label = t0.strftime('%Y%m%d_%H%M%S') + '_' + ('+'.join(cameras))

    # Ensure each clip has 'path' for composer (fallback to 'full_path')
    prepared_group: List[Dict[str, Any]] = []
    for clip in group:
        clip_copy = dict(clip)
        if not clip_copy.get('path') and clip_copy.get('full_path'):
            clip_copy['path'] = clip_copy['full_path']
        prepared_group.append(clip_copy)

    # Compose
    composer = MultiCameraComposer(config)
    # For a fast test: limit to the first N clips and shorter duration if many clips
    MAX_CLIPS = int(os.environ.get('QC_MAX_CLIPS', '12'))
    test_group = sorted(prepared_group, key=lambda c: c['datetime'])[:MAX_CLIPS]

    out_path = os.path.join(videos_dir, f"TEST_{group_label}_composite.mp4")
    logging.info("Composing test composite (first %d clips): %s", len(test_group), out_path)
    ok = composer.compose_multi_camera_event(test_group, out_path)

    if not ok:
        logging.error("Composition failed")
        return 5

    if os.path.exists(out_path):
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        logging.info("SUCCESS: Wrote %s (%.2f MB)", out_path, size_mb)
        print("\nTry opening the output file to review the angle switching and audio quality:")
        print(out_path)
        return 0

    logging.error("Output file not found after composition")
    return 6


if __name__ == '__main__':
    raise SystemExit(main())
