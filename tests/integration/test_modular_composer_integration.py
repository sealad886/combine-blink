"""
Integration tests for ModularComposer.

Tests the complete modular composition pipeline from clips to rendered output.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blink_pipeline.composition import ModularComposer


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        'multi_camera_composition': {
            'enable_composition': True,
            'use_modular_composition': True,
            'switching_strategy': 'time_based',
            'switching_interval': 5.0,
            'single_pass_filter_complex': False,
            'audio_alignment': {
                'enabled': False,  # Disable for faster tests
            },
            'timestamp_overlay': {
                'enabled': True,
                'font': 'Arial',
                'font_size': 24,
            },
            'audio_mix': {
                'crossfade_seconds': 0.05,
                'curve1': 'tri',
                'curve2': 'tri',
            },
        },
        'output': {
            'audio_cache_dir': 'output/audio_cache',
        },
    }


@pytest.fixture
def sample_clips():
    """Sample video clips in legacy format."""
    base_time = datetime(2025, 10, 24, 12, 0, 0)
    return [
        {
            'path': '/path/to/camera1.mp4',
            'camera': 'Camera1',
            'datetime': base_time,
        },
        {
            'path': '/path/to/camera2.mp4',
            'camera': 'Camera2',
            'datetime': base_time + timedelta(seconds=1),
        },
    ]


def test_modular_composer_initialization(sample_config):
    """Test ModularComposer initializes with correct modules."""
    composer = ModularComposer(sample_config)

    assert composer.config is not None
    assert composer.quality_analyzer is not None
    assert composer.alignment_engine is not None
    assert composer.timeline_generator is not None
    assert composer.audio_processor is not None
    assert composer.overlay_generator is not None
    assert composer.renderer is not None

    # Should use MultiPassRenderer by default
    from blink_pipeline.composition.rendering import MultiPassRenderer
    assert isinstance(composer.renderer, MultiPassRenderer)


def test_modular_composer_single_pass_selection(sample_config):
    """Test single-pass renderer selection."""
    sample_config['multi_camera_composition']['single_pass_filter_complex'] = True
    composer = ModularComposer(sample_config)

    from blink_pipeline.composition.rendering import SinglePassRenderer
    assert isinstance(composer.renderer, SinglePassRenderer)


def test_convert_clips(sample_config, sample_clips):
    """Test conversion from legacy clip format to modular types."""
    composer = ModularComposer(sample_config)

    # Mock probe_media_info to avoid needing real video files
    with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe:
        mock_probe.return_value = MagicMock(
            duration=10.0,
            duration_timedelta=timedelta(seconds=10),
            width=1920,
            height=1080,
            fps=30.0,
            audio_sample_rate=48000,
            audio_channels=2,
        )

        clips = composer._convert_clips(sample_clips)

        assert len(clips) == 2
        assert clips[0].camera_id == 'Camera1'
        assert clips[1].camera_id == 'Camera2'
        assert clips[0].duration == 10.0
        assert clips[0].resolution == (1920, 1080)


def test_convert_to_timeline_clips(sample_config, sample_clips):
    """Test conversion to timeline-compatible format."""
    composer = ModularComposer(sample_config)

    with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe:
        mock_probe.return_value = MagicMock(
            duration=10.0,
            duration_timedelta=timedelta(seconds=10),
            width=1920,
            height=1080,
            fps=30.0,
            audio_sample_rate=48000,
            audio_channels=2,
        )

        clips = composer._convert_clips(sample_clips)
        timeline_clips = composer._convert_to_timeline_clips(clips)

        assert len(timeline_clips) == 2
        assert timeline_clips[0].start_time == 0.0  # First clip at event start
        assert timeline_clips[1].start_time == 1.0  # Second clip 1s later
        assert timeline_clips[0].camera_id == 'Camera1'


def test_convert_speech_segments(sample_config):
    """Test conversion of speech segments."""
    composer = ModularComposer(sample_config)

    speech_segments = [
        {'start': 0.0, 'end': 5.0, 'speaker': 'Speaker1', 'text': 'Hello'},
        {'start': 5.0, 'end': 10.0, 'speaker': 'Speaker2', 'text': 'World'},
    ]

    converted = composer._convert_speech(speech_segments)

    assert converted is not None
    assert len(converted) == 2
    assert converted[0].start == 0.0
    assert converted[0].speaker == 'Speaker1'
    assert converted[1].end == 10.0


def test_compose_multi_camera_event_mock(sample_config, sample_clips):
    """Test end-to-end composition with mocked components."""
    composer = ModularComposer(sample_config)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = str(Path(tmpdir) / 'output.mp4')

        # Mock all the heavy components
        with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe, \
             patch.object(composer.quality_analyzer, 'analyze') as mock_analyze, \
             patch.object(composer.renderer, 'render') as mock_render:

            # Setup mocks
            mock_probe.return_value = MagicMock(
                duration=10.0,
                duration_timedelta=timedelta(seconds=10),
                width=1920,
                height=1080,
                fps=30.0,
                audio_sample_rate=48000,
                audio_channels=2,
            )

            from blink_pipeline.composition.models import QualityMetrics
            mock_analyze.return_value = QualityMetrics(
                rms_db=-20.0,
                peak_db=-3.0,
                noise_floor_db=-60.0,
                clipping_rate=0.0,
            )

            mock_render.return_value = True

            # Run composition
            result = composer.compose_multi_camera_event(
                video_clips=sample_clips,
                output_video_path=output_path,
            )

            assert result is True
            assert mock_render.called

            # Verify renderer was called with correct types
            call_args = mock_render.call_args
            assert call_args is not None
            clips_arg, timeline_arg, output_arg = call_args[0][:3]
            assert len(clips_arg) == 2
            assert output_arg == Path(output_path)


def test_event_start_captured(sample_config, sample_clips):
    """Test that event_start is captured for timestamp overlays."""
    composer = ModularComposer(sample_config)

    with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe, \
         patch.object(composer.quality_analyzer, 'analyze') as mock_analyze, \
         patch.object(composer.renderer, 'render') as mock_render:

        mock_probe.return_value = MagicMock(
            duration=10.0,
            duration_timedelta=timedelta(seconds=10),
            width=1920,
            height=1080,
            fps=30.0,
            audio_sample_rate=48000,
            audio_channels=2,
        )

        from blink_pipeline.composition.models import QualityMetrics
        mock_analyze.return_value = QualityMetrics(
            rms_db=-20.0,
            peak_db=-3.0,
            noise_floor_db=-60.0,
            clipping_rate=0.0,
        )

        mock_render.return_value = True

        with tempfile.TemporaryDirectory() as tmpdir:
            composer.compose_multi_camera_event(
                video_clips=sample_clips,
                output_video_path=str(Path(tmpdir) / 'output.mp4'),
            )

            # Event start should be captured
            assert composer._event_start is not None
            assert composer._event_start == datetime(2025, 10, 24, 12, 0, 0)


def test_compose_with_speech_segments(sample_config, sample_clips):
    """Test composition with speech segments."""
    composer = ModularComposer(sample_config)

    speech_segments = [
        {'start': 0.0, 'end': 5.0, 'speaker': 'Speaker1'},
        {'start': 5.0, 'end': 10.0, 'speaker': 'Speaker2'},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe, \
             patch.object(composer.quality_analyzer, 'analyze') as mock_analyze, \
             patch.object(composer.renderer, 'render') as mock_render:

            mock_probe.return_value = MagicMock(
                duration=10.0,
                duration_timedelta=timedelta(seconds=10),
                width=1920,
                height=1080,
                fps=30.0,
                audio_sample_rate=48000,
                audio_channels=2,
            )

            from blink_pipeline.composition.models import QualityMetrics
            mock_analyze.return_value = QualityMetrics(
                rms_db=-20.0,
                peak_db=-3.0,
                noise_floor_db=-60.0,
                clipping_rate=0.0,
            )

            mock_render.return_value = True

            result = composer.compose_multi_camera_event(
                video_clips=sample_clips,
                output_video_path=str(Path(tmpdir) / 'output.mp4'),
                speech_segments=speech_segments,
            )

            assert result is True


def test_error_handling(sample_config):
    """Test error handling in composition."""
    composer = ModularComposer(sample_config)

    # Empty clips should return False
    result = composer.compose_multi_camera_event(
        video_clips=[],
        output_video_path='/tmp/output.mp4',
    )

    assert result is False


def test_renderer_error_propagation(sample_config, sample_clips):
    """Test that renderer errors are handled gracefully."""
    composer = ModularComposer(sample_config)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('blink_pipeline.composition.composer.probe_media_info') as mock_probe, \
             patch.object(composer.quality_analyzer, 'analyze') as mock_analyze, \
             patch.object(composer.renderer, 'render') as mock_render:

            mock_probe.return_value = MagicMock(
                duration=10.0,
                duration_timedelta=timedelta(seconds=10),
                width=1920,
                height=1080,
                fps=30.0,
                audio_sample_rate=48000,
                audio_channels=2,
            )

            from blink_pipeline.composition.models import QualityMetrics
            mock_analyze.return_value = QualityMetrics(
                rms_db=-20.0,
                peak_db=-3.0,
                noise_floor_db=-60.0,
                clipping_rate=0.0,
            )

            # Simulate renderer failure
            mock_render.return_value = False

            result = composer.compose_multi_camera_event(
                video_clips=sample_clips,
                output_video_path=str(Path(tmpdir) / 'output.mp4'),
            )

            assert result is False
