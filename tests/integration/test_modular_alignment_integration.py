"""
Integration tests for modular alignment engine with multi_camera_composer.

Tests:
- Feature flag enables modular AlignmentEngine
- AlignmentEngine is initialized correctly from config
- Alignment results match expected format
- Fallback to legacy implementation when flag disabled
- Error handling and logging

Author: Phase 2 integration testing
"""

import pytest
import logging
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List

from blink_pipeline.multi_camera_composer import MultiCameraComposer
from blink_pipeline.composition.alignment import AlignmentResult


@pytest.fixture
def base_config():
    """Base configuration for composer."""
    return {
        'output': {
            'audio_cache_dir': 'output/audio_cache'
        },
        'multi_camera_composition': {
            'enable_composition': True,
            'switching_strategy': 'time_based',
            'switching_interval': 5.0,
            'transition_style': 'cut',
            'audio_source': 'best_quality',
            'audio_alignment': {
                'enabled': True,
                'max_shift_seconds': 1.5,
                'analysis_window_seconds': 12.0,
                'sample_rate': 16000,
                'bandpass': True,
                'highpass_hz': 300,
                'lowpass_hz': 3000,
                'estimate_drift': False
            }
        }
    }


@pytest.fixture
def modular_config(base_config):
    """Configuration with modular composition enabled."""
    config = base_config.copy()
    config['multi_camera_composition']['use_modular_composition'] = True
    return config


@pytest.fixture
def legacy_config(base_config):
    """Configuration with modular composition disabled."""
    config = base_config.copy()
    config['multi_camera_composition']['use_modular_composition'] = False
    return config


