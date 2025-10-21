#!/usr/bin/env python3
"""
Integration test for preprocessing resume capability.

Simulates a real preprocessing run with interruption and resume.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))


def create_mock_video_list(tmpdir: str, count: int) -> list:
    """Create a list of mock video paths."""
    return [f"{tmpdir}/video_{i:03d}.mp4" for i in range(count)]


def mock_preprocess_partial(video_paths, cache_dir, complete_count):
    """
    Mock preprocessing that completes only some videos.

    Simulates what happens during an interrupted run.
    """
    from src.media_validation import _save_progress
    from datetime import datetime

    # Simulate processing first N videos
    completed = {}
    for i, path in enumerate(video_paths[:complete_count]):
        # Mock validated path
        validated_path = f"{cache_dir}/repaired_fill_video_{i:03d}_abc12345.mp4"
        completed[path] = {'validated_path': validated_path}

    # Save progress (simulating interrupted run)
    progress_data = {
        'start_time': datetime.now().isoformat(),
        'total': len(video_paths),
        'completed': completed,
        'strategy': 'fill',
        'always_repair': False
    }
    _save_progress(cache_dir, progress_data)

    return completed


def test_resume_integration():
    """Test complete resume workflow."""
    print("\n=== Integration Test: Resume Workflow ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "cache")
        os.makedirs(cache_dir)

        # Create mock video list
        video_paths = create_mock_video_list(tmpdir, 50)
        print(f"Created {len(video_paths)} mock video paths")

        # Simulate interrupted run (25 videos completed)
        print("\n1. Simulating interrupted run (25/50 completed)...")
        completed_first = mock_preprocess_partial(video_paths, cache_dir, 25)
        print(f"   ✅ Saved progress: {len(completed_first)} videos completed")

        # Check progress file exists
        from src.media_validation import _get_progress_file_path
        progress_file = _get_progress_file_path(cache_dir)
        if not progress_file.exists():
            print("   ❌ FAIL: Progress file not created")
            return False
        print(f"   ✅ Progress file created: {progress_file}")

        # Load progress and verify
        from src.media_validation import _load_progress
        loaded = _load_progress(cache_dir)
        if not loaded:
            print("   ❌ FAIL: Could not load progress")
            return False

        if len(loaded['completed']) != 25:
            print(f"   ❌ FAIL: Expected 25 completed, got {len(loaded['completed'])}")
            return False
        print(f"   ✅ Progress loaded correctly: {len(loaded['completed'])} videos")

        # Simulate resuming (process remaining 25)
        print("\n2. Simulating resumed run (processing remaining 25)...")

        # Add more completed videos
        completed_second = completed_first.copy()
        for i, path in enumerate(video_paths[25:], start=25):
            validated_path = f"{cache_dir}/repaired_fill_video_{i:03d}_xyz67890.mp4"
            completed_second[path] = {'validated_path': validated_path}

        # Save updated progress
        from src.media_validation import _save_progress
        from datetime import datetime
        progress_data = {
            'start_time': loaded['start_time'],  # Preserve original start time
            'total': len(video_paths),
            'completed': completed_second,
            'strategy': 'fill',
            'always_repair': False
        }
        _save_progress(cache_dir, progress_data)
        print(f"   ✅ Updated progress: {len(completed_second)} videos total")

        # Verify all videos completed
        loaded_final = _load_progress(cache_dir)
        if not loaded_final:
            print("   ❌ FAIL: Could not load final progress")
            return False
        if len(loaded_final['completed']) != 50:
            print(f"   ❌ FAIL: Expected 50 completed, got {len(loaded_final['completed'])}")
            return False
        print(f"   ✅ All videos completed: {len(loaded_final['completed'])}/50")

        # Verify start time preserved
        if loaded_final['start_time'] != loaded['start_time']:
            print("   ⚠️  WARNING: Start time not preserved")
        else:
            print("   ✅ Original start time preserved")

        # Simulate completion (delete progress file)
        print("\n3. Simulating completion (cleanup)...")
        from src.media_validation import _delete_progress
        _delete_progress(cache_dir)

        if progress_file.exists():
            print("   ❌ FAIL: Progress file not deleted")
            return False
        print("   ✅ Progress file deleted")

        return True


def test_resume_with_new_videos():
    """Test resume when video list changes."""
    print("\n=== Integration Test: Video List Changes ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "cache")
        os.makedirs(cache_dir)

        # First run: 20 videos
        video_paths_v1 = create_mock_video_list(tmpdir, 20)
        completed = mock_preprocess_partial(video_paths_v1, cache_dir, 15)
        print(f"First run: 15/20 videos completed")

        # Second run: 30 videos (10 new)
        video_paths_v2 = create_mock_video_list(tmpdir, 30)

        from src.media_validation import _load_progress
        loaded = _load_progress(cache_dir)

        if not loaded:
            print("   ❌ FAIL: Could not load progress for second run")
            return False

        # Check which videos would be skipped
        already_done = [p for p in video_paths_v2 if p in loaded['completed']]
        need_processing = [p for p in video_paths_v2 if p not in loaded['completed']]

        print(f"Second run: {len(already_done)} to skip, {len(need_processing)} to process")

        if len(already_done) != 15:
            print(f"   ❌ FAIL: Expected 15 to skip, got {len(already_done)}")
            return False

        if len(need_processing) != 15:  # 5 remaining from v1 + 10 new
            print(f"   ❌ FAIL: Expected 15 to process, got {len(need_processing)}")
            return False

        print("   ✅ Correctly identified videos to skip and process")
        return True


def test_resume_with_errors():
    """Test resume when some videos fail."""
    print("\n=== Integration Test: Error Handling ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "cache")
        os.makedirs(cache_dir)

        video_paths = create_mock_video_list(tmpdir, 10)

        # Simulate processing with errors
        from src.media_validation import _save_progress
        from datetime import datetime

        completed = {}
        # Videos 0, 2, 4, 6, 8 completed successfully
        for i in [0, 2, 4, 6, 8]:
            path = video_paths[i]
            validated_path = f"{cache_dir}/repaired_fill_video_{i:03d}_abc12345.mp4"
            completed[path] = {'validated_path': validated_path}

        # Videos 1, 3, 5, 7, 9 failed (use original path)
        for i in [1, 3, 5, 7, 9]:
            path = video_paths[i]
            completed[path] = {'validated_path': path}  # Original path = failed

        progress_data = {
            'start_time': datetime.now().isoformat(),
            'total': len(video_paths),
            'completed': completed,
            'strategy': 'fill',
            'always_repair': False
        }
        _save_progress(cache_dir, progress_data)

        print(f"Saved progress with {len(completed)} videos (5 repaired, 5 original)")

        # Load and verify
        from src.media_validation import _load_progress
        loaded = _load_progress(cache_dir)

        if not loaded:
            print("   ❌ FAIL: Could not load progress")
            return False

        if len(loaded['completed']) != 10:
            print(f"   ❌ FAIL: Expected 10 completed, got {len(loaded['completed'])}")
            return False

        # Count repaired vs original
        repaired = sum(1 for path, result in loaded['completed'].items()
                      if result['validated_path'] != path)
        original = sum(1 for path, result in loaded['completed'].items()
                      if result['validated_path'] == path)

        if repaired != 5 or original != 5:
            print(f"   ❌ FAIL: Expected 5 repaired and 5 original, got {repaired} and {original}")
            return False

        print(f"   ✅ Correctly tracked {repaired} repaired and {original} original")
        return True


def main():
    """Run all integration tests."""
    print("=" * 70)
    print("Preprocessing Resume Integration Tests")
    print("=" * 70)

    tests = [
        test_resume_integration,
        test_resume_with_new_videos,
        test_resume_with_errors,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test_func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "=" * 70)
    print("Integration Test Summary")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n✅ All integration tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
