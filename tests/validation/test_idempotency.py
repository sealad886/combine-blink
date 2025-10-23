"""
Idempotency Validation Tests

Ensures that operations produce consistent results when repeated:
- AlignmentEngine produces same results with same inputs
- CachedAlignmentEngine cache works correctly
- Feature flag behavior is consistent
- No side effects that change results on repeated calls

Author: Validation suite
"""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch

from blink_pipeline.composition.alignment import (
    AlignmentConfig,
    AlignmentEngine,
    CachedAlignmentEngine,
    AlignmentResult
)
from blink_pipeline.multi_camera_composer import MultiCameraComposer


class TestAlignmentEngineIdempotency:
    """Test AlignmentEngine produces identical results on repeated calls."""

    def test_gcc_phat_idempotency(self):
        """GCC-PHAT should produce identical results for same inputs."""
        config = AlignmentConfig(
            enabled=True,
            max_shift=1.0,
            sample_rate=16000
        )
        engine = AlignmentEngine(config)

        # Create test signals
        fs = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(fs * duration))

        # Reference signal
        ref_signal = np.sin(2 * np.pi * 440 * t)

        # Delayed signal (100ms delay)
        delay_samples = int(0.1 * fs)
        sig_signal = np.zeros_like(ref_signal)
        sig_signal[delay_samples:] = ref_signal[:-delay_samples]

        # Run alignment multiple times
        results = []
        for _ in range(5):
            offset = engine._gcc_phat(
                sig=sig_signal,
                refsig=ref_signal,
                fs=fs,
                max_tau=1.0,
                interp=16
            )
            results.append(offset)

        # All results should be identical (within floating point precision)
        for i in range(1, len(results)):
            assert abs(results[i] - results[0]) < 1e-10, \
                f"Result {i} differs from first result: {results[i]} vs {results[0]}"

    @patch('librosa.load')
    @patch('blink_pipeline.composition.alignment.ensure_wav_cache')
    def test_align_clips_idempotency(self, mock_wav_cache, mock_load, tmp_path):
        """align_clips should produce identical results for same inputs."""
        config = AlignmentConfig(enabled=True, max_shift=1.0)
        engine = AlignmentEngine(config)

        # Mock audio extraction
        def fake_wav_cache(path, *args, **kwargs):
            return str(tmp_path / f"{Path(path).stem}.wav")

        mock_wav_cache.side_effect = fake_wav_cache

        # Create consistent test audio
        fs = 16000
        duration = 2.0
        t = np.linspace(0, duration, int(fs * duration))
        ref_audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)

        # Camera audio with 50ms delay
        delay_samples = int(0.05 * fs)
        cam_audio = np.zeros_like(ref_audio)
        cam_audio[delay_samples:] = ref_audio[:-delay_samples]

        # Mock librosa to return consistent audio
        mock_load.side_effect = lambda *args, **kwargs: (
            cam_audio if 'cam1' in str(args[0]) else ref_audio,
            fs
        )

        # Run alignment multiple times
        camera_clips = {
            "ref": [Path("ref_001.mp4")],
            "cam1": [Path("cam1_001.mp4")]
        }

        results_list = []
        for _ in range(3):
            results = engine.align_clips(
                camera_clips=camera_clips,
                ref_camera="ref"
            )
            results_list.append(results)

        # All results should be identical
        for i in range(1, len(results_list)):
            assert len(results_list[i]) == len(results_list[0])
            for j in range(len(results_list[i])):
                assert results_list[i][j].camera == results_list[0][j].camera
                assert abs(results_list[i][j].offset_seconds - results_list[0][j].offset_seconds) < 1e-10
                assert results_list[i][j].confidence == results_list[0][j].confidence


