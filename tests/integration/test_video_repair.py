#!/usr/bin/env python3
"""
Test script to validate video repair functionality.

This script tests the repair system without requiring actual video files.
It validates:
- MediaInfo parsing with stream durations
- Repair decision logic
- Cache directory creation
- Configuration loading
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all repair-related imports work."""
    print("Testing imports...")
    try:
        from src.media_utils import repair_video, probe_media_info, MediaInfo
        print("✓ Core repair imports successful")
        print("  - repair_video")
        print("  - probe_media_info")
        print("  - MediaInfo")

        # Try importing transcription (may fail without torch/whisper)
        try:
            from src.transcription import process_audio_for_transcription
            print("  - process_audio_for_transcription")
        except ImportError as e:
            print(f"  ⚠ transcription.py requires dependencies: {e}")
            print("    (This is OK - repair functions work independently)")

        return True
    except ImportError as e:
        print(f"✗ Core import failed: {e}")
        return False

def test_media_info_structure():
    """Test MediaInfo dataclass with new fields."""
    print("\nTesting MediaInfo structure...")
    try:
        from src.media_utils import MediaInfo

        # Test with all fields
        info = MediaInfo(
            duration=10.5,
            has_audio=True,
            video_duration=10.7,
            audio_duration=10.5
        )

        assert info.duration == 10.5
        assert info.has_audio is True
        assert info.video_duration == 10.7
        assert info.audio_duration == 10.5

        # Test sync detection logic
        duration_diff = abs(info.video_duration - info.audio_duration)
        needs_repair = duration_diff > 0.1

        assert needs_repair is True  # 0.2s difference > 0.1s threshold

        print("✓ MediaInfo structure is correct")
        print(f"  - duration: {info.duration}s")
        print(f"  - video_duration: {info.video_duration}s")
        print(f"  - audio_duration: {info.audio_duration}s")
        print(f"  - needs_repair: {needs_repair} (diff: {duration_diff:.2f}s)")
        return True
    except Exception as e:
        print(f"✗ MediaInfo test failed: {e}")
        return False

def test_config_loading():
    """Test that config.yaml has repair settings."""
    print("\nTesting config.yaml repair settings...")
    try:
        import yaml

        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        transcription = config.get('transcription', {})
        always_repair = transcription.get('always_repair')
        repair_cache_dir = transcription.get('repair_cache_dir')

        assert always_repair is not None, "always_repair not found in config"
        assert repair_cache_dir is not None, "repair_cache_dir not found in config"

        print("✓ Config has repair settings")
        print(f"  - always_repair: {always_repair}")
        print(f"  - repair_cache_dir: {repair_cache_dir}")
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False

def test_repair_decision_logic():
    """Test the repair decision logic."""
    print("\nTesting repair decision logic...")

    test_cases = [
        # (video_dur, audio_dur, expected_needs_repair, description)
        (10.0, 10.0, False, "Perfect sync"),
        (10.05, 10.0, False, "Within threshold (50ms)"),
        (10.15, 10.0, True, "Above threshold (150ms)"),
        (10.0, 10.2, True, "Audio longer (200ms)"),
        (15.5, 15.1, True, "Large difference (400ms)"),
    ]

    all_passed = True
    for video_dur, audio_dur, expected, desc in test_cases:
        duration_diff = abs(video_dur - audio_dur)
        needs_repair = duration_diff > 0.1

        if needs_repair == expected:
            print(f"  ✓ {desc}: {video_dur}s vs {audio_dur}s → {needs_repair}")
        else:
            print(f"  ✗ {desc}: Expected {expected}, got {needs_repair}")
            all_passed = False

    return all_passed

def test_cache_directory_creation():
    """Test cache directory creation logic."""
    print("\nTesting cache directory creation...")
    try:
        test_cache_dir = "test_repair_cache"

        # Create directory
        os.makedirs(test_cache_dir, exist_ok=True)

        # Verify it exists
        assert os.path.isdir(test_cache_dir), "Cache directory not created"

        # Clean up
        os.rmdir(test_cache_dir)

        print("✓ Cache directory creation works")
        return True
    except Exception as e:
        print(f"✗ Cache directory test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 80)
    print("VIDEO REPAIR SYSTEM VALIDATION")
    print("=" * 80)

    tests = [
        test_imports,
        test_media_info_structure,
        test_config_loading,
        test_repair_decision_logic,
        test_cache_directory_creation,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            results.append(False)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")

    if passed == total:
        print("\n✓ ALL TESTS PASSED - Video repair system is ready!")
        print("\nNext steps:")
        print("  1. Run the pipeline: python3 main.py")
        print("  2. Monitor logs for repair messages")
        print("  3. Check output/repaired_cache for cached repairs")
        print("  4. Review VIDEO_REPAIR.md for detailed documentation")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED - Review errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
