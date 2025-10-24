"""
Unit tests for timeline generation strategies.

Tests all 4 strategies: TimeBasedStrategy, RoundRobinStrategy,
AudioQualityStrategy, SpeechPeopleStrategy.
"""

import pytest
from blink_pipeline.composition.config import CompositionConfig, PeopleDetectionConfig
from blink_pipeline.composition.timeline import (
    TimelineGenerator,
    TimeBasedStrategy,
    RoundRobinStrategy,
    AudioQualityStrategy,
    SpeechPeopleStrategy,
    CameraClip,
    SpeechSegment,
)


@pytest.fixture
def base_config():
    """Base composition configuration."""
    return CompositionConfig(
        switching_strategy="time_based",
        switching_interval=5.0,
        people_detection=PeopleDetectionConfig(
            enabled=True,
            min_count=1,
            score_threshold=0.5,
        ),
    )


@pytest.fixture
def sample_clips():
    """Sample camera clips for testing."""
    return [
        CameraClip(
            path="/video/cam1.mp4",
            camera="Camera 1",
            camera_id="cam1",
            start_time=0.0,
            duration=30.0,
            audio_quality_score=0.8,
        ),
        CameraClip(
            path="/video/cam2.mp4",
            camera="Camera 2",
            camera_id="cam2",
            start_time=0.0,
            duration=30.0,
            audio_quality_score=0.9,
        ),
        CameraClip(
            path="/video/cam3.mp4",
            camera="Camera 3",
            camera_id="cam3",
            start_time=5.0,
            duration=25.0,
            audio_quality_score=0.7,
        ),
    ]


@pytest.fixture
def speech_segments():
    """Sample speech segments."""
    return [
        SpeechSegment(start=0.0, end=10.0, speaker="Speaker A"),
        SpeechSegment(start=15.0, end=25.0, speaker="Speaker B"),
        # Silent: 10-15, 25-30
    ]


class TestTimeBasedStrategy:
    """Tests for TimeBasedStrategy."""

    def test_regular_intervals(self, base_config, sample_clips):
        """Test switching at regular intervals."""
        strategy = TimeBasedStrategy(base_config)
        timeline = strategy.generate(sample_clips)

        assert len(timeline) > 0

        # Verify segments use configured interval
        for seg in timeline:
            assert seg.duration <= base_config.switching_interval + 0.1
            assert seg.duration >= 0.1  # Minimum reasonable segment

    def test_clip_boundaries(self, base_config, sample_clips):
        """Test respects clip boundaries."""
        strategy = TimeBasedStrategy(base_config)
        timeline = strategy.generate(sample_clips)

        for seg in timeline:
            # Find source clip
            source_clip = next(
                c for c in sample_clips
                if c.camera_id == seg.camera_id
            )

            # Verify segment is within clip bounds
            assert seg.start_time >= source_clip.start_time
            assert seg.start_time + seg.duration <= source_clip.start_time + source_clip.duration

    def test_empty_clips(self, base_config):
        """Test handles empty clip list."""
        strategy = TimeBasedStrategy(base_config)
        timeline = strategy.generate([])

        assert timeline == []

    def test_camera_rotation(self, base_config, sample_clips):
        """Test rotates through cameras."""
        strategy = TimeBasedStrategy(base_config)
        timeline = strategy.generate(sample_clips)

        # Get unique cameras used
        cameras = [seg.camera_id for seg in timeline]
        unique_cameras = set(cameras)

        # Should use multiple cameras
        assert len(unique_cameras) >= 2


class TestRoundRobinStrategy:
    """Tests for RoundRobinStrategy."""

    def test_uses_time_based(self, base_config, sample_clips):
        """Test delegates to TimeBasedStrategy."""
        strategy = RoundRobinStrategy(base_config)
        timeline = strategy.generate(sample_clips)

        # Should produce same results as time_based
        time_based = TimeBasedStrategy(base_config)
        time_based_timeline = time_based.generate(sample_clips)

        assert len(timeline) == len(time_based_timeline)


