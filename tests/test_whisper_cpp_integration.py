"""
Unit tests for whisper.cpp integration.

Tests GGML model detection, wrapper initialization, and config parsing.
"""

import pytest
from pathlib import Path


@pytest.mark.unit
class TestGGMLModelDetection:
    """Test GGML model file detection."""

    @pytest.mark.parametrize("model_path,expected", [
        ("/path/to/ggml-base.en.bin", True),
        ("/path/to/ggml-custom.bin", True),
        ("models/ggml-model.bin", True),
        ("/path/to/ggml-base.en.mlmodelc", True),
        ("/path/to/ggml-base.en.mlpackage", True),
        ("small", False),
        ("base.en", False),
        ("/path/to/model.pt", False),
        ("", False),
        (None, False),
    ])
    def test_is_ggml_model(self, model_path, expected):
        """Test GGML model path detection."""
        from blink_pipeline.whisper_cpp_wrapper import is_ggml_model

        result = is_ggml_model(model_path)
        assert result == expected, f"is_ggml_model('{model_path}') = {result}, expected {expected}"


@pytest.mark.unit
class TestWhisperCppWrapper:
    """Test whisper.cpp wrapper functionality."""

    def test_wrapper_missing_model_file(self):
        """Test that wrapper raises FileNotFoundError for missing model."""
        from blink_pipeline.whisper_cpp_wrapper import WhisperCppWrapper

        with pytest.raises(FileNotFoundError):
            WhisperCppWrapper(
                model_path="/nonexistent/model.bin",
                whisper_cpp_binary="/nonexistent/binary"
            )

    def test_wrapper_missing_binary(self):
        """Test that wrapper raises FileNotFoundError for missing binary."""
        from blink_pipeline.whisper_cpp_wrapper import WhisperCppWrapper

        with pytest.raises(FileNotFoundError):
            WhisperCppWrapper(
                model_path="/nonexistent/model.bin",
                whisper_cpp_binary=None
            )


@pytest.mark.unit
class TestTimestampParsing:
    """Test timestamp string parsing for whisper output."""

    @pytest.mark.parametrize("timestamp_str,expected", [
        ("00:00:03.450", 3.45),
        ("00:01:30.000", 90.0),
        ("01:00:00.000", 3600.0),
        ("0:03.5", 3.5),
        ("10.5", 10.5),
        ("00:00:00.000", 0.0),
        ("00:00:00.001", 0.001),
    ])
    def test_parse_timestamp(self, timestamp_str, expected):
        """Test parsing various timestamp formats."""
        from blink_pipeline.transcription import _WhisperTranscriber

        result = _WhisperTranscriber._parse_timestamp(timestamp_str)

        # Allow small floating point error
        assert abs(result - expected) < 0.01, (
            f"parse_timestamp('{timestamp_str}') = {result:.3f}, expected {expected:.3f}"
        )


@pytest.mark.unit
class TestWhisperConfigParsing:
    """Test whisper configuration parsing."""

    def test_parse_standard_model_config(self):
        """Test parsing standard model configuration."""
        from blink_pipeline.transcription import _parse_whisper_settings

        config = {
            "model_name": "small",
            "device": "cpu",
            "language": "en",
            "beam_size": 5
        }

        settings = _parse_whisper_settings(config)

        assert settings.model_name == "small"
        assert settings.device == "cpu"
        assert settings.language == "en"
        assert settings.beam_size == 5

    def test_parse_ggml_model_config(self):
        """Test parsing GGML model configuration."""
        from blink_pipeline.transcription import _parse_whisper_settings

        config = {
            "ggml_model_path": "/path/to/ggml-custom.bin",
            "whisper_cpp_binary": "/usr/local/bin/whisper-cli",
            "device": "auto",
        }

        settings = _parse_whisper_settings(config)

        assert settings.ggml_model_path == "/path/to/ggml-custom.bin"
        assert settings.whisper_cpp_binary == "/usr/local/bin/whisper-cli"
        # "auto" is resolved to actual device (cpu or cuda) depending on availability
        assert settings.device in ["cpu", "cuda"]

    def test_parse_coreml_model_config(self):
        """Test parsing Core ML model configuration."""
        from blink_pipeline.transcription import _parse_whisper_settings

        config = {
            "ggml_model_path": "/path/to/coreml-encoder-base.en.mlmodelc",
            "whisper_cpp_binary": "/usr/local/bin/whisper-cli",
            "device": "coreml",
        }

        settings = _parse_whisper_settings(config)

        assert settings.ggml_model_path == "/path/to/coreml-encoder-base.en.mlmodelc"
        assert settings.device == "coreml"

    @pytest.mark.skip(reason="WhisperSettings doesn't have prefer_whisper_cpp attribute; selection logic is elsewhere")
    def test_parse_prefer_whisper_cpp(self):
        """Test prefer_whisper_cpp configuration flag.

        Note: The preference for whisper.cpp vs standard whisper is determined by checking
        if ggml_model_path and whisper_cpp_binary are set, not by a dedicated flag.
        """
        pass

    def test_parse_default_values(self):
        """Test that default values are applied when not specified."""
        from blink_pipeline.transcription import _parse_whisper_settings

        config = {
            "model_name": "base"
        }

        settings = _parse_whisper_settings(config)

        # Should have sensible defaults
        assert settings.model_name == "base"
        assert settings.beam_size is not None
        assert settings.temperature is not None
