"""
Timeline Generation Module

Strategy pattern for timeline generation algorithms.
Supports: time_based, round_robin, audio_quality, speech_people.

NOTE: This module retains a legacy-compatible CameraClip/CompositionSegment format
for backward compatibility during the transition period.

Classes:
- TimelineStrategy: Abstract base strategy
- TimeBasedStrategy: Switch at regular intervals
- RoundRobinStrategy: Cycle through cameras equally
- AudioQualityStrategy: Prefer best audio quality
- SpeechPeopleStrategy: Anchor to speech, fall back to people detection
- TimelineGenerator: Main generator with strategy selection

Author: Phase 3 implementation
Status: In Progress
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from typing import Callable, Dict, List, Optional, Tuple

from .config import CompositionConfig

logger = logging.getLogger(__name__)


# Legacy format compatibility retained during refactor
@dataclass
class CameraClip:
    """Legacy camera clip format (event-relative float times)."""
    path: str
    camera: str
    camera_id: str  # Alias for camera
    start_time: float  # Seconds since event start
    duration: float
    audio_quality_score: float = 0.0
    video_quality_score: float = 0.0
    people_count: float = 0.0
    alignment_offset: float = 0.0  # Seconds (positive means audio is later)


@dataclass
class CompositionSegment:
    """Legacy composition segment format."""
    camera: str
    camera_id: str  # Alias for camera
    clip_path: str
    start_time: float  # Time in final composition
    start: float  # Alias for start_time
    end: float  # End time in final composition
    duration: float
    source_start: float = 0.0  # Start time within source clip
    source_end: float = 0.0  # End time within source clip
    audio_source: str = ""  # Camera ID for audio (may differ from video)
    # Decoupled audio fields: if not provided, renderer falls back to clip_path/source_* for audio
    audio_clip_path: Optional[str] = None  # Source path for audio
    audio_source_start: Optional[float] = None  # Start in audio source clip
    audio_source_end: Optional[float] = None  # End in audio source clip
    needs_review: bool = False
    speech_active: bool = True
    reason: Optional[str] = None


@dataclass
class SpeechSegment:
    """Speech segment from diarization."""
    start: float
    end: float
    speaker: str
    text: Optional[str] = None


# Type aliases
Timeline = List[CompositionSegment]


class TimelineStrategy(ABC):
    """Abstract base class for timeline generation strategies."""

    def __init__(self, config: CompositionConfig):
        """Initialize strategy with configuration."""
        self.config = config

    @abstractmethod
    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Timeline:
        """Generate composition timeline."""
        pass

    # --- Shared helpers for strategies ---
    def _select_audio_clip(self, clips: List[CameraClip]) -> Optional[CameraClip]:
        """Select an audio clip from available clips based on config.audio_source.

        Strategies:
        - best_quality: highest audio_quality_score
        - first: earliest start_time among available
        - longest: largest duration among available
        """
        if not clips:
            return None
        strategy = getattr(self.config, 'audio_source', 'best_quality')
        if strategy == 'first':
            return min(clips, key=lambda c: (c.start_time, -c.duration))
        if strategy == 'longest':
            return max(clips, key=lambda c: c.duration)
        # default: best_quality
        return max(clips, key=lambda c: c.audio_quality_score)

    @staticmethod
    def _set_audio_fields(
        seg: 'CompositionSegment',
        video_clip: CameraClip,
        audio_clip: Optional[CameraClip],
        seg_start: float,
        seg_duration: float,
    ) -> None:
        """Populate decoupled audio fields on segment if audio_clip provided.

        Computes audio_source_start/end relative to chosen audio clip timeline.
        Assumes audio_clip covers [seg_start, seg_start+seg_duration]; this is
        guaranteed when boundaries are created from all clip start/end times.
        """
        if not audio_clip:
            # Fallback: use the same as video
            seg.audio_clip_path = seg.clip_path
            seg.audio_source_start = seg.source_start
            seg.audio_source_end = seg.source_end
            return
        seg.audio_source = audio_clip.camera_id
        seg.audio_clip_path = audio_clip.path
        # Start in audio source timeline, adjusted by alignment delta between selected video and audio
        align_delta = float(getattr(video_clip, 'alignment_offset', 0.0)) - float(getattr(audio_clip, 'alignment_offset', 0.0))
        a_start = max(0.0, (seg_start - audio_clip.start_time) + align_delta)
        seg.audio_source_start = a_start
        seg.audio_source_end = a_start + seg_duration


class TimeBasedStrategy(TimelineStrategy):
    """Switch cameras at regular time intervals."""

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Timeline:
        """
        Generate time-based timeline by switching at regular intervals.

        Args:
            clips: List of camera clips
            speech_segments: Unused for time-based strategy

        Returns:
            Timeline with segments switching at configured interval
        """
        if not clips:
            return []

        timeline: Timeline = []
        current_time = 0.0

        # Calculate total event duration
        total_duration = max(
            clip.start_time + clip.duration
            for clip in clips
        )

        # Sort cameras by name for consistent ordering
        cameras_sorted = sorted(set(clip.camera_id for clip in clips))
        camera_index = 0

        while current_time < total_duration:
            # Find clips available at current_time
            available_clips = [
                clip for clip in clips
                if clip.start_time <= current_time < clip.start_time + clip.duration
            ]

            if not available_clips:
                # No clips available, advance to next clip start
                future_clips = [
                    clip for clip in clips
                    if clip.start_time > current_time
                ]
                if future_clips:
                    current_time = min(clip.start_time for clip in future_clips)
                    continue
                else:
                    break

            # Select next camera in rotation that's available
            selected_clip = None
            for _ in range(len(cameras_sorted)):
                camera_name = cameras_sorted[camera_index % len(cameras_sorted)]
                camera_index += 1

                matching = [c for c in available_clips if c.camera_id == camera_name]
                if matching:
                    selected_clip = matching[0]
                    break

            if not selected_clip:
                selected_clip = available_clips[0]

            # Calculate segment duration
            segment_duration = min(
                self.config.switching_interval,
                (selected_clip.start_time + selected_clip.duration) - current_time,
                total_duration - current_time
            )

            # Calculate where to start in the source clip
            source_start = current_time - selected_clip.start_time

            seg = CompositionSegment(
                camera=selected_clip.camera,
                camera_id=selected_clip.camera_id,
                clip_path=selected_clip.path,
                start_time=current_time,
                start=current_time,
                end=current_time + segment_duration,
                duration=segment_duration,
                source_start=source_start,
                source_end=source_start + segment_duration,
                audio_source=selected_clip.camera_id,
                reason="time_based",
            )
            # Decouple audio: choose best audio among available at this time
            audio_clip = self._select_audio_clip(available_clips)
            self._set_audio_fields(seg, selected_clip, audio_clip, current_time, segment_duration)
            timeline.append(seg)

            current_time += segment_duration

        return timeline


class RoundRobinStrategy(TimelineStrategy):
    """Cycle through cameras equally."""

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Timeline:
        """
        Generate round-robin timeline - reuses time_based for now.

        Args:
            clips: List of camera clips
            speech_segments: Unused

        Returns:
            Timeline with round-robin camera selection
        """
        # Round-robin uses the same logic as time-based with regular intervals
        time_based = TimeBasedStrategy(self.config)
        return time_based.generate(clips, speech_segments)


class AudioQualityStrategy(TimelineStrategy):
    """Prefer camera with best audio quality."""

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Timeline:
        """
        Generate audio-quality-based timeline.

        Selects camera with best audio quality at each moment, switching
        at configured intervals.

        Args:
            clips: List of camera clips
            speech_segments: Unused for audio quality strategy

        Returns:
            Timeline preferring best audio quality
        """
        if not clips:
            return []

        timeline: Timeline = []
        current_time = 0.0

        total_duration = max(
            clip.start_time + clip.duration
            for clip in clips
        )

        while current_time < total_duration:
            # Find available clips
            available_clips = [
                clip for clip in clips
                if clip.start_time <= current_time < clip.start_time + clip.duration
            ]

            if not available_clips:
                # Advance to next clip start
                future_clips = [
                    clip for clip in clips
                    if clip.start_time > current_time
                ]
                if future_clips:
                    current_time = min(clip.start_time for clip in future_clips)
                    continue
                else:
                    break

            # Select clip with best audio quality
            selected_clip = max(available_clips, key=lambda x: x.audio_quality_score)

            # Calculate segment duration
            segment_duration = min(
                self.config.switching_interval,
                (selected_clip.start_time + selected_clip.duration) - current_time,
                total_duration - current_time
            )

            source_start = current_time - selected_clip.start_time

            seg = CompositionSegment(
                camera=selected_clip.camera,
                camera_id=selected_clip.camera_id,
                clip_path=selected_clip.path,
                start_time=current_time,
                start=current_time,
                end=current_time + segment_duration,
                duration=segment_duration,
                source_start=source_start,
                source_end=source_start + segment_duration,
                audio_source=selected_clip.camera_id,
                reason="audio_quality",
            )
            audio_clip = self._select_audio_clip(available_clips)
            self._set_audio_fields(seg, selected_clip, audio_clip, current_time, segment_duration)
            timeline.append(seg)

            current_time += segment_duration

        return timeline


class SpeechPeopleStrategy(TimelineStrategy):
    """Anchor to speech, fall back to people detection during silence."""

    def __init__(self, config: CompositionConfig, people_detector: Optional[Callable] = None):
        """
        Initialize strategy with people detection capability.

        Args:
            config: Composition configuration
            people_detector: Optional callable that returns people count for a clip at time t
                            Signature: (clip: CameraClip, time: float) -> int
        """
        super().__init__(config)
        self.people_detector = people_detector

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Timeline:
        """
        Generate speech-aware timeline with people detection fallback.

        During speech: Use best audio quality
        During silence: Use angle with most people (if detector provided)

        Args:
            clips: List of camera clips
            speech_segments: Speech segments from diarization

        Returns:
            Timeline anchored to speech with intelligent silent period handling
        """
        if not clips:
            return []

        # Build timeline using boundary-based approach (like legacy)
        boundaries = self._create_boundaries(clips)

        timeline: Timeline = []

        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            seg_dur = seg_end - seg_start

            if seg_dur <= 0:
                continue

            # Find available clips
            avail = [
                c for c in clips
                if c.start_time <= seg_start < c.start_time + c.duration
            ]

            if not avail:
                continue

            # Check if speech is active in this segment
            speech_active = self._segment_has_speech(seg_start, seg_end, speech_segments)

            # Select camera
            selected: CameraClip
            needs_review = False

            if speech_active:
                # During speech: use best audio quality
                selected = max(avail, key=lambda x: x.audio_quality_score)
            else:
                # During silence: try people detection
                if self.people_detector and len(avail) > 1:
                    # Sample people count at segment midpoint
                    sample_t = seg_start + 0.5 * seg_dur

                    # Get people counts for each clip
                    people_clips = []
                    for clip in avail:
                        count = self.people_detector(clip, sample_t)
                        if count >= self.config.people_detection.min_count:
                            people_clips.append((clip, count))

                    if len(people_clips) >= 2:
                        # Multiple angles with people - select best and flag for review
                        selected = max(people_clips, key=lambda x: x[1])[0]
                        needs_review = True
                    elif people_clips:
                        # Single angle with people
                        selected = people_clips[0][0]
                    else:
                        # No people detected, fall back to best audio
                        selected = max(avail, key=lambda x: x.audio_quality_score)
                else:
                    # No people detector or single camera - use best audio
                    selected = max(avail, key=lambda x: x.audio_quality_score)

            source_start = max(0.0, seg_start - selected.start_time)

            seg = CompositionSegment(
                camera=selected.camera,
                camera_id=selected.camera_id,
                clip_path=selected.path,
                start_time=seg_start,
                start=seg_start,
                end=seg_end,
                duration=seg_dur,
                source_start=source_start,
                source_end=source_start + seg_dur,
                audio_source=selected.camera_id,
                needs_review=needs_review,
                speech_active=speech_active,
                reason="speech_people",
            )
            # Audio: choose independently based on config
            audio_clip = self._select_audio_clip(avail)
            self._set_audio_fields(seg, selected, audio_clip, seg_start, seg_dur)
            timeline.append(seg)

        # Coalesce adjacent segments from same source
        timeline = self._coalesce_segments(timeline)

        return timeline

    def _create_boundaries(self, clips: List[CameraClip]) -> List[float]:
        """Create sorted list of boundary times from clip starts and ends."""
        boundaries = {0.0}
        for clip in clips:
            boundaries.add(clip.start_time)
            boundaries.add(clip.start_time + clip.duration)
        return sorted(boundaries)

    def _segment_has_speech(
        self,
        start: float,
        end: float,
        speech_segments: Optional[List[SpeechSegment]]
    ) -> bool:
        """Check if a time segment overlaps with any speech."""
        if not speech_segments:
            return True  # Assume speech if no data

        for seg in speech_segments:
            if seg.start >= end:
                break
            if seg.end > start and seg.start < end:
                return True
        return False

    def _coalesce_segments(self, segments: List[CompositionSegment]) -> List[CompositionSegment]:
        """Merge adjacent segments from the same source to reduce cuts."""
        if not segments:
            return []

        merged: List[CompositionSegment] = []
        current = segments[0]

        for seg in segments[1:]:
            # Check if segments can be merged
            if (
                seg.clip_path == current.clip_path and
                seg.needs_review == current.needs_review and
                seg.speech_active == current.speech_active and
                abs(seg.start_time - (current.start_time + current.duration)) < 1e-3
            ):
                # Extend current segment
                current.duration += seg.duration
                current.end = seg.end
                current.source_end = seg.source_end
            else:
                merged.append(current)
                current = seg

        merged.append(current)
        return merged


class TimelineGenerator:
    """Main timeline generator with strategy selection."""

    def __init__(self, config: CompositionConfig, people_detector: Optional[Callable] = None):
        """
        Initialize generator with configuration.

        Args:
            config: Composition configuration
            people_detector: Optional people detection callable for speech_people strategy
        """
        self.config = config
        self.people_detector = people_detector
        self._strategy = self._create_strategy()

    def _create_strategy(self) -> TimelineStrategy:
        """Create strategy based on configuration."""
        strategy_name = self.config.switching_strategy
        if strategy_name == 'time_based':
            return TimeBasedStrategy(self.config)
        elif strategy_name == 'round_robin':
            return RoundRobinStrategy(self.config)
        elif strategy_name == 'audio_quality':
            return AudioQualityStrategy(self.config)
        elif strategy_name == 'speech_people':
            return SpeechPeopleStrategy(self.config, self.people_detector)
        else:
            logger.warning(f"Unknown strategy '{strategy_name}', falling back to speech_people")
            return SpeechPeopleStrategy(self.config, self.people_detector)

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Tuple[Timeline, Timeline]:
        """
        Generate video and audio timelines.

        Args:
            clips: List of camera clips with alignment and quality data
            speech_segments: Speech segments from diarization (optional)

        Returns:
            Tuple of (video_timeline, audio_timeline)
        """
        if not clips:
            return [], []

        # Sort clips by start time
        sorted_clips = sorted(clips, key=lambda c: c.start_time)

        # Generate primary timeline using strategy
        logger.info(f"Generating timeline with strategy: {self.config.switching_strategy}")
        video_timeline = self._strategy.generate(sorted_clips, speech_segments)

        # Sanitize to ensure strictly monotonic, non-overlapping timeline
        video_timeline = self._sanitize_timeline(video_timeline)

        # For now, audio timeline mirrors video segments with decoupled audio fields filled
        audio_timeline = video_timeline.copy()

        # Log summary
        logger.info(
            f"Timeline generated: {len(video_timeline)} video segments, "
            f"{len(audio_timeline)} audio segments"
        )

        if any(seg.needs_review for seg in video_timeline):
            review_count = sum(1 for seg in video_timeline if seg.needs_review)
            logger.warning(
                f"{review_count} segments flagged for manual review "
                "(multiple angles with people during silence)"
            )

        return video_timeline, audio_timeline

    @staticmethod
    def _sanitize_timeline(timeline: Timeline) -> Timeline:
        """Ensure non-overlapping, time-monotonic segments. Trim or drop overlaps.

        This guards against any upstream rounding errors causing tiny time regressions
        that could manifest as repeated moments.
        """
        if not timeline:
            return []
        tl = sorted(timeline, key=lambda s: float(getattr(s, 'start_time', getattr(s, 'start', 0.0))))
        sanitized: Timeline = []
        last_end = 0.0
        for seg in tl:
            s = float(getattr(seg, 'start_time', getattr(seg, 'start', 0.0)))
            d = float(getattr(seg, 'duration', 0.0))
            e = s + d
            if s < last_end - 1e-3:
                # Trim leading overlap
                trim = last_end - s
                new_d = max(0.0, d - trim)
                if new_d <= 1e-3:
                    continue
                # Adjust segment fields
                seg.start_time = last_end
                seg.start = last_end
                seg.duration = new_d
                seg.source_start = float(getattr(seg, 'source_start', 0.0)) + trim
                seg.source_end = seg.source_start + new_d
                # Adjust audio fields if present
                if getattr(seg, 'audio_source_start', None) is not None:
                    seg.audio_source_start = float(seg.audio_source_start) + trim
                    seg.audio_source_end = float(seg.audio_source_start) + new_d
                s = last_end
                e = s + new_d
            # Enforce monotonic
            sanitized.append(seg)
            last_end = max(last_end, e)
        return sanitized


__all__ = [
    'TimelineStrategy',
    'TimeBasedStrategy',
    'RoundRobinStrategy',
    'AudioQualityStrategy',
    'SpeechPeopleStrategy',
    'TimelineGenerator',
]