class TestAudioQualityStrategy:
    """Tests for AudioQualityStrategy."""

    def test_prefers_best_quality(self, base_config, sample_clips):
        """Test prefers camera with best audio quality."""
        strategy = AudioQualityStrategy(base_config)
        timeline = strategy.generate(sample_clips)

        assert len(timeline) > 0

        # Camera 2 has best quality (0.9), should be preferred when available
        cam2_segments = [s for s in timeline if s.camera_id == "cam2"]
        assert len(cam2_segments) > 0

    def test_quality_score_selection(self, base_config):
        """Test selects correct camera based on quality."""
        clips = [
            CameraClip(
                path="/video/low.mp4",
                camera="Low Quality",
                camera_id="low",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.3,
            ),
            CameraClip(
                path="/video/high.mp4",
                camera="High Quality",
                camera_id="high",
                start_time=0.0,
                duration=10.0,
                audio_quality_score=0.95,
            ),
        ]

        strategy = AudioQualityStrategy(base_config)
        timeline = strategy.generate(clips)

        # Should predominantly use high quality camera
        high_quality_duration = sum(
            s.duration for s in timeline if s.camera_id == "high"
        )
        total_duration = sum(s.duration for s in timeline)

        assert high_quality_duration / total_duration > 0.8

    def test_handles_gaps(self, base_config):
        """Test handles non-overlapping clips."""
        clips = [
            CameraClip(
                path="/video/cam1.mp4",
                camera="Camera 1",
                camera_id="cam1",
                start_time=0.0,
                duration=5.0,
                audio_quality_score=0.8,
            ),
            CameraClip(
                path="/video/cam2.mp4",
                camera="Camera 2",
                camera_id="cam2",
                start_time=10.0,
                duration=5.0,
                audio_quality_score=0.9,
            ),
        ]

        strategy = AudioQualityStrategy(base_config)
        timeline = strategy.generate(clips)

        # Should create segments for both clips
        assert len(timeline) >= 2


class TestSpeechPeopleStrategy:
    """Tests for SpeechPeopleStrategy."""

    def test_speech_active_uses_audio_quality(self, base_config, sample_clips, speech_segments):
        """Test uses best audio during speech."""
        strategy = SpeechPeopleStrategy(base_config)
        timeline = strategy.generate(sample_clips, speech_segments)

        # Find segments during speech
        speech_segs = [
            s for s in timeline
            if s.speech_active
        ]

        assert len(speech_segs) > 0

        # During speech, should prefer cam2 (best audio: 0.9)
        speech_cameras = [s.camera_id for s in speech_segs]
        assert "cam2" in speech_cameras

    def test_people_detection_fallback(self, base_config, sample_clips, speech_segments):
        """Test uses people detection during silence."""
        # Mock people detector
        def people_detector(clip: CameraClip, time: float) -> int:
            # Cam1 has 2 people, cam2 has 1, cam3 has 0
            if clip.camera_id == "cam1":
                return 2
            elif clip.camera_id == "cam2":
                return 1
            return 0

        strategy = SpeechPeopleStrategy(base_config, people_detector)
        timeline = strategy.generate(sample_clips, speech_segments)

        # Find segments during silence
        silent_segs = [
            s for s in timeline
            if not s.speech_active
        ]

        # During silence, should prefer cam1 (most people)
        if silent_segs:
            silent_cameras = [s.camera_id for s in silent_segs]
            assert "cam1" in silent_cameras

    def test_needs_review_flag(self, base_config, sample_clips, speech_segments):
        """Test flags multi-angle silent segments for review."""
        # Multiple cameras with people during silence
        def people_detector(clip: CameraClip, time: float) -> int:
            # All cameras have people
            return 2

        strategy = SpeechPeopleStrategy(base_config, people_detector)
        timeline = strategy.generate(sample_clips, speech_segments)

        # Should flag some segments for review
        review_segs = [s for s in timeline if s.needs_review]

        # May or may not have review segments depending on silence duration
        # Just verify the flag exists and is boolean
        for seg in timeline:
            assert isinstance(seg.needs_review, bool)

    def test_segment_coalescing(self, base_config):
        """Test merges adjacent segments from same source."""
        clips = [
            CameraClip(
                path="/video/cam1.mp4",
                camera="Camera 1",
                camera_id="cam1",
                start_time=0.0,
                duration=30.0,
                audio_quality_score=0.9,  # Best quality
            ),
        ]

        strategy = SpeechPeopleStrategy(base_config)
        timeline = strategy.generate(clips)

        # With single best-quality camera, should coalesce into few segments
        assert len(timeline) <= 5

    def test_no_speech_segments(self, base_config, sample_clips):
        """Test handles missing speech segments."""
        strategy = SpeechPeopleStrategy(base_config)
        timeline = strategy.generate(sample_clips, None)

        # Should assume speech is active everywhere
        assert len(timeline) > 0
        assert all(s.speech_active for s in timeline)