class TestCachedAlignmentEngineIdempotency:
    """Test CachedAlignmentEngine cache consistency."""

    @patch('librosa.load')
    @patch('blink_pipeline.composition.alignment.ensure_wav_cache')
    def test_cache_hit_returns_identical_results(self, mock_wav_cache, mock_load, tmp_path):
        """Cache hits should return identical results to cache misses."""
        config = AlignmentConfig(enabled=True, max_shift=1.0)
        engine = CachedAlignmentEngine(config)

        # Mock audio extraction
        def fake_wav_cache(path, *args, **kwargs):
            return str(tmp_path / f"{Path(path).stem}.wav")

        mock_wav_cache.side_effect = fake_wav_cache

        # Create consistent test audio
        fs = 16000
        duration = 2.0
        t = np.linspace(0, duration, int(fs * duration))
        ref_audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        cam_audio = ref_audio.copy()  # Identical audio

        mock_load.side_effect = lambda *args, **kwargs: (
            cam_audio if 'cam1' in str(args[0]) else ref_audio,
            fs
        )

        camera_clips = {
            "ref": [Path("ref_001.mp4")],
            "cam1": [Path("cam1_001.mp4")]
        }

        # First call - cache miss
        assert engine.cache_size == 0
        results1 = engine.align_clips(camera_clips, ref_camera="ref")
        cache_size_after_first = engine.cache_size

        # Second call - cache hit
        results2 = engine.align_clips(camera_clips, ref_camera="ref")

        # Cache should have grown after first call but not after second
        assert cache_size_after_first > 0
        assert engine.cache_size == cache_size_after_first

        # Results should be identical
        assert len(results1) == len(results2)
        for i in range(len(results1)):
            assert results1[i] == results2[i]

    def test_cache_clear_resets_state(self):
        """Cache clear should reset engine state."""
        config = AlignmentConfig(enabled=True)
        engine = CachedAlignmentEngine(config)

        # Manually add to cache
        cache_key = ("path1", "path2", 1.0, 12.0, 16000, True, 16, False)
        engine._cache[cache_key] = AlignmentResult(
            camera="cam1",
            offset_seconds=0.123
        )

        assert engine.cache_size == 1

        # Clear cache
        engine.clear_cache()

        assert engine.cache_size == 0
        assert len(engine._cache) == 0


class TestMultiCameraComposerIdempotency:
    """Test MultiCameraComposer initialization is consistent."""

    def test_composer_initialization_idempotent(self, tmp_path):
        """Composer should initialize with same state every time."""
        config = {
            'multi_camera_composition': {
                'use_modular_composition': True,
                'alignment_config': {
                    'enabled': True,
                    'max_shift': 1.5,
                    'window_seconds': 12.0
                }
            }
        }

        # Create multiple composers
        composers = []
        for _ in range(3):
            composer = MultiCameraComposer(config)
            composers.append(composer)

        # All should have same configuration
        for i in range(1, len(composers)):
            assert composers[i]._use_modular_composition == composers[0]._use_modular_composition
            assert composers[i]._alignment_enabled == composers[0]._alignment_enabled
            assert composers[i]._alignment_max_shift == composers[0]._alignment_max_shift

            # Both should have modular engine initialized
            assert composers[i]._modular_alignment_engine is not None
            assert composers[0]._modular_alignment_engine is not None


class TestConfigurationIdempotency:
    """Test configuration objects are immutable and consistent."""

    def test_alignment_config_immutable(self):
        """AlignmentConfig should be frozen (immutable)."""
        config = AlignmentConfig(
            enabled=True,
            max_shift=1.5
        )

        # Should not be able to modify
        with pytest.raises(AttributeError):
            config.max_shift = 2.0

        with pytest.raises(AttributeError):
            config.enabled = False

    def test_alignment_result_immutable(self):
        """AlignmentResult should be frozen (immutable)."""
        result = AlignmentResult(
            camera="cam1",
            offset_seconds=0.123
        )

        # Should not be able to modify
        with pytest.raises(AttributeError):
            result.offset_seconds = 0.456

        with pytest.raises(AttributeError):
            result.camera = "cam2"

    def test_config_hash_consistency(self):
        """Config objects with same values should have same hash."""
        config1 = AlignmentConfig(
            enabled=True,
            max_shift=1.5,
            window_seconds=12.0
        )

        config2 = AlignmentConfig(
            enabled=True,
            max_shift=1.5,
            window_seconds=12.0
        )

        # Should be equal and have same hash
        assert config1 == config2
        assert hash(config1) == hash(config2)


class TestFeatureFlagIdempotency:
    """Test feature flag behavior is consistent."""

    def test_feature_flag_consistent_across_calls(self):
        """Feature flag state should be consistent across multiple operations."""
        config_enabled = {
            'multi_camera_composition': {
                'use_modular_composition': True,
                'alignment_config': {'enabled': True}
            }
        }

        config_disabled = {
            'multi_camera_composition': {
                'use_modular_composition': False,
                'alignment_config': {'enabled': True}
            }
        }

        # Test enabled composer
        composer_enabled = MultiCameraComposer(config_enabled)
        assert composer_enabled._use_modular_composition is True
        assert composer_enabled._modular_alignment_engine is not None

        # State should not change
        assert composer_enabled._use_modular_composition is True
        assert composer_enabled._modular_alignment_engine is not None

        # Test disabled composer
        composer_disabled = MultiCameraComposer(config_disabled)
        assert composer_disabled._use_modular_composition is False
        assert composer_disabled._modular_alignment_engine is None

        # State should not change
        assert composer_disabled._use_modular_composition is False
        assert composer_disabled._modular_alignment_engine is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