class TestModularAlignmentIntegration:
    """Test modular alignment engine integration."""

    def test_feature_flag_enables_modular_alignment(self, modular_config):
        """Test that feature flag enables modular alignment engine."""
        composer = MultiCameraComposer(modular_config)

        # Check feature flag is enabled
        assert composer._use_modular_composition is True

        # Check modular alignment engine is initialized
        assert composer._modular_alignment_engine is not None
        assert hasattr(composer._modular_alignment_engine, 'align_clips')
        assert hasattr(composer._modular_alignment_engine, 'cache_size')

    def test_feature_flag_disabled_uses_legacy(self, legacy_config):
        """Test that disabled flag uses legacy implementation."""
        composer = MultiCameraComposer(legacy_config)

        # Check feature flag is disabled
        assert composer._use_modular_composition is False

        # Check modular engine is not initialized
        assert composer._modular_alignment_engine is None

    def test_alignment_config_from_yaml(self, modular_config):
        """Test alignment configuration is read from YAML correctly."""
        composer = MultiCameraComposer(modular_config)

        # Check configuration values
        assert composer._alignment_enabled is True
        assert composer._alignment_max_shift == 1.5
        assert composer._alignment_window == 12.0
        assert composer._alignment_sr == 16000
        assert composer._alignment_bandpass is True
        assert composer._alignment_hp == 300
        assert composer._alignment_lp == 3000
        assert composer._alignment_estimate_drift is False

        # Check modular engine has correct config
        engine = composer._modular_alignment_engine
        assert engine.config.max_shift == 1.5
        assert engine.config.window_seconds == 12.0
        assert engine.config.sample_rate == 16000
        assert engine.config.bandpass_enabled is True
        assert engine.config.bandpass_lowcut == 300.0
        assert engine.config.bandpass_highcut == 3000.0

    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._analyze_clips')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._load_speech_segments')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._generate_aligned_timelines')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._create_composite_video')
    @patch('blink_pipeline.composition.alignment.CachedAlignmentEngine.align_clips')
    def test_modular_alignment_called_during_composition(
        self,
        mock_align,
        mock_create_composite,
        mock_generate_timelines,
        mock_load_speech,
        mock_analyze,
        modular_config
    ):
        """Test modular alignment engine is called during composition."""
        from blink_pipeline.multi_camera_composer import CameraClip

        # Setup mocks
        camera_clips = [
            CameraClip(
                path="cam1_001.mp4",
                camera="cam1",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.8
            ),
            CameraClip(
                path="cam2_001.mp4",
                camera="cam2",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.6
            )
        ]
        mock_analyze.return_value = camera_clips
        mock_load_speech.return_value = None
        mock_generate_timelines.return_value = ([], [])
        mock_create_composite.return_value = True

        # Mock alignment results
        mock_align.return_value = [
            AlignmentResult(
                camera="cam2",
                offset_seconds=0.125,
                confidence=0.95,
                num_windows=3,
                offset_std=0.01
            )
        ]

        # Run composition
        composer = MultiCameraComposer(modular_config)
        video_clips = [
            {'path': 'cam1_001.mp4', 'camera': 'cam1', 'timestamp': '2024-01-01 12:00:00'},
            {'path': 'cam2_001.mp4', 'camera': 'cam2', 'timestamp': '2024-01-01 12:00:00'}
        ]

        composer.compose_multi_camera_event(
            video_clips,
            output_path='test_output.mp4',
            speech_segments=None,
            speech_timeline=None,
            progress_callback=None
        )

        # Verify modular alignment was called
        assert mock_align.call_count == 1

        # Check alignment was called with correct arguments
        call_kwargs = mock_align.call_args[1]
        assert 'camera_clips' in call_kwargs
        assert 'ref_camera' in call_kwargs
        assert call_kwargs['ref_camera'] == 'cam1'  # Best quality

        # Verify camera clips were prepared correctly
        camera_clips_dict = call_kwargs['camera_clips']
        assert 'cam1' in camera_clips_dict
        assert 'cam2' in camera_clips_dict
        assert len(camera_clips_dict['cam1']) == 1
        assert len(camera_clips_dict['cam2']) == 1

    @patch('blink_pipeline.av_alignment.ensure_wav_cache')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._analyze_clips')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._load_speech_segments')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._generate_aligned_timelines')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._create_composite_video')
    @patch('blink_pipeline.multi_camera_composer.estimate_per_clip_offsets')
    def test_legacy_alignment_called_when_flag_disabled(
        self,
        mock_estimate,
        mock_create_composite,
        mock_generate_timelines,
        mock_load_speech,
        mock_analyze,
        mock_audio_cache,
        legacy_config,
        tmp_path,
        caplog
    ):
        """Test legacy alignment is called when feature flag disabled."""
        from blink_pipeline.multi_camera_composer import CameraClip

        # Mock audio cache to return valid WAV paths
        def fake_audio_cache(video_path, *args, **kwargs):
            # Return a fake WAV path based on video path
            wav_path = tmp_path / f"{Path(video_path).stem}.wav"
            wav_path.touch()  # Create empty file
            return str(wav_path)

        mock_audio_cache.side_effect = fake_audio_cache

        # Setup mocks
        camera_clips = [
            CameraClip(
                path="cam1_001.mp4",
                camera="cam1",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.8
            ),
            CameraClip(
                path="cam2_001.mp4",
                camera="cam2",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.6
            )
        ]
        mock_analyze.return_value = camera_clips
        mock_load_speech.return_value = None
        mock_generate_timelines.return_value = ([], [])
        mock_create_composite.return_value = True

        # Mock legacy alignment - must return dict with camera names as keys
        def mock_alignment_func(*args, **kwargs):
            logging.debug(f"Mock estimate_per_clip_offsets called with args={args[:2]}, kwargs keys={kwargs.keys()}")
            return {'cam2': 0.125}

        mock_estimate.side_effect = mock_alignment_func

        # Run composition
        composer = MultiCameraComposer(legacy_config)

        # Debug: Check alignment is enabled
        assert composer._alignment_enabled is True, "Alignment should be enabled in test"
        assert composer._use_modular_composition is False, "Feature flag should be off"

        video_clips = [
            {'path': 'cam1_001.mp4', 'camera': 'cam1', 'timestamp': '2024-01-01 12:00:00'},
            {'path': 'cam2_001.mp4', 'camera': 'cam2', 'timestamp': '2024-01-01 12:00:00'}
        ]

        with caplog.at_level(logging.DEBUG):
            composer.compose_multi_camera_event(
                video_clips,
                output_path='test_output.mp4',
                speech_segments=None,
                speech_timeline=None,
                progress_callback=None
            )

        # Verify legacy alignment was called
        assert mock_estimate.call_count == 1, f"estimate_per_clip_offsets should be called once, but was called {mock_estimate.call_count} times"

        # Verify legacy parameters
        call_args = mock_estimate.call_args
        assert call_args[0][1] == 'cam1'  # ref_camera

    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._analyze_clips')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._load_speech_segments')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._generate_aligned_timelines')
    @patch('blink_pipeline.multi_camera_composer.MultiCameraComposer._create_composite_video')
    @patch('blink_pipeline.composition.alignment.CachedAlignmentEngine.align_clips')
    @patch('blink_pipeline.audio_cache.ensure_wav_cache')
    def test_alignment_error_handling(
        self,
        mock_audio_cache,
        mock_align,
        mock_create_composite,
        mock_generate_timelines,
        mock_load_speech,
        mock_analyze,
        modular_config,
        tmp_path,
        caplog
    ):
        """Test alignment errors are handled gracefully."""
        from blink_pipeline.multi_camera_composer import CameraClip

        # Mock audio cache to return valid WAV paths
        def fake_audio_cache(video_path, *args, **kwargs):
            wav_path = tmp_path / f"{Path(video_path).stem}.wav"
            wav_path.touch()
            return str(wav_path)

        mock_audio_cache.side_effect = fake_audio_cache

        # Setup mocks
        camera_clips = [
            CameraClip(
                path="cam1_001.mp4",
                camera="cam1",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.8
            ),
            CameraClip(
                path="cam2_001.mp4",
                camera="cam2",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.6
            )
        ]
        mock_analyze.return_value = camera_clips
        mock_load_speech.return_value = None
        mock_generate_timelines.return_value = ([], [])
        mock_create_composite.return_value = True

        # Make alignment raise an error
        mock_align.side_effect = Exception("Alignment failed!")

        # Run composition
        composer = MultiCameraComposer(modular_config)
        video_clips = [
            {'path': 'cam1_001.mp4', 'camera': 'cam1', 'timestamp': '2024-01-01 12:00:00'},
            {'path': 'cam2_001.mp4', 'camera': 'cam2', 'timestamp': '2024-01-01 12:00:00'}
        ]

        output_path = tmp_path / 'test_output.mp4'

        with caplog.at_level(logging.WARNING):
            result = composer.compose_multi_camera_event(
                video_clips,
                output_path=str(output_path),
                speech_segments=None,
                speech_timeline=None,
                progress_callback=None
            )

        # Composition should still succeed
        assert result is True

        # Warning should be logged
        assert any('alignment estimation failed' in record.message.lower()
                  for record in caplog.records)

    def test_alignment_disabled_skips_engine(self, modular_config):
        """Test that disabled alignment skips engine initialization."""
        modular_config['multi_camera_composition']['audio_alignment']['enabled'] = False

        composer = MultiCameraComposer(modular_config)

        # Alignment should be disabled
        assert composer._alignment_enabled is False

        # Modular engine should not be initialized
        assert composer._modular_alignment_engine is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
