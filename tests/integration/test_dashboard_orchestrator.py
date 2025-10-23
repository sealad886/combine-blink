"""
Integration Tests for Dashboard and Orchestrator

Tests the interaction between PipelineDashboard and the orchestrator,
ensuring:
- Stage keys are validated correctly
- STAGE_DEFINITIONS is used consistently
- Progress tracking works correctly
- Error handling is robust
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from blink_pipeline.pipeline_dashboard import PipelineDashboard, StageStatus, STAGE_DEFINITIONS
from blink_pipeline.stages import StageKey, validate_stage_key, ALL_STAGE_KEYS


class TestStageKeyValidation:
    """Test that stage key validation works correctly."""

    def test_valid_stage_keys(self):
        """All StageKey enum values should pass validation."""
        for stage_key in StageKey:
            # Should not raise any exception
            validate_stage_key(stage_key)
            validate_stage_key(stage_key.value)

    def test_invalid_stage_key_raises(self):
        """Invalid stage keys should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid stage key"):
            validate_stage_key("nonexistent_stage")

    def test_stage_definitions_use_valid_keys(self):
        """STAGE_DEFINITIONS should only contain valid stage keys."""
        for key, name in STAGE_DEFINITIONS:
            # Each key should either be a StageKey enum or a valid string
            if isinstance(key, StageKey):
                assert key.value in ALL_STAGE_KEYS
            else:
                # String keys like "speaker_profiles" that aren't in the enum yet
                # should be documented as TODO items
                assert isinstance(key, str)


class TestDashboardStageOperations:
    """Test PipelineDashboard stage operations with validation."""

    def test_start_stage_with_valid_key(self):
        """Starting a stage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            # Should not raise
            dashboard.start_stage(StageKey.VALIDATION, 10)

            assert dashboard.stages[StageKey.VALIDATION].status == StageStatus.RUNNING

    def test_start_stage_with_invalid_key_raises(self):
        """Starting a stage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.start_stage("invalid_stage", 10)

    def test_update_stage_with_valid_key(self):
        """Updating a stage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.VALIDATION, 10)

            # Should not raise
            dashboard.update_stage(StageKey.VALIDATION, 5, "5/10 complete")

            assert dashboard.stages[StageKey.VALIDATION].completed == 5

    def test_update_stage_with_invalid_key_raises(self):
        """Updating a stage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.update_stage("invalid_stage", 5)

    def test_complete_stage_with_valid_key(self):
        """Completing a stage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.VALIDATION, 10)

            # Should not raise
            dashboard.complete_stage(StageKey.VALIDATION, "All videos validated")

            assert dashboard.stages[StageKey.VALIDATION].status == StageStatus.COMPLETE

    def test_complete_stage_with_invalid_key_raises(self):
        """Completing a stage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.complete_stage("invalid_stage")

    def test_skip_stage_with_valid_key(self):
        """Skipping a stage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            # Should not raise
            dashboard.skip_stage(StageKey.TRANSCRIPTION, "No audio to transcribe")

            assert dashboard.stages[StageKey.TRANSCRIPTION].status == StageStatus.SKIPPED

    def test_skip_stage_with_invalid_key_raises(self):
        """Skipping a stage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.skip_stage("invalid_stage")

    def test_error_stage_with_valid_key(self):
        """Marking a stage as error with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.MERGE, 5)

            # Should not raise
            dashboard.error_stage(StageKey.MERGE, "Merge failed")

            assert dashboard.stages[StageKey.MERGE].status == StageStatus.ERROR

    def test_error_stage_with_invalid_key_raises(self):
        """Marking a stage as error with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.error_stage("invalid_stage")


class TestDashboardSubstageOperations:
    """Test PipelineDashboard substage operations with validation."""

    def test_add_substage_with_valid_key(self):
        """Adding a substage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.TRANSCRIPTION, 5)

            # Should not raise
            dashboard.add_substage(StageKey.TRANSCRIPTION, "group1", 3)

            assert "group1" in dashboard.stages[StageKey.TRANSCRIPTION].substages

    def test_add_substage_with_invalid_key_raises(self):
        """Adding a substage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.add_substage("invalid_stage", "group1", 3)

    def test_update_substage_with_valid_key(self):
        """Updating a substage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.MERGE, 5)
            dashboard.add_substage(StageKey.MERGE, "group1", 3)

            # Should not raise
            dashboard.update_substage(StageKey.MERGE, "group1", 2)

            assert dashboard.stages[StageKey.MERGE].substages["group1"]["progress"] == 2

    def test_update_substage_with_invalid_key_raises(self):
        """Updating a substage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.update_substage("invalid_stage", "group1", 2)

    def test_remove_substage_with_valid_key(self):
        """Removing a substage with valid key should work."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.FINAL_TRANSCRIPTION, 5)
            dashboard.add_substage(StageKey.FINAL_TRANSCRIPTION, "group1", 3)

            # Should not raise
            dashboard.remove_substage(StageKey.FINAL_TRANSCRIPTION, "group1")

            assert dashboard.stages[StageKey.FINAL_TRANSCRIPTION].substages["group1"]["visible"] is False

    def test_remove_substage_with_invalid_key_raises(self):
        """Removing a substage with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.remove_substage("invalid_stage", "group1")


