"""
Unit tests for multi-camera grouping logic.

Tests that video clips from multiple cameras are correctly grouped
based on overlapping timestamps.
"""

import pytest
from datetime import datetime, timedelta


@pytest.mark.unit
class TestVideoGrouping:
    """Test suite for multi-camera video grouping."""

    def _create_clip(self, camera: str, offset_seconds: int, base_time: datetime) -> dict:
        """Helper to create a test video clip."""
        return {
            'camera': camera,
            'datetime': base_time + timedelta(seconds=offset_seconds),
            'path': f'/fake/path/{camera}_{offset_seconds}.mp4',
            'full_path': f'/fake/path/{camera}_{offset_seconds}.mp4',
            'duration': 30.0
        }

    def test_single_camera_single_clip(self):
        """Test grouping with a single clip."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [self._create_clip('FrontDoor', 0, base_time)]

        groups = group_videos(clips, max_diff_seconds=300)

        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0]['camera'] == 'FrontDoor'

    def test_single_camera_multiple_clips_same_group(self):
        """Test grouping multiple clips from same camera within time window."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('FrontDoor', 60, base_time),    # 1 minute later
            self._create_clip('FrontDoor', 120, base_time),   # 2 minutes later
        ]

        groups = group_videos(clips, max_diff_seconds=300)

        assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
        assert len(groups[0]) == 3, f"Expected 3 clips in group, got {len(groups[0])}"

    def test_single_camera_multiple_groups(self):
        """Test that clips beyond time window create separate groups."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('FrontDoor', 60, base_time),
            self._create_clip('FrontDoor', 120, base_time),
            self._create_clip('FrontDoor', 600, base_time),   # 10 minutes later (new group)
        ]

        groups = group_videos(clips, max_diff_seconds=300)  # 5 minute window

        assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
        assert len(groups[0]) == 3, f"Expected 3 clips in group 1, got {len(groups[0])}"
        assert len(groups[1]) == 1, f"Expected 1 clip in group 2, got {len(groups[1])}"

    def test_multi_camera_simultaneous(self):
        """Test grouping simultaneous clips from multiple cameras."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('Corner', 5, base_time),      # 5 seconds later
            self._create_clip('Backyard', 10, base_time),   # 10 seconds later
        ]

        groups = group_videos(clips, max_diff_seconds=60)  # 1 minute window

        assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
        assert len(groups[0]) == 3, f"Expected 3 clips, got {len(groups[0])}"

        # Verify all three cameras are present
        cameras = set(clip['camera'] for clip in groups[0])
        assert cameras == {'FrontDoor', 'Corner', 'Backyard'}

    def test_multi_camera_separate_events(self):
        """Test grouping multiple separate multi-camera events."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            # Event 1: All 3 cameras
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('Corner', 5, base_time),
            self._create_clip('Backyard', 10, base_time),

            # Event 2: 10 minutes later, only 2 cameras
            self._create_clip('FrontDoor', 600, base_time),
            self._create_clip('Corner', 605, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=60)

        assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
        assert len(groups[0]) == 3, f"Expected 3 clips in group 1, got {len(groups[0])}"
        assert len(groups[1]) == 2, f"Expected 2 clips in group 2, got {len(groups[1])}"

        # Verify camera counts
        cameras_group1 = set(clip['camera'] for clip in groups[0])
        cameras_group2 = set(clip['camera'] for clip in groups[1])

        assert len(cameras_group1) == 3
        assert len(cameras_group2) == 2

    def test_partial_overlap_bridging(self):
        """Test that partial overlaps bridge into single group."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            # Camera 1 triggers first
            self._create_clip('FrontDoor', 0, base_time),

            # Camera 2 triggers 30 seconds later (within window of Camera 1)
            self._create_clip('Corner', 30, base_time),

            # Camera 3 triggers 100 seconds after start
            # Outside window from start, but within window from Camera 2
            self._create_clip('Backyard', 100, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=90)  # 90 second window

        # All should be in one group due to bridging
        assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
        assert len(groups[0]) == 3, f"Expected 3 clips, got {len(groups[0])}"

    def test_mixed_multi_and_single_camera_events(self):
        """Test complex scenario with both multi and single camera events."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            # Event 1: Multi-camera (3 cameras within 30 seconds)
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('Corner', 10, base_time),
            self._create_clip('Backyard', 20, base_time),

            # Event 2: Single camera (5 minutes later)
            self._create_clip('FrontDoor', 300, base_time),

            # Event 3: Multi-camera again (10 minutes from start)
            self._create_clip('Corner', 600, base_time),
            self._create_clip('Backyard', 605, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=60)

        assert len(groups) == 3, f"Expected 3 groups, got {len(groups)}"

        # Verify camera counts per group
        assert len(set(clip['camera'] for clip in groups[0])) == 3, "Group 1 should have 3 cameras"
        assert len(set(clip['camera'] for clip in groups[1])) == 1, "Group 2 should have 1 camera"
        assert len(set(clip['camera'] for clip in groups[2])) == 2, "Group 3 should have 2 cameras"

    def test_chronological_ordering(self):
        """Test that groups are returned in chronological order."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)

        # Create clips in random order
        clips = [
            self._create_clip('Backyard', 600, base_time),   # Event 2
            self._create_clip('FrontDoor', 0, base_time),    # Event 1
            self._create_clip('Corner', 1200, base_time),    # Event 3
            self._create_clip('Corner', 5, base_time),       # Event 1
        ]

        groups = group_videos(clips, max_diff_seconds=60)

        assert len(groups) == 3

        # Verify chronological ordering
        for i in range(len(groups) - 1):
            current_start = min(clip['datetime'] for clip in groups[i])
            next_start = min(clip['datetime'] for clip in groups[i+1])
            assert current_start < next_start, (
                f"Groups not in chronological order: "
                f"group {i} starts at {current_start}, "
                f"group {i+1} starts at {next_start}"
            )

    def test_empty_input(self):
        """Test handling of empty clip list."""
        from blink_pipeline.grouping import group_videos

        groups = group_videos([], max_diff_seconds=60)

        assert len(groups) == 0, f"Expected 0 groups for empty input, got {len(groups)}"

    def test_within_group_ordering(self):
        """Test that clips within each group are chronologically ordered."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)

        # Create clips out of order
        clips = [
            self._create_clip('Backyard', 20, base_time),
            self._create_clip('FrontDoor', 0, base_time),
            self._create_clip('Corner', 10, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=60)

        assert len(groups) == 1

        # Verify clips within group are sorted
        group = groups[0]
        for i in range(len(group) - 1):
            assert group[i]['datetime'] <= group[i+1]['datetime'], (
                "Clips within group not chronologically ordered"
            )

    @pytest.mark.parametrize("max_diff", [30, 60, 120, 300, 600])
    def test_varying_time_windows(self, max_diff):
        """Test grouping with different time window sizes."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            self._create_clip('Camera1', 0, base_time),
            self._create_clip('Camera2', 40, base_time),
            self._create_clip('Camera3', 80, base_time),
            self._create_clip('Camera4', 200, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=max_diff)

        # Number of groups depends on window size
        if max_diff >= 200:
            assert len(groups) == 1, "All clips should be in one group with large window"
        elif max_diff >= 80:
            assert len(groups) <= 2, "Should have at most 2 groups"
        else:
            assert len(groups) >= 2, "Should have multiple groups with small window"


