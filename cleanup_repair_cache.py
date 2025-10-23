#!/usr/bin/env python3
"""
Cleanup script for old repair cache directories and test outputs.

This script:
1. Removes old repair_strategy_cache directory
2. Moves any repaired video files from output/ root to proper locations
3. Creates a proper test_repairs directory for test outputs
"""

import shutil
from pathlib import Path


def main():
    print("=" * 80)
    print("REPAIR CACHE CLEANUP")
    print("=" * 80)
    print()

    output_dir = Path("output")
    if not output_dir.exists():
        print("✓ No output directory found - nothing to clean")
        return

    # 1. Remove old repair_strategy_cache
    old_cache = output_dir / "repair_strategy_cache"
    if old_cache.exists():
        print(f"Removing old cache directory: {old_cache}")
        try:
            shutil.rmtree(old_cache)
            print(f"  ✓ Removed {old_cache}")
        except Exception as e:
            print(f"  ✗ Failed to remove: {e}")
    else:
        print("✓ No old repair_strategy_cache directory found")

    print()

    # 2. Find and clean up stray repaired videos in output/ root
    print("Checking for stray repaired videos in output/ root...")
    stray_files = []
    for item in output_dir.iterdir():
        # Look for files that match repair patterns
        if item.is_file() and item.suffix == '.mp4':
            if '_fill.mp4' in item.name or '_remove_blank.mp4' in item.name:
                stray_files.append(item)

    if stray_files:
        print(f"Found {len(stray_files)} stray repaired videos:")
        test_repairs_dir = output_dir / "test_repairs"
        test_repairs_dir.mkdir(exist_ok=True)

        for file in stray_files:
            dest = test_repairs_dir / file.name
            print(f"  Moving: {file.name} → test_repairs/")
            try:
                shutil.move(str(file), str(dest))
                print(f"    ✓ Moved to {dest}")
            except Exception as e:
                print(f"    ✗ Failed: {e}")
    else:
        print("  ✓ No stray repaired videos found")

    print()

    # 3. Summary of current structure
    print("=" * 80)
    print("CURRENT CACHE STRUCTURE")
    print("=" * 80)
    print()

    repaired_cache = output_dir / "repaired_cache"
    if repaired_cache.exists():
        cached_files = list(repaired_cache.glob("*.mp4"))
        print(f"✓ Unified repair cache: {repaired_cache}")
        print(f"  {len(cached_files)} cached repairs")
    else:
        print("⚠ No repaired_cache directory (will be created on first run)")

    print()

    test_repairs = output_dir / "test_repairs"
    if test_repairs.exists():
        test_files = list(test_repairs.glob("*.mp4"))
        print(f"✓ Test outputs: {test_repairs}")
        print(f"  {len(test_files)} test files")
    else:
        print("✓ No test_repairs directory (clean)")

    print()
    print("=" * 80)
    print("✅ CLEANUP COMPLETE")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
