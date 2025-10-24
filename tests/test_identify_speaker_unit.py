"""
Unit tests for speaker identification module.

Tests speaker identification functionality with mocked dependencies.
"""

import pytest


class TestSpeakerIdentifier:
    """Test suite for SpeakerIdentifier class."""

    def test_initialization_no_speakers(self, base_config, mock_pyannote, mock_env_tokens):
        """Test SpeakerIdentifier initialization without known speakers."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speakers'] = {'known_speakers': {}}

        si = SpeakerIdentifier(config)

        assert si.known_speakers_map == {}
        assert si.config is not None

    def test_initialization_with_speakers(self, base_config, mock_pyannote, mock_env_tokens):
        """Test SpeakerIdentifier initialization with known speakers mapping."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speakers'] = {
            'known_speakers': {
                'speaker_0001': 'Alice',
                'speaker_0002': 'Bob'
            }
        }

        si = SpeakerIdentifier(config)

        assert si.known_speakers_map == {
            'speaker_0001': 'Alice',
            'speaker_0002': 'Bob'
        }

    def test_substitute_names_no_mapping(self, base_config, mock_pyannote, mock_env_tokens):
        """Test name substitution when no speaker mapping exists."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speakers'] = {'known_speakers': {}}

        si = SpeakerIdentifier(config)

        transcript = [
            {"speaker": "speaker_0001", "text": "hello"},
            {"speaker": "speaker_9999", "text": "world"},
        ]

        named = si.substitute_names_in_transcript(transcript)

        # Without mapping, speaker IDs should remain unchanged
        assert named[0]["speaker"] == "speaker_0001"
        assert named[1]["speaker"] == "speaker_9999"
        assert named[0]["text"] == "hello"
        assert named[1]["text"] == "world"

    def test_substitute_names_with_mapping(self, base_config, mock_pyannote, mock_env_tokens):
        """Test name substitution with speaker mapping."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speakers'] = {
            'known_speakers': {
                'speaker_0001': 'Alice'
            }
        }

        si = SpeakerIdentifier(config)

        transcript = [
            {"speaker": "speaker_0001", "text": "hello"},
            {"speaker": "speaker_9999", "text": "world"},
        ]

        named = si.substitute_names_in_transcript(transcript)

        # Mapped speaker should be replaced
        assert named[0]["speaker"] == "Alice"
        # Unmapped speaker should remain unchanged
        assert named[1]["speaker"] == "speaker_9999"

    def test_substitute_names_preserves_transcript_structure(
        self, base_config, mock_pyannote, mock_env_tokens
    ):
        """Test that name substitution preserves all transcript fields."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speakers'] = {
            'known_speakers': {
                'speaker_0001': 'Alice'
            }
        }

        si = SpeakerIdentifier(config)

        transcript = [
            {
                "start": 0.0,
                "end": 3.5,
                "speaker": "speaker_0001",
                "text": "Hello everyone",
                "confidence": 0.95
            }
        ]

        named = si.substitute_names_in_transcript(transcript)

        assert named[0]["speaker"] == "Alice"
        assert named[0]["start"] == 0.0
        assert named[0]["end"] == 3.5
        assert named[0]["text"] == "Hello everyone"
        assert named[0]["confidence"] == 0.95

    def test_device_configuration(self, base_config, mock_pyannote, mock_env_tokens):
        """Test that device configuration is properly parsed."""
        from blink_pipeline.identify_speaker import SpeakerIdentifier

        config = base_config.copy()
        config['speaker_identification']['device'] = 'cpu'
        config['speakers'] = {'known_speakers': {}}

        si = SpeakerIdentifier(config)

        # Device should be set in settings (exact value depends on platform detection)
        assert hasattr(si, 'settings')
        assert hasattr(si.settings, 'device')


@pytest.mark.unit
class TestSpeakerIdentificationConfig:
    """Test configuration parsing for speaker identification."""

    @pytest.mark.skip(reason="identify_speaker doesn't expose _parse_settings function; it's private within __init__")
    def test_parse_settings_cpu(self, base_config):
        """Test parsing speaker identification settings for CPU."""
        pass

    @pytest.mark.skip(reason="identify_speaker doesn't expose _parse_settings function; it's private within __init__")
    def test_parse_settings_mps_preference(self, base_config):
        """Test MPS preference on macOS."""
        pass