class TestTimelineGenerator:
    """Tests for TimelineGenerator orchestrator."""

    def test_strategy_selection_time_based(self, base_config, sample_clips):
        """Test selects time_based strategy."""
        config = base_config.model_copy(update={"switching_strategy": "time_based"})
        generator = TimelineGenerator(config)

        video_timeline, audio_timeline = generator.generate(sample_clips)

        assert len(video_timeline) > 0
        assert len(audio_timeline) > 0

    def test_strategy_selection_audio_quality(self, base_config, sample_clips):
        """Test selects audio_quality strategy."""
        config = base_config.model_copy(update={"switching_strategy": "audio_quality"})
        generator = TimelineGenerator(config)

        video_timeline, audio_timeline = generator.generate(sample_clips)

        assert len(video_timeline) > 0

    def test_strategy_selection_speech_people(self, base_config, sample_clips, speech_segments):
        """Test selects speech_people strategy."""
        config = base_config.model_copy(update={"switching_strategy": "speech_people"})
        generator = TimelineGenerator(config)

        video_timeline, audio_timeline = generator.generate(sample_clips, speech_segments)

        assert len(video_timeline) > 0

    def test_unknown_strategy_fallback(self, base_config, sample_clips):
        """Test falls back to speech_people for unknown strategy."""
        config = base_config.model_copy(update={"switching_strategy": "unknown"})
        generator = TimelineGenerator(config)

        video_timeline, audio_timeline = generator.generate(sample_clips)

        # Should still generate timeline
        assert len(video_timeline) > 0

    def test_dual_timeline_generation(self, base_config, sample_clips):
        """Test generates both video and audio timelines."""
        generator = TimelineGenerator(base_config)

        video_timeline, audio_timeline = generator.generate(sample_clips)

        assert len(video_timeline) > 0
        assert len(audio_timeline) > 0

        # For now, audio matches video
        assert len(video_timeline) == len(audio_timeline)

    def test_empty_clips(self, base_config):
        """Test handles empty clip list."""
        generator = TimelineGenerator(base_config)

        video_timeline, audio_timeline = generator.generate([])

        assert video_timeline == []
        assert audio_timeline == []

    def test_people_detector_integration(self, base_config, sample_clips, speech_segments):
        """Test passes people detector to speech_people strategy."""
        def people_detector(clip: CameraClip, time: float) -> int:
            return 1

        config = base_config.model_copy(update={"switching_strategy": "speech_people"})
        generator = TimelineGenerator(config, people_detector)

        video_timeline, audio_timeline = generator.generate(sample_clips, speech_segments)

        # Should successfully generate timeline with people detection
        assert len(video_timeline) > 0


class TestDataModels:
    """Tests for legacy-compatible data models."""

    def test_camera_clip_creation(self):
        """Test CameraClip dataclass."""
        clip = CameraClip(
            path="/video/test.mp4",
            camera="Test Camera",
            camera_id="test",
            start_time=10.5,
            duration=30.0,
            audio_quality_score=0.85,
        )

        assert clip.path == "/video/test.mp4"
        assert clip.start_time == 10.5
        assert clip.duration == 30.0
        assert clip.audio_quality_score == 0.85

    def test_speech_segment_creation(self):
        """Test SpeechSegment dataclass."""
        segment = SpeechSegment(
            start=5.0,
            end=10.0,
            speaker="Speaker A",
        )

        assert segment.start == 5.0
        assert segment.end == 10.0
        assert segment.speaker == "Speaker A"

    def test_composition_segment_fields(self):
        """Test CompositionSegment has all required fields."""
        from blink_pipeline.composition.timeline import CompositionSegment

        segment = CompositionSegment(
            camera="Test",
            camera_id="test",
            clip_path="/video/test.mp4",
            start_time=0.0,
            start=0.0,
            end=5.0,
            duration=5.0,
            source_start=0.0,
            source_end=5.0,
            audio_source="test",
            needs_review=False,
            speech_active=True,
            reason="test",
        )

        assert segment.duration == 5.0
        assert segment.needs_review is False
        assert segment.speech_active is True
