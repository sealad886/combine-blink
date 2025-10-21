"""
Test script for whisper.cpp integration.

This validates that the GGML model wrapper works correctly
and produces output compatible with the transcription pipeline.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.whisper_cpp_wrapper import WhisperCppWrapper, is_ggml_model


def test_ggml_detection():
    """Test GGML model file detection."""
    print("\n=== Testing GGML Model Detection ===")

    test_cases = [
        ("/path/to/ggml-base.en.bin", True),
        ("/path/to/ggml-custom.bin", True),
        ("models/ggml-model.bin", True),
        ("small", False),
        ("base.en", False),
        ("/path/to/model.pt", False),
        ("", False),
    ]

    for model_path, expected in test_cases:
        result = is_ggml_model(model_path)
        status = "✓" if result == expected else "✗"
        print(f"{status} is_ggml_model('{model_path}') = {result} (expected {expected})")
        if result != expected:
            raise AssertionError(f"GGML detection failed for {model_path}")

    print("✓ All GGML detection tests passed!\n")


def test_wrapper_initialization():
    """Test whisper.cpp wrapper initialization."""
    print("=== Testing Wrapper Initialization ===")

    # Test with non-existent model (should fail gracefully)
    try:
        wrapper = WhisperCppWrapper(
            model_path="/nonexistent/model.bin",
            whisper_cpp_binary="/nonexistent/binary"
        )
        print("✗ Should have raised FileNotFoundError for missing model")
        raise AssertionError("Missing model check failed")
    except FileNotFoundError as e:
        print(f"✓ Correctly raised FileNotFoundError: {e}")

    print("✓ Wrapper initialization tests passed!\n")


def test_timestamp_parsing():
    """Test timestamp string parsing."""
    print("=== Testing Timestamp Parsing ===")

    from src.transcription import _WhisperTranscriber

    test_cases = [
        ("00:00:03.450", 3.45),
        ("00:01:30.000", 90.0),
        ("01:00:00.000", 3600.0),
        ("0:03.5", 3.5),
        ("10.5", 10.5),
    ]

    for timestamp_str, expected in test_cases:
        result = _WhisperTranscriber._parse_timestamp(timestamp_str)
        status = "✓" if abs(result - expected) < 0.01 else "✗"
        print(f"{status} parse_timestamp('{timestamp_str}') = {result:.2f} (expected {expected:.2f})")
        if abs(result - expected) >= 0.01:
            raise AssertionError(f"Timestamp parsing failed for {timestamp_str}")

    print("✓ All timestamp parsing tests passed!\n")


def test_integration_with_config():
    """Test integration with config parsing."""
    print("=== Testing Config Integration ===")

    from src.transcription import _parse_whisper_settings

    # Test standard model config
    standard_config = {
        "model_name": "small",
        "device": "cpu",
    }
    settings = _parse_whisper_settings(standard_config)
    print(f"✓ Standard config: model_name={settings.model_name}, ggml_model_path={settings.ggml_model_path}")

    # Test GGML model config
    ggml_config = {
        "ggml_model_path": "/path/to/ggml-custom.bin",
        "whisper_cpp_binary": "/usr/local/bin/whisper-cli",
        "device": "auto",
    }
    settings = _parse_whisper_settings(ggml_config)
    print(f"✓ GGML config: ggml_model_path={settings.ggml_model_path}, binary={settings.whisper_cpp_binary}")

    assert settings.ggml_model_path == "/path/to/ggml-custom.bin"
    assert settings.whisper_cpp_binary == "/usr/local/bin/whisper-cli"

    print("✓ Config integration tests passed!\n")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  Whisper.cpp Integration Test Suite")
    print("="*60)

    try:
        test_ggml_detection()
        test_wrapper_initialization()
        test_timestamp_parsing()
        test_integration_with_config()

        print("\n" + "="*60)
        print("  ✓ ALL TESTS PASSED!")
        print("="*60)
        print("\nNext steps:")
        print("1. Install whisper.cpp: https://github.com/ggerganov/whisper.cpp")
        print("2. Download a GGML model: ./models/download-ggml-model.sh base.en")
        print("3. Configure ggml_model_path in config.yaml")
        print("4. Run the pipeline with your custom model!")
        print()

        return 0

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
