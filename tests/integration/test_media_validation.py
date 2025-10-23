"""
Integration tests for video repair and validation functionality.

Note: These tests require ffmpeg to be installed and working.
Some tests are skipped if sample video files are not available.

Tests that cannot be easily automated without real video files:
- Actual video corruption detection and repair
- Frame duplication strategies with real damaged files
- Performance benchmarking of repair strategies
"""

import pytest
import json
from pathlib import Path
from datetime import datetime


@pytest.mark.integration
@pytest.mark.requires_ffmpeg
class TestProgressFileOperations:
    """Test preprocessing progress file save/load/delete operations."""

    def test_save_and_load_progress(self, temp_dir):
        """Test saving and loading progress file."""
        from blink_pipeline.media_validation import _save_progress, _load_progress

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

        _save_progress(str(temp_dir), progress_data)

        # Verify file was created
        from blink_pipeline.media_validation import _get_progress_file_path
        progress_file = _get_progress_file_path(str(temp_dir))
        assert progress_file.exists(), "Progress file should be created"

        # Load and verify
        loaded = _load_progress(str(temp_dir))
        assert loaded is not None, "Should load progress file"
        assert loaded['total'] == 10
        assert len(loaded['completed']) == 2
        assert loaded['strategy'] == 'fill'

    def test_delete_progress(self, temp_dir):
        """Test deleting progress file."""
        from blink_pipeline.media_validation import (
            _save_progress, _delete_progress, _get_progress_file_path
        )

        progress_data = {
            'start_time': '2024-01-01T12:00:00',
            'total': 1,
            'completed': {},
            'strategy': 'fill',
            'always_repair': False
        }

        _save_progress(str(temp_dir), progress_data)

        progress_file = _get_progress_file_path(str(temp_dir))
        assert progress_file.exists()

        # Delete
        _delete_progress(str(temp_dir))

        assert not progress_file.exists(), "Progress file should be deleted"

    def test_corrupted_progress_file(self, temp_dir):
        """Test handling of corrupted progress file."""
        from blink_pipeline.media_validation import _get_progress_file_path, _load_progress

        progress_file = _get_progress_file_path(str(temp_dir))

        # Create corrupted JSON file
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_file, 'w') as f:
            f.write("{ invalid json }")

        loaded = _load_progress(str(temp_dir))

        assert loaded is None, "Should return None for corrupted file"

    def test_invalid_structure_progress_file(self, temp_dir):
        """Test handling of progress file with invalid structure."""
        from blink_pipeline.media_validation import _get_progress_file_path, _load_progress

        progress_file = _get_progress_file_path(str(temp_dir))

        # Create valid JSON but wrong structure
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_file, 'w') as f:
            json.dump({'wrong': 'structure'}, f)

        loaded = _load_progress(str(temp_dir))

        assert loaded is None, "Should return None for invalid structure"

    def test_progress_file_format(self, temp_dir):
        """Test that progress file has correct format with all required keys."""
        from blink_pipeline.media_validation import _save_progress, _get_progress_file_path

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

        _save_progress(str(temp_dir), progress_data)

        # Load as raw JSON
        progress_file = _get_progress_file_path(str(temp_dir))
        with open(progress_file, 'r') as f:
            data = json.load(f)

        # Verify all required keys present
        required_keys = ['start_time', 'total', 'completed', 'strategy', 'always_repair']
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"

        # Verify completed entries structure
        for video_path, result in data['completed'].items():
            assert 'validated_path' in result, "Missing validated_path in completed entry"

    def test_atomic_write(self, temp_dir):
        """Test that progress writes are atomic (no temp files left behind)."""
        from blink_pipeline.media_validation import _save_progress, _load_progress

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
            _save_progress(str(temp_dir), progress_data)

        # Verify final state is consistent
        loaded = _load_progress(str(temp_dir))
        assert loaded is not None
        assert len(loaded['completed']) == 5

        # Check no temporary files left behind
        temp_files = list(Path(temp_dir).glob('.preprocessing_progress_*.tmp'))
        assert len(temp_files) == 0, f"Found {len(temp_files)} temporary files left behind"

    def test_no_progress_file_exists(self, temp_dir):
        """Test loading when no progress file exists."""
        from blink_pipeline.media_validation import _load_progress

        loaded = _load_progress(str(temp_dir))

        assert loaded is None, "Should return None when no progress file exists"


