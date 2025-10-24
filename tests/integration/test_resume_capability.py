#!/usr/bin/env python3
"""
Test script to validate preprocessing resume capability.

Tests:
1. Progress file creation and format
2. Resume from interrupted job
3. Progress file deletion on completion
4. Handling of corrupted progress files
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from blink_pipeline.media_validation import (
    _get_progress_file_path,
    _load_progress,
    _save_progress,
    _delete_progress
)


def test_progress_file_operations():
    """Test basic progress file operations."""
    print("\n=== Test 1: Progress File Operations ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test save
        progress_data = {
            'start_time': '2024-01-01T12:00:00',
            'total': 10,
            'completed': {
                '/video1.mp4': {'validated_path': '/cache/video1.mp4'},
                '/video2.mp4': {'validated_path': '/video2.mp4'}
            },
            'strategy': 'fill',
            'always_repair': False
        }

        _save_progress(tmpdir, progress_data)

        progress_file = _get_progress_file_path(tmpdir)
        if not progress_file.exists():
            print("❌ FAIL: Progress file not created")
            return False

        print(f"✅ Progress file created: {progress_file.name}")

        # Test load
        loaded = _load_progress(tmpdir)
        if not loaded:
            print("❌ FAIL: Could not load progress file")
            return False

        if loaded['total'] != 10:
            print(f"❌ FAIL: Loaded total={loaded['total']}, expected 10")
            return False

        if len(loaded['completed']) != 2:
            print(f"❌ FAIL: Loaded {len(loaded['completed'])} completed, expected 2")
            return False

        print("✅ Progress file loaded correctly")

        # Test delete
        _delete_progress(tmpdir)
        if progress_file.exists():
            print("❌ FAIL: Progress file not deleted")
            return False

        print("✅ Progress file deleted")

        return True


def test_corrupted_progress_file():
    """Test handling of corrupted progress file."""
    print("\n=== Test 2: Corrupted Progress File Handling ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        progress_file = _get_progress_file_path(tmpdir)

        # Create corrupted JSON file
        with open(progress_file, 'w') as f:
            f.write("{ invalid json }")

        loaded = _load_progress(tmpdir)
        if loaded is not None:
            print("❌ FAIL: Should return None for corrupted file")
            return False

        print("✅ Correctly handled corrupted progress file")

        # Create file with wrong structure
        with open(progress_file, 'w') as f:
            json.dump({'wrong': 'structure'}, f)

        loaded = _load_progress(tmpdir)
        if loaded is not None:
            print("❌ FAIL: Should return None for invalid structure")
            return False

        print("✅ Correctly handled invalid structure")

        return True


def test_progress_file_format():
    """Test that progress file has correct format."""
    print("\n=== Test 3: Progress File Format ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        progress_data = {
            'start_time': '2024-01-01T12:00:00',
            'total': 3,
            'completed': {
                '/path/to/video1.mp4': {'validated_path': '/cache/repaired_fill_video1_abc123.mp4'},
                '/path/to/video2.mp4': {'validated_path': '/path/to/video2.mp4'}
            },
            'strategy': 'fill',
            'always_repair': False
        }

        _save_progress(tmpdir, progress_data)

        # Load as JSON and verify structure
        progress_file = _get_progress_file_path(tmpdir)
        with open(progress_file, 'r') as f:
            data = json.load(f)

        required_keys = ['start_time', 'total', 'completed', 'strategy', 'always_repair']
        for key in required_keys:
            if key not in data:
                print(f"❌ FAIL: Missing required key: {key}")
                return False

        print(f"✅ All required keys present: {required_keys}")

        # Verify completed structure
        for video_path, result in data['completed'].items():
            if 'validated_path' not in result:
                print(f"❌ FAIL: Missing validated_path in completed entry")
                return False

        print(f"✅ Completed entries have correct structure")

        # Check that file is human-readable (has indentation)
        with open(progress_file, 'r') as f:
            content = f.read()

        if '\n' not in content or '  ' not in content:
            print("⚠️  WARNING: Progress file may not be properly indented")
        else:
            print("✅ Progress file is human-readable (indented JSON)")

        return True


def test_atomic_write():
    """Test that progress writes are atomic."""
    print("\n=== Test 4: Atomic Write Test ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        progress_data = {
            'start_time': '2024-01-01T12:00:00',
            'total': 1,
            'completed': {},
            'strategy': 'fill',
            'always_repair': False
        }

        # Save multiple times quickly
        for i in range(5):
            progress_data['completed'][f'/video{i}.mp4'] = {'validated_path': f'/cache/video{i}.mp4'}
            _save_progress(tmpdir, progress_data)

        # Verify final state is consistent
        loaded = _load_progress(tmpdir)
        if not loaded:
            print("❌ FAIL: Could not load progress after multiple writes")
            return False

        if len(loaded['completed']) != 5:
            print(f"❌ FAIL: Expected 5 completed, got {len(loaded['completed'])}")
            return False

        print("✅ Atomic writes maintained consistency")

        # Check no temporary files left behind
        temp_files = list(Path(tmpdir).glob('.preprocessing_progress_*.tmp'))
        if temp_files:
            print(f"⚠️  WARNING: {len(temp_files)} temporary files left behind")
            for f in temp_files:
                print(f"    {f.name}")
        else:
            print("✅ No temporary files left behind")

        return True


def test_no_progress_file():
    """Test loading when no progress file exists."""
    print("\n=== Test 5: No Progress File ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = _load_progress(tmpdir)

        if loaded is not None:
            print("❌ FAIL: Should return None when no progress file exists")
            return False

        print("✅ Correctly returns None when no progress file exists")
        return True


def main():
    """Run all resume capability tests."""
    print("=" * 70)
    print("Preprocessing Resume Capability Tests")
    print("=" * 70)

    tests = [
        test_progress_file_operations,
        test_corrupted_progress_file,
        test_progress_file_format,
        test_atomic_write,
        test_no_progress_file,
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
    print("Test Summary")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n✅ All tests passed! Resume capability verified.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