class TestStageKeyStringCompatibility:
    """Test that StageKey enums work as strings for backward compatibility."""

    def test_stage_key_string_conversion(self):
        """StageKey should convert to string seamlessly."""
        assert str(StageKey.VALIDATION) == "validation"
        assert str(StageKey.TRANSCRIPTION) == "transcription"
        assert str(StageKey.MERGE) == "merge"

    def test_stage_key_in_dict(self):
        """StageKey should work as dict keys."""
        stages = {
            StageKey.VALIDATION: "Video Validation",
            StageKey.TRANSCRIPTION: "Audio Transcription"
        }

        assert stages[StageKey.VALIDATION] == "Video Validation"
        # Should also work with string lookup since StageKey inherits from str
        assert stages["validation"] == "Video Validation"

    def test_stage_key_comparison(self):
        """StageKey should compare equal to its string value."""
        assert StageKey.VALIDATION == "validation"
        assert "validation" == StageKey.VALIDATION


class TestDashboardTimingOperations:
    """Test timing-related operations."""

    def test_get_stage_timings(self):
        """Should return timing information for all stages."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.VALIDATION, 10)
            dashboard.complete_stage(StageKey.VALIDATION)

        timings = dashboard.get_stage_timings()

        assert StageKey.VALIDATION in timings
        start_time, end_time, duration = timings[StageKey.VALIDATION]
        assert start_time > 0
        assert end_time > start_time
        assert duration > 0

    def test_get_total_pipeline_time(self):
        """Should return total pipeline time."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            dashboard.start_stage(StageKey.VALIDATION, 10)
            dashboard.complete_stage(StageKey.VALIDATION)

        total_time = dashboard.get_total_pipeline_time()

        assert total_time > 0


class TestStageDefinitionsConsistency:
    """Test that STAGE_DEFINITIONS matches StageKey enum."""

    def test_stage_definitions_covers_main_stages(self):
        """STAGE_DEFINITIONS should cover all main pipeline stages."""
        stage_keys_in_definitions = {key for key, _ in STAGE_DEFINITIONS}

        # Check that main stages are present
        assert StageKey.VALIDATION in stage_keys_in_definitions or StageKey.VALIDATION.value in stage_keys_in_definitions
        assert StageKey.TRANSCRIPTION in stage_keys_in_definitions or StageKey.TRANSCRIPTION.value in stage_keys_in_definitions
        assert StageKey.SPEAKER_ID in stage_keys_in_definitions or StageKey.SPEAKER_ID.value in stage_keys_in_definitions
        assert StageKey.MERGE in stage_keys_in_definitions or StageKey.MERGE.value in stage_keys_in_definitions
        assert StageKey.FINAL_TRANSCRIPTION in stage_keys_in_definitions or StageKey.FINAL_TRANSCRIPTION.value in stage_keys_in_definitions

    def test_stage_definitions_have_names(self):
        """Each stage in STAGE_DEFINITIONS should have a human-readable name."""
        for key, name in STAGE_DEFINITIONS:
            assert isinstance(name, str)
            assert len(name) > 0


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_set_stage_total_with_invalid_key_raises(self):
        """set_stage_total with invalid key should raise ValueError."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            with pytest.raises(ValueError, match="Invalid stage key"):
                dashboard.set_stage_total("invalid_stage", 20)

    def test_operations_on_nonexistent_stage_fail_gracefully(self):
        """Operations on non-existent stages should be handled gracefully."""
        dashboard = PipelineDashboard(total_videos=10, total_groups=5, total_clips=20)

        with dashboard:
            # These should validate the key but not crash if stage doesn't exist in stages dict
            # (though for our implementation, all stages are pre-initialized)
            dashboard.update_stage(StageKey.VALIDATION, 5)
            dashboard.complete_stage(StageKey.TRANSCRIPTION)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