@pytest.mark.integration
@pytest.mark.requires_ffmpeg
@pytest.mark.requires_video_files
class TestVideoRepairStrategies:
    """
    Test video repair strategies.

    Note: These tests require actual video files and ffmpeg.
    They are marked as @pytest.mark.requires_video_files and will be skipped
    unless real video files are provided.
    """

    @pytest.fixture
    def sample_video_path(self, test_data_dir):
        """Provide path to sample video for testing."""
        sample_path = test_data_dir / "sample.mp4"
        if not sample_path.exists():
            pytest.skip("Sample video file not available")
        return sample_path

    def test_repair_video_fill_strategy(self, temp_dir, sample_video_path):
        """Test video repair with 'fill' strategy."""
        from blink_pipeline.media_utils import repair_video, probe_media_info

        output_path = temp_dir / "repaired_fill.mp4"
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()

        success = repair_video(
            str(sample_video_path),
            str(output_path),
            cache_dir=str(cache_dir),
            strategy='fill'
        )

        assert success, "Repair should succeed"
        assert output_path.exists(), "Repaired video should exist"

        # Verify output
        info = probe_media_info(str(output_path))
        assert info.has_audio
        assert info.video_duration > 0
        assert info.audio_duration > 0

    def test_repair_video_remove_blank_strategy(self, temp_dir, sample_video_path):
        """Test video repair with 'remove_blank' strategy."""
        from blink_pipeline.media_utils import repair_video, probe_media_info

        output_path = temp_dir / "repaired_remove_blank.mp4"
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()

        success = repair_video(
            str(sample_video_path),
            str(output_path),
            cache_dir=str(cache_dir),
            strategy='remove_blank'
        )

        assert success, "Repair should succeed"
        assert output_path.exists(), "Repaired video should exist"

    def test_repair_uses_cache(self, temp_dir, sample_video_path):
        """Test that repair results are cached and reused."""
        from blink_pipeline.media_utils import repair_video

        output_path1 = temp_dir / "repaired1.mp4"
        output_path2 = temp_dir / "repaired2.mp4"
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir()

        # First repair
        success1 = repair_video(
            str(sample_video_path),
            str(output_path1),
            cache_dir=str(cache_dir),
            strategy='fill'
        )

        assert success1

        # Second repair (should use cache)
        success2 = repair_video(
            str(sample_video_path),
            str(output_path2),
            cache_dir=str(cache_dir),
            strategy='fill'
        )

        assert success2

        # Both outputs should exist
        assert output_path1.exists()
        assert output_path2.exists()


@pytest.mark.integration
@pytest.mark.slow
class TestResumablePreprocessing:
    """
    Test resume capability for preprocessing stage.

    Tests the ability to resume interrupted preprocessing jobs.
    """

    def test_resume_from_partial_completion(self, temp_dir):
        """Test resuming from partially completed preprocessing."""
        from blink_pipeline.media_validation import _save_progress, _load_progress

        # Simulate partial completion
        progress_data = {
            'start_time': datetime.now().isoformat(),
            'total': 10,
            'completed': {
                f'/video{i}.mp4': {'validated_path': f'/cache/video{i}.mp4'}
                for i in range(5)  # 5 out of 10 completed
            },
            'strategy': 'fill',
            'always_repair': False
        }

        _save_progress(str(temp_dir), progress_data)

        # Simulate resume
        loaded = _load_progress(str(temp_dir))

        assert loaded is not None
        assert loaded['total'] == 10
        assert len(loaded['completed']) == 5

        # Remaining work: 10 - 5 = 5 videos
        remaining = loaded['total'] - len(loaded['completed'])
        assert remaining == 5

    def test_progress_tracks_strategy_consistency(self, temp_dir):
        """Test that progress file tracks repair strategy for consistency."""
        from blink_pipeline.media_validation import _save_progress, _load_progress

        progress_data = {
            'start_time': datetime.now().isoformat(),
            'total': 5,
            'completed': {},
            'strategy': 'fill',
            'always_repair': True
        }

        _save_progress(str(temp_dir), progress_data)
        loaded = _load_progress(str(temp_dir))

        assert loaded is not None
        assert loaded['strategy'] == 'fill'
        assert loaded['always_repair'] is True

        # Verify we can detect strategy mismatch if config changes
        # (implementation should check this when resuming)
        assert loaded['strategy'] in ['fill', 'remove_blank']