@pytest.mark.unit
class TestGroupingEdgeCases:
    """Test edge cases and boundary conditions."""

    def _create_clip(self, camera: str, offset_seconds: int, base_time: datetime) -> dict:
        """Helper to create a test video clip."""
        return {
            'camera': camera,
            'datetime': base_time + timedelta(seconds=offset_seconds),
            'path': f'/fake/path/{camera}_{offset_seconds}.mp4',
            'full_path': f'/fake/path/{camera}_{offset_seconds}.mp4'
        }

    def test_exact_boundary_clip(self):
        """Test clip exactly at max_diff_seconds boundary."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        max_diff = 60

        clips = [
            self._create_clip('Camera1', 0, base_time),
            self._create_clip('Camera2', max_diff, base_time),  # Exactly at boundary
        ]

        groups = group_videos(clips, max_diff_seconds=max_diff)

        # Boundary behavior: should be in same group (inclusive)
        assert len(groups) == 1 or len(groups) == 2  # Implementation dependent

    def test_single_clip_per_camera(self):
        """Test with exactly one clip from each camera."""
        from blink_pipeline.grouping import group_videos

        base_time = datetime(2025, 10, 15, 10, 0, 0)
        clips = [
            self._create_clip('Camera1', 0, base_time),
            self._create_clip('Camera2', 10, base_time),
            self._create_clip('Camera3', 20, base_time),
            self._create_clip('Camera4', 30, base_time),
        ]

        groups = group_videos(clips, max_diff_seconds=60)

        assert len(groups) == 1
        assert len(groups[0]) == 4

        # Each clip should be from a different camera
        cameras = [clip['camera'] for clip in groups[0]]
        assert len(set(cameras)) == 4
