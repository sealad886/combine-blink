#!/usr/bin/env python3
"""
Runtime validation test for ffprobe and alignment configuration fixes.

This test validates:
1. ffprobe works without -nostdin flag
2. AlignmentEngine accepts Pydantic AlignmentConfig from ModularComposer
"""

import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from blink_pipeline.composition.config import AlignmentConfig as PydanticAlignmentConfig
from blink_pipeline.composition.alignment import AlignmentEngine
from blink_pipeline.media_utils import probe_media_info


def test_ffprobe_fix():
    """Test that ffprobe works correctly without -nostdin flag."""
    print("\n" + "="*80)
    print("TEST 1: FFprobe Fix Validation")
    print("="*80)

    # Find a test video file
    test_files = list(Path("output/merged_videos").glob("*.mp4"))
    if not test_files:
        print("❌ No test videos found in output/merged_videos/")
        return False

    test_file = test_files[0]
    print(f"📁 Testing with: {test_file.name}")

    # Test probe_media_info (uses our fixed ffprobe)
    try:
        info = probe_media_info(str(test_file))
        print(f"✅ probe_media_info succeeded:")
        print(f"   - Duration: {info.duration:.2f}s")
        print(f"   - Has audio: {info.has_audio}")
        print(f"   - Video duration: {info.video_duration:.2f}s")
        print(f"   - Audio duration: {info.audio_duration:.2f}s")
        return True
    except Exception as exc:
        print(f"❌ probe_media_info failed: {exc}")
        return False


def test_alignment_config_compatibility():
    """Test that AlignmentEngine accepts Pydantic AlignmentConfig."""
    print("\n" + "="*80)
    print("TEST 2: Alignment Config Compatibility")
    print("="*80)

    try:
        # Create Pydantic config like ModularComposer does
        pydantic_config = PydanticAlignmentConfig(
            enabled=True,
            max_shift_seconds=1.5,
            analysis_window_seconds=12.0,
            sample_rate=48000,
            bandpass=True,
            highpass_hz=80.0,
            lowpass_hz=8000.0,
            estimate_drift=True
        )
        print("✅ Created Pydantic AlignmentConfig")
        print(f"   - max_shift_seconds: {pydantic_config.max_shift_seconds}")
        print(f"   - bandpass: {pydantic_config.bandpass}")
        print(f"   - highpass_hz: {pydantic_config.highpass_hz}")

        # Create AlignmentEngine with Pydantic config
        engine = AlignmentEngine(pydantic_config)
        print("✅ AlignmentEngine instantiated with Pydantic config")

        # Test the _cfg() accessor method
        max_shift = engine._cfg('max_shift', 1.0, alias='max_shift_seconds')
        bandpass = engine._cfg('bandpass_enabled', True, alias='bandpass')
        highpass = engine._cfg('bandpass_lowcut', 300, alias='highpass_hz')
        lowpass = engine._cfg('bandpass_highcut', 3000, alias='lowpass_hz')

        print("✅ Config accessor (_cfg) working correctly:")
        print(f"   - max_shift (via alias): {max_shift}s")
        print(f"   - bandpass_enabled (via alias): {bandpass}")
        print(f"   - highpass (via alias): {highpass}Hz")
        print(f"   - lowpass (via alias): {lowpass}Hz")

        # Verify values match
        assert max_shift == 1.5, f"Expected max_shift=1.5, got {max_shift}"
        assert bandpass == True, f"Expected bandpass=True, got {bandpass}"
        assert highpass == 80, f"Expected highpass=80, got {highpass}"
        assert lowpass == 8000, f"Expected lowpass=8000, got {lowpass}"

        print("✅ All config values correctly mapped via aliases")
        return True

    except Exception as exc:
        print(f"❌ Alignment config test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation tests."""
    print("\n" + "="*80)
    print("🎬 RUNTIME VALIDATION: FFprobe & Alignment Fixes")
    print("="*80)

    results = []

    # Test 1: FFprobe fix
    results.append(("FFprobe Fix", test_ffprobe_fix()))

    # Test 2: Alignment config compatibility
    results.append(("Alignment Config", test_alignment_config_compatibility()))

    # Summary
    print("\n" + "="*80)
    print("📊 TEST RESULTS SUMMARY")
    print("="*80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
        if not passed:
            all_passed = False

    print("="*80)

    if all_passed:
        print("\n🎉 ALL TESTS PASSED - Fixes validated successfully!")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Review errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
