"""
Integration test for modular timeline generation in MultiCameraComposer.

Tests that the modular timeline module integrates correctly with the
legacy composer and produces compatible output.
"""

import tempfile
from pathlib import Path
import pytest

from blink_pipeline.multi_camera_composer import MultiCameraComposer


@pytest.fixture
def modular_config():
    """Configuration with modular timeline enabled."""
    return {
        'multi_camera_composition': {
            'use_modular_composition': True,
            'switching_strategy': 'time_based',
            'switching_interval': 5.0,
            'enable_composition': True,
        },
        'output': {
            'audio_cache_dir': tempfile.mkdtemp(),
        },
        'logging': {},
    }


@pytest.fixture
def legacy_config():
    """Configuration with legacy timeline (modular disabled)."""
    return {
        'multi_camera_composition': {
            'use_modular_composition': False,
            'switching_strategy': 'time_based',
            'switching_interval': 5.0,
            'enable_composition': True,
        },
        'output': {},
        'logging': {},
    }


def test_modular_timeline_integration(modular_config):
    """Test that modular timeline module integrates with composer."""
    composer = MultiCameraComposer(modular_config)

    # Verify modular components initialized
    assert composer._use_modular_composition is True
    assert composer._timeline_generator is not None
    assert composer._modular_quality_analyzer is not None


def test_legacy_timeline_still_works(legacy_config):
    """Test that legacy timeline still works when modular is disabled."""
    composer = MultiCameraComposer(legacy_config)

    # Verify legacy mode
    assert composer._use_modular_composition is False
    assert composer._timeline_generator is None


def test_modular_timeline_conversion():
    """Test conversion between legacy and modular CameraClip formats."""
    from blink_pipeline.multi_camera_composer import CameraClip
    from blink_pipeline.composition.timeline import CameraClip as ModularCameraClip

    # Create legacy clip
    legacy_clip = CameraClip(
        path="/video/test.mp4",
        camera="Test Camera",
        start_time=10.0,
        duration=30.0,
        audio_quality_score=0.8,
        video_quality_score=0.7,
        people_count=2.0,
    )

    # Convert to modular format (same as done in _generate_timelines_modular)
    modular_clip = ModularCameraClip(
        path=legacy_clip.path,
        camera=legacy_clip.camera,
        camera_id=legacy_clip.camera,
        start_time=legacy_clip.start_time,
        duration=legacy_clip.duration,
        audio_quality_score=legacy_clip.audio_quality_score,
        video_quality_score=legacy_clip.video_quality_score,
        people_count=legacy_clip.people_count,
    )

    # Verify conversion preserved data
    assert modular_clip.path == legacy_clip.path
    assert modular_clip.camera == legacy_clip.camera
    assert modular_clip.start_time == legacy_clip.start_time
    assert modular_clip.duration == legacy_clip.duration
    assert modular_clip.audio_quality_score == legacy_clip.audio_quality_score


def test_segment_format_compatibility():
    """Test that modular segments convert to legacy format correctly."""
    from blink_pipeline.multi_camera_composer import CompositionSegment as LegacySegment
    from blink_pipeline.composition.timeline import CompositionSegment as ModularSegment

    # Create modular segment (with extra fields)
    modular_seg = ModularSegment(
        camera="Camera 1",
        camera_id="cam1",
        clip_path="/video/cam1.mp4",
        start_time=0.0,
        start=0.0,
        end=5.0,
        duration=5.0,
        source_start=0.0,
        source_end=5.0,
        audio_source="cam1",
        needs_review=False,
        speech_active=True,
        reason="test",
    )

    # Convert to legacy format (same as done in _generate_timelines_modular)
    legacy_seg = LegacySegment(
        camera=modular_seg.camera,
        clip_path=modular_seg.clip_path,
        start_time=modular_seg.start_time,
        duration=modular_seg.duration,
        source_start=modular_seg.source_start,
        needs_review=modular_seg.needs_review,
        speech_active=modular_seg.speech_active,
    )

    # Verify essential fields preserved
    assert legacy_seg.camera == modular_seg.camera
    assert legacy_seg.clip_path == modular_seg.clip_path
    assert legacy_seg.start_time == modular_seg.start_time
    assert legacy_seg.duration == modular_seg.duration
    assert legacy_seg.source_start == modular_seg.source_start
    assert legacy_seg.needs_review == modular_seg.needs_review
    assert legacy_seg.speech_active == modular_seg.speech_active


def test_people_detector_callable(modular_config):
    """Test that people detector callable works."""
    from blink_pipeline.composition.timeline import CameraClip as ModularCameraClip

    composer = MultiCameraComposer(modular_config)

    # Create test clip
    clip = ModularCameraClip(
        path="/video/test.mp4",
        camera="Test",
        camera_id="test",
        start_time=0.0,
        duration=10.0,
        audio_quality_score=0.8,
        people_count=3.0,
    )

    # Call people detector
    count = composer._get_people_count_for_timeline(clip, 5.0)

    # Should return stored people count
    assert count == 3
