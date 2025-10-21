"""
Test script for multi-camera grouping logic.

This script creates test video clip data and verifies that the grouping
logic correctly groups clips from multiple cameras based on overlapping timestamps.
"""

from datetime import datetime, timedelta
from src.grouping import group_videos


def create_test_clip(camera: str, time_offset_seconds: int, base_time: datetime) -> dict:
    """Create a test video clip dictionary."""
    return {
        'camera': camera,
        'datetime': base_time + timedelta(seconds=time_offset_seconds),
        'path': f'/fake/path/{camera}_{time_offset_seconds}.mp4',
        'full_path': f'/fake/path/{camera}_{time_offset_seconds}.mp4'
    }


def test_single_camera_grouping():
    """Test grouping with clips from a single camera."""
    print("\n" + "="*80)
    print("TEST 1: Single Camera Grouping")
    print("="*80)

    base_time = datetime(2025, 10, 15, 10, 0, 0)
    clips = [
        create_test_clip('FrontDoor', 0, base_time),
        create_test_clip('FrontDoor', 60, base_time),    # 1 minute later
        create_test_clip('FrontDoor', 120, base_time),   # 2 minutes later
        create_test_clip('FrontDoor', 600, base_time),   # 10 minutes later (new group)
    ]

    groups = group_videos(clips, max_diff_seconds=300)  # 5 minute window

    print(f"\nInput: {len(clips)} clips from 1 camera")
    print(f"Result: {len(groups)} groups")

    assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
    assert len(groups[0]) == 3, f"Expected 3 clips in group 1, got {len(groups[0])}"
    assert len(groups[1]) == 1, f"Expected 1 clip in group 2, got {len(groups[1])}"

    print("✅ Single camera grouping passed")


def test_multi_camera_simultaneous():
    """Test grouping with simultaneous clips from multiple cameras."""
    print("\n" + "="*80)
    print("TEST 2: Multi-Camera Simultaneous Recording")
    print("="*80)

    base_time = datetime(2025, 10, 15, 10, 0, 0)
    clips = [
        # Event 1: All 3 cameras triggered at the same time
        create_test_clip('FrontDoor', 0, base_time),
        create_test_clip('Corner', 5, base_time),        # 5 seconds later
        create_test_clip('Backyard', 10, base_time),     # 10 seconds later

        # Event 2: 10 minutes later, only 2 cameras
        create_test_clip('FrontDoor', 600, base_time),
        create_test_clip('Corner', 605, base_time),
    ]

    groups = group_videos(clips, max_diff_seconds=60)  # 1 minute window

    print(f"\nInput: {len(clips)} clips from 3 cameras")
    print(f"Result: {len(groups)} groups")

    for i, group in enumerate(groups, 1):
        cameras = set(clip['camera'] for clip in group)
        print(f"  Group {i}: {len(group)} clips from cameras: {', '.join(sorted(cameras))}")

    assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
    assert len(groups[0]) == 3, f"Expected 3 clips in group 1, got {len(groups[0])}"
    assert len(groups[1]) == 2, f"Expected 2 clips in group 2, got {len(groups[1])}"

    # Verify multi-camera in first group
    cameras_group1 = set(clip['camera'] for clip in groups[0])
    assert len(cameras_group1) == 3, f"Expected 3 cameras in group 1, got {len(cameras_group1)}"

    print("✅ Multi-camera simultaneous grouping passed")


def test_partial_overlap():
    """Test grouping with partial overlap between cameras."""
    print("\n" + "="*80)
    print("TEST 3: Partial Overlap Between Cameras")
    print("="*80)

    base_time = datetime(2025, 10, 15, 10, 0, 0)
    clips = [
        # Camera 1 triggers first
        create_test_clip('FrontDoor', 0, base_time),

        # Camera 2 triggers 30 seconds later (within window)
        create_test_clip('Corner', 30, base_time),

        # Camera 3 triggers 100 seconds after start (outside window from start, but within from Camera 2)
        create_test_clip('Backyard', 100, base_time),
    ]

    groups = group_videos(clips, max_diff_seconds=90)  # 90 second window

    print(f"\nInput: {len(clips)} clips from 3 cameras with staggered start times")
    print(f"Result: {len(groups)} groups")

    for i, group in enumerate(groups, 1):
        cameras = set(clip['camera'] for clip in group)
        times = [clip['datetime'] for clip in group]
        duration = (max(times) - min(times)).total_seconds()
        print(f"  Group {i}: {len(group)} clips, {len(cameras)} cameras, spanning {duration}s")

    # All should be in one group since each subsequent clip is within window of previous
    assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
    assert len(groups[0]) == 3, f"Expected 3 clips in group 1, got {len(groups[0])}"

    print("✅ Partial overlap grouping passed")


