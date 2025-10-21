#!/usr/bin/env python3
"""
Test script to validate the unified repair cache system.

This script checks:
1. Single repair cache directory is used
2. No duplicate repairs occur
3. Cached repairs are reused correctly
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.media_validation import preprocess_videos, get_validation_stats


def test_unified_repair_cache():
    """Test that repair cache works correctly."""

    print("=" * 80)
    print("TESTING UNIFIED REPAIR CACHE SYSTEM")
    print("=" * 80)
    print()

    # Use a small subset of test videos
    test_dir = Path("25-10-15")
    if not test_dir.exists():
        print(f"❌ Test directory {test_dir} not found")
        return False

    # Find some test videos
    video_paths = list(test_dir.glob("*.mp4"))[:5]  # Just test with 5 videos

    if not video_paths:
        print(f"❌ No video files found in {test_dir}")
        return False

    print(f"✓ Found {len(video_paths)} test videos")
    print()

    # Clean up old caches
    cache_dir = Path("output/test_repair_cache")
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
        print(f"✓ Cleaned up old test cache")

    # Test 1: First run should repair videos
    print("=" * 80)
    print("TEST 1: First run (should repair videos)")
    print("=" * 80)
    print()

    video_paths_str = [str(p) for p in video_paths]

    path_mapping = preprocess_videos(
        video_paths_str,
        str(cache_dir),
        strategy="fill",
        always_repair=False,  # Only repair if needed
        max_workers=2
    )

    total1, repaired1, original1 = get_validation_stats(path_mapping)
    print(f"\n✓ First run complete:")
    print(f"  • Total: {total1}")
    print(f"  • Repaired: {repaired1}")
    print(f"  • Original: {original1}")
    print()

    # Check cache directory exists
    if not cache_dir.exists():
        print(f"❌ Cache directory was not created")
        return False

    cached_files_first = list(cache_dir.glob("*.mp4"))
    print(f"✓ Cache directory contains {len(cached_files_first)} files")
    print()

    # Test 2: Second run should use cache
    print("=" * 80)
    print("TEST 2: Second run (should use cache)")
    print("=" * 80)
    print()

    path_mapping2 = preprocess_videos(
        video_paths_str,
        str(cache_dir),
        strategy="fill",
        always_repair=False,
        max_workers=2
    )

    total2, repaired2, original2 = get_validation_stats(path_mapping2)
    print(f"\n✓ Second run complete:")
    print(f"  • Total: {total2}")
    print(f"  • Repaired: {repaired2}")
    print(f"  • Original: {original2}")
    print()

    # Check cache was reused (same number of files)
    cached_files_second = list(cache_dir.glob("*.mp4"))
    if len(cached_files_second) != len(cached_files_first):
        print(f"❌ Cache file count changed: {len(cached_files_first)} -> {len(cached_files_second)}")
        return False

    print(f"✓ Cache was reused (no new files created)")
    print()

    # Test 3: Verify path mappings are consistent
    print("=" * 80)
    print("TEST 3: Verify path mappings")
    print("=" * 80)
    print()

    if path_mapping != path_mapping2:
        print(f"❌ Path mappings differ between runs")
        print(f"Run 1: {path_mapping}")
        print(f"Run 2: {path_mapping2}")
        return False

    print(f"✓ Path mappings are consistent")
    print()

    # Cleanup
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
        print(f"✓ Cleaned up test cache")

    print()
    print("=" * 80)
    print("✅ ALL TESTS PASSED")
    print("=" * 80)
    print()

    return True


if __name__ == "__main__":
    success = test_unified_repair_cache()
    sys.exit(0 if success else 1)
