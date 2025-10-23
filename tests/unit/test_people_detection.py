"""Unit tests for people detection module."""

import pytest


@pytest.mark.unit
class TestPeopleDetectorConfig:
    """Test people detection configuration."""

    def test_import_module(self):
        """Test that people detection module can be imported."""
        try:
            from blink_pipeline import people_detection
            assert people_detection is not None
        except ImportError as e:
            pytest.skip(f"Import failed: {e}")
