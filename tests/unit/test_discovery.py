"""
Unit tests for video discovery and filename parsing.

Tests the regex patterns and date parsing logic used for discovering video files.
"""

import pytest
import re
from datetime import datetime


@pytest.mark.unit
class TestFilenameRegexPattern:
    """Test filename regex pattern matching."""

    @pytest.fixture
    def filename_pattern(self):
        """Provide the filename regex pattern."""
        return r'(\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4'

    @pytest.fixture
    def filename_re(self, filename_pattern):
        """Compile the filename regex."""
        return re.compile(filename_pattern)

    @pytest.mark.parametrize("filename,should_match,expected_time,expected_camera", [
        ("08-37-43_CornerG8T1K0013255014P_081.mp4", True, "08-37-43", "Corner"),
        ("14-22-15_FrontDoorG1234567890ABC_001.mp4", True, "14-22-15", "FrontDoor"),
        ("23-59-59_BackyardG9876543210XYZ_999.mp4", True, "23-59-59", "Backyard"),
        ("00-00-01_GarageG1A2B3C4D5E_042.mp4", True, "00-00-01", "Garage"),
        ("12-30-45_CameraG123_test.mp4", True, "12-30-45", "Camera"),
        # Invalid patterns
        ("not_a_match.mp4", False, None, None),
        ("08-37_CornerG123.mp4", False, None, None),  # Missing seconds
        ("08-37-43_Corner_123.mp4", False, None, None),  # Missing 'G' prefix
        ("08-37-43_CornerG123.avi", False, None, None),  # Wrong extension
    ])
    def test_filename_matching(
        self, filename_re, filename, should_match, expected_time, expected_camera
    ):
        """Test filename pattern matching with various inputs."""
        match = filename_re.match(filename)

        if should_match:
            assert match is not None, f"Expected match for: {filename}"
            timestamp, camera = match.groups()
            assert timestamp == expected_time, f"Expected time {expected_time}, got {timestamp}"
            assert camera == expected_camera, f"Expected camera {expected_camera}, got {camera}"
        else:
            assert match is None, f"Expected no match for: {filename}"


@pytest.mark.unit
class TestDateFolderParsing:
    """Test date folder parsing with various formats."""

    @pytest.fixture
    def date_patterns(self):
        """Provide date folder patterns."""
        return [
            '%Y-%m-%d',   # 2025-10-19
            '%Y%m%d',     # 20251019
            '%Y_%m_%d',   # 2025_10_19
            '%y-%m-%d',   # 25-10-19
            '%y%m%d',     # 251019
            '%y_%m_%d',   # 25_10_19
            '%m-%d-%Y',   # 10-19-2025
            '%d-%m-%Y',   # 19-10-2025
        ]

    @pytest.mark.parametrize("folder_name,expected_date", [
        ("2025-10-19", datetime(2025, 10, 19)),
        ("20251019", datetime(2025, 10, 19)),
        ("2025_10_19", datetime(2025, 10, 19)),
        ("25-10-19", datetime(2025, 10, 19)),
        ("10-19-2025", datetime(2025, 10, 19)),
        ("19-10-2025", datetime(2025, 10, 19)),
    ])
    def test_parse_date_folders(self, date_patterns, folder_name, expected_date):
        """Test parsing various date folder formats."""
        parsed = None

        for pattern in date_patterns:
            try:
                parsed = datetime.strptime(folder_name, pattern)
                break
            except ValueError:
                continue

        assert parsed is not None, f"Failed to parse folder: {folder_name}"
        assert parsed.date() == expected_date.date(), (
            f"Parsed {folder_name} as {parsed.date()}, expected {expected_date.date()}"
        )

    def test_invalid_date_folder(self, date_patterns):
        """Test that invalid date folders fail gracefully."""
        invalid_folder = "not-a-date"

        parsed = None
        for pattern in date_patterns:
            try:
                parsed = datetime.strptime(invalid_folder, pattern)
                break
            except ValueError:
                continue

        assert parsed is None, f"Should not parse invalid folder: {invalid_folder}"


@pytest.mark.unit
class TestDiscoveryIntegration:
    """Test complete discovery workflow."""

    def test_full_filename_to_datetime(self):
        """Test converting filename and folder to complete datetime."""
        # Simulate discovery result
        folder = "2025-10-19"
        filename = "08-37-43_CornerG8T1K0013255014P_081.mp4"

        # Parse folder date
        folder_date = datetime.strptime(folder, '%Y-%m-%d')

        # Parse filename time
        pattern = r'(\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4'
        match = re.match(pattern, filename)
        assert match is not None

        time_str, camera = match.groups()
        hour, minute, second = map(int, time_str.split('-'))

        # Combine
        full_datetime = folder_date.replace(
            hour=hour,
            minute=minute,
            second=second
        )

        expected = datetime(2025, 10, 19, 8, 37, 43)
        assert full_datetime == expected
        assert camera == "Corner"

    def test_discovery_with_real_discovery_module(self, tmp_path):
        """Test that the actual discovery module can be imported and has expected interface."""
        from blink_pipeline.discovery import discover_files

        # Basic smoke test - module should import
        assert callable(discover_files)