def test_mixed_scenarios():
    """Test complex scenario with both multi-camera and single-camera events."""
    print("\n" + "="*80)
    print("TEST 4: Mixed Multi-Camera and Single-Camera Events")
    print("="*80)

    base_time = datetime(2025, 10, 15, 10, 0, 0)
    clips = [
        # Event 1: Multi-camera (3 cameras within 30 seconds)
        create_test_clip('FrontDoor', 0, base_time),
        create_test_clip('Corner', 10, base_time),
        create_test_clip('Backyard', 20, base_time),

        # Event 2: Single camera (5 minutes later)
        create_test_clip('FrontDoor', 300, base_time),

        # Event 3: Multi-camera again (10 minutes from start)
        create_test_clip('Corner', 600, base_time),
        create_test_clip('Backyard', 605, base_time),
    ]

    groups = group_videos(clips, max_diff_seconds=60)  # 1 minute window

    print(f"\nInput: {len(clips)} clips from 3 cameras")
    print(f"Result: {len(groups)} groups")

    for i, group in enumerate(groups, 1):
        cameras = set(clip['camera'] for clip in group)
        print(f"  Group {i}: {len(group)} clips from {len(cameras)} camera(s) - {', '.join(sorted(cameras))}")

    assert len(groups) == 3, f"Expected 3 groups, got {len(groups)}"
    assert len(set(clip['camera'] for clip in groups[0])) == 3, "Group 1 should have 3 cameras"
    assert len(set(clip['camera'] for clip in groups[1])) == 1, "Group 2 should have 1 camera"
    assert len(set(clip['camera'] for clip in groups[2])) == 2, "Group 3 should have 2 cameras"

    print("✅ Mixed scenario grouping passed")


def test_chronological_ordering():
    """Test that groups are ordered chronologically."""
    print("\n" + "="*80)
    print("TEST 5: Chronological Ordering of Groups")
    print("="*80)

    base_time = datetime(2025, 10, 15, 10, 0, 0)

    # Create clips in random order
    clips = [
        create_test_clip('Backyard', 600, base_time),    # Event 2
        create_test_clip('FrontDoor', 0, base_time),     # Event 1
        create_test_clip('Corner', 1200, base_time),     # Event 3
        create_test_clip('Corner', 5, base_time),        # Event 1
    ]

    groups = group_videos(clips, max_diff_seconds=60)

    print(f"\nInput: {len(clips)} clips in random order")
    print(f"Result: {len(groups)} groups")

    # Verify groups are chronologically ordered
    for i in range(len(groups) - 1):
        current_start = min(clip['datetime'] for clip in groups[i])
        next_start = min(clip['datetime'] for clip in groups[i+1])
        assert current_start < next_start, f"Groups not in chronological order: group {i} starts at {current_start}, group {i+1} starts at {next_start}"
        print(f"  Group {i+1} starts at {current_start.strftime('%H:%M:%S')}")

    print(f"  Group {len(groups)} starts at {min(clip['datetime'] for clip in groups[-1]).strftime('%H:%M:%S')}")
    print("✅ Chronological ordering passed")


def test_empty_input():
    """Test handling of empty input."""
    print("\n" + "="*80)
    print("TEST 6: Empty Input")
    print("="*80)

    groups = group_videos([], max_diff_seconds=60)

    print(f"\nInput: 0 clips")
    print(f"Result: {len(groups)} groups")

    assert len(groups) == 0, f"Expected 0 groups for empty input, got {len(groups)}"

    print("✅ Empty input handling passed")


if __name__ == '__main__':
    print("\n" + "="*80)
    print("MULTI-CAMERA GROUPING LOGIC TEST SUITE")
    print("="*80)

    try:
        test_single_camera_grouping()
        test_multi_camera_simultaneous()
        test_partial_overlap()
        test_mixed_scenarios()
        test_chronological_ordering()
        test_empty_input()

        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED!")
        print("="*80 + "\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        exit(1)
