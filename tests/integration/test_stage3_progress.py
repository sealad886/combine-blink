#!/usr/bin/env python3
"""
Quick test to verify Stage 3 progress bars update correctly.
Run a small subset of clips through transcription to observe progress behavior.
"""
import os
import sys
import yaml
import logging
from typing import Any, Dict

# Ensure project root on path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.discovery import discover_files
from src.grouping import group_videos

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_config(path: str = 'config.yaml') -> Dict[str, Any]:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def main() -> int:
    config = load_config()

    # Override to limit transcription workers for easier observation
    config['concurrency']['transcription_workers'] = 1

    # Disable other stages we don't need for this test
    config['multi_camera_composition']['enable_composition'] = False

    # Discover and group
    input_dir = config['paths']['input_dir']
    files = discover_files(
        input_dir,
        config['discovery']['filename_pattern'],
        config,
    )

    if not files:
        logging.error("No files discovered")
        return 1

    logging.info("Discovered %d files", len(files))

    max_diff = config['grouping']['max_time_diff_seconds']
    groups = group_videos(files, max_diff)

    if not groups:
        logging.error("No groups formed")
        return 2

    logging.info("Formed %d groups", len(groups))

    # Pick first group with multiple clips to test progress
    test_group = None
    for group in groups:
        if len(group) >= 3:  # Want at least 3 clips to see progress
            test_group = group
            break

    if not test_group:
        # Fallback to first group
        test_group = groups[0]

    logging.info("Testing with group of %d clips", len(test_group))

    # Now run main pipeline which should show Stage 3 progress
    logging.info("\n" + "="*80)
    logging.info("Running main pipeline - observe Stage 3 progress bars")
    logging.info("="*80 + "\n")

    from src.orchestrator import main as orchestrator_main
    orchestrator_main()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
