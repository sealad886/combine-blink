# Module Interface Specifications

## Overview

This document defines the **public interfaces** for each module in the refactored multi-camera composition system. These interfaces serve as **contracts** between modules, enabling:

- **Independent Development**: Teams can work on modules in parallel
- **Testability**: Interfaces can be mocked for unit testing
- **Extensibility**: New implementations can be swapped via dependency injection
- **Documentation**: Clear API surface for users and maintainers

---

## 1. Configuration Module (`composition_config.py`)

### Public Models

#### `AudioQualityWeights`
```python
from pydantic import BaseModel, Field, field_validator
from typing import Dict

class AudioQualityWeights(BaseModel):
    """Weights for combining audio quality metrics into composite score."""

    rms: float = Field(0.4, ge=0.0, le=1.0, description="Weight for RMS level score")
    peak: float = Field(0.2, ge=0.0, le=1.0, description="Weight for peak level score")
    noise: float = Field(0.2, ge=0.0, le=1.0, description="Weight for noise floor score")
    clip: float = Field(0.2, ge=0.0, le=1.0, description="Weight for clipping penalty")

    @field_validator('rms', 'peak', 'noise', 'clip')
    @classmethod
    def validate_weight_range(cls, v: float) -> float:
        """Ensure each weight is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Weight must be between 0 and 1, got {v}")
        return v

    @property
    def total_weight(self) -> float:
        """Sum of all weights (should be ~1.0 for normalized scoring)."""
        return self.rms + self.peak + self.noise + self.clip

    def normalize(self) -> 'AudioQualityWeights':
        """Return normalized weights that sum to 1.0."""
        total = self.total_weight
        if total <= 0:
            return AudioQualityWeights(rms=1.0, peak=0.0, noise=0.0, clip=0.0)
        return AudioQualityWeights(
            rms=self.rms / total,
            peak=self.peak / total,
            noise=self.noise / total,
            clip=self.clip / total
        )
```

#### `AlignmentConfig`
```python
class AlignmentConfig(BaseModel):
    """Configuration for audio alignment via cross-correlation."""

    enabled: bool = Field(True, description="Enable fine audio alignment")
    max_shift_seconds: float = Field(
        1.5,
        gt=0.0,
        le=5.0,
        description="Maximum allowed time shift for alignment"
    )
    analysis_window_seconds: float = Field(
        12.0,
        gt=0.0,
        description="Window size for cross-correlation analysis"
    )
    hop_seconds: float = Field(
        6.0,
        gt=0.0,
        description="Hop size between analysis windows (for multi-window median)"
    )
    sample_rate: int = Field(
        16000,
        gt=0,
        description="Audio sample rate for alignment analysis"
    )
    bandpass: bool = Field(True, description="Apply bandpass filter (speech frequencies)")
    highpass_hz: int = Field(300, gt=0, description="Highpass filter cutoff frequency")
    lowpass_hz: int = Field(3000, gt=0, description="Lowpass filter cutoff frequency")
    estimate_drift: bool = Field(
        True,
        description="Estimate clock drift between cameras"
    )

    @field_validator('lowpass_hz')
    @classmethod
    def validate_lowpass_above_highpass(cls, v: int, info) -> int:
        """Ensure lowpass > highpass."""
        if 'highpass_hz' in info.data and v <= info.data['highpass_hz']:
            raise ValueError(f"Lowpass ({v}) must be greater than highpass ({info.data['highpass_hz']})")
        return v
```

#### `PeopleDetectionConfig`
```python
class PeopleDetectionConfig(BaseModel):
    """Configuration for people detection in video frames."""

    enabled: bool = Field(True, description="Enable people detection")
    model_name: str = Field(
        'hustvl/yolos-tiny',
        description="Hugging Face model identifier"
    )
    revision: Optional[str] = Field(None, description="Model revision/branch")
    score_threshold: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for person detection"
    )
    min_count: int = Field(
        1,
        ge=0,
        description="Minimum number of people to consider clip 'has people'"
    )
    resize_width: int = Field(
        640,
        gt=0,
        description="Resize frame to this width before detection (speed optimization)"
    )
    min_frame_width: int = Field(
        320,
        gt=0,
        description="Minimum frame width (avoid over-downscaling)"
    )
    sample_frames: int = Field(
        6,
        gt=0,
        description="Number of frames to sample per clip for detection"
    )
```

#### `SwitchingStrategy` (Enum)
```python
from enum import Enum

class SwitchingStrategy(str, Enum):
    """Camera switching strategies."""

    TIME_BASED = "time_based"
    """Switch cameras at regular intervals, prefer continuity."""

    ROUND_ROBIN = "round_robin"
    """Cycle through cameras equally."""

    AUDIO_QUALITY = "audio_quality"
    """Always use camera with best audio quality."""

    SPEECH_PEOPLE = "speech_people"
    """Use best audio during speech, most people during silence."""
```

#### `AudioSource` (Enum)
```python
class AudioSource(str, Enum):
    """Audio source selection strategies."""

    BEST_QUALITY = "best_quality"
    """Use single best audio quality clip for entire event."""

    PER_SEGMENT = "per_segment"
    """Choose best audio quality per segment (may switch frequently)."""

    FIRST = "first"
    """Use first clip's audio (chronologically)."""

    LONGEST = "longest"
    """Use longest clip's audio."""
```

#### `CompositionConfig`
```python
class CompositionConfig(BaseModel):
    """Top-level configuration for multi-camera composition."""

    # Strategy settings
    switching_strategy: SwitchingStrategy = Field(
        SwitchingStrategy.TIME_BASED,
        description="Camera switching strategy"
    )
    switching_interval: float = Field(
        5.0,
        gt=0.0,
        description="Time interval for switching cameras (time_based/round_robin)"
    )
    audio_source: AudioSource = Field(
        AudioSource.BEST_QUALITY,
        description="Audio selection strategy"
    )

    # Sub-configurations
    quality_weights: AudioQualityWeights = Field(
        default_factory=AudioQualityWeights,
        description="Weights for audio quality scoring"
    )
    alignment: AlignmentConfig = Field(
        default_factory=AlignmentConfig,
        description="Audio alignment configuration"
    )
    people_detection: PeopleDetectionConfig = Field(
        default_factory=PeopleDetectionConfig,
        description="People detection configuration"
    )

    # Encoding settings
    single_pass: bool = Field(
        True,
        description="Use single-pass filter_complex (faster, modern)"
    )
    use_hw_encode: bool = Field(
        False,
        description="Use hardware encoder (e.g., VideoToolbox on macOS)"
    )
    hw_codec: str = Field("h264_videotoolbox", description="Hardware codec name")
    x264_preset: str = Field("veryfast", description="x264 software encoder preset")
    x264_crf: str = Field("22", description="x264 constant rate factor (quality)")
    bitrate: str = Field("6000k", description="Target bitrate for hardware encoding")

    # Audio processing
    audio_crossfade_seconds: float = Field(
        0.06,
        ge=0.0,
        le=5.0,
        description="Crossfade duration between audio segments"
    )

    # Overlay settings
    timestamp_overlay_enabled: bool = Field(
        True,
        description="Enable timestamp overlay on video"
    )
    overlay_font: str = Field("Arial", description="Font for overlay text")
    overlay_font_size: int = Field(24, gt=0, description="Font size for overlay")

    # Audio cleanup
    audio_cleanup_enabled: bool = Field(
        True,
        description="Apply audio cleanup filters (highpass, denoise, loudnorm)"
    )
    highpass_hz: Optional[float] = Field(120.0, description="Highpass filter frequency")
    lowpass_hz: Optional[float] = Field(7000.0, description="Lowpass filter frequency")
    denoise: bool = Field(True, description="Apply denoising")
    loudness_normalize: bool = Field(True, description="Apply loudness normalization")

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'CompositionConfig':
        """
        Create CompositionConfig from nested dictionary (legacy format).

        Args:
            config_dict: Configuration dictionary with 'multi_camera_composition' key

        Returns:
            CompositionConfig instance

        Example:
            >>> config = CompositionConfig.from_dict({
            ...     'multi_camera_composition': {
            ...         'switching_strategy': 'audio_quality',
            ...         'audio_quality_weights': {'rms': 0.5, 'peak': 0.5}
            ...     }
            ... })
        """
        comp_config = config_dict.get('multi_camera_composition', {})

        # Map legacy keys to new structure
        return cls(
            switching_strategy=comp_config.get('switching_strategy', 'time_based'),
            switching_interval=comp_config.get('switching_interval', 5.0),
            audio_source=comp_config.get('audio_source', 'best_quality'),
            quality_weights=AudioQualityWeights(
                **comp_config.get('audio_quality_weights', {})
            ),
            alignment=AlignmentConfig(
                **comp_config.get('audio_alignment', {})
            ),
            people_detection=PeopleDetectionConfig(
                **comp_config.get('people_detection', {})
            ),
            # ... other mappings
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to legacy dictionary format for backward compatibility."""
        return {
            'multi_camera_composition': {
                'switching_strategy': self.switching_strategy.value,
                'switching_interval': self.switching_interval,
                'audio_source': self.audio_source.value,
                'audio_quality_weights': self.quality_weights.dict(),
                'audio_alignment': self.alignment.dict(),
                'people_detection': self.people_detection.dict(),
                # ... other fields
            }
        }
```

---

## 2. Data Models (`data_models.py`)

### `CameraClip`
```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class CameraClip:
    """
    Represents a single camera clip with metadata and quality scores.

    Attributes:
        path: Absolute file path to video clip
        camera: Camera identifier (e.g., "iPhone_12_Pro", "GoPro_Hero10")
        start_time: Seconds since event start (after alignment adjustments)
        duration: Clip duration in seconds
        audio_quality_score: Composite audio quality score (0-1, higher = better)
        video_quality_score: Video quality score (0-1, currently placeholder)
        people_count: Average number of people detected in clip
    """
    path: str
    camera: str
    start_time: float
    duration: float
    audio_quality_score: float = 0.0
    video_quality_score: float = 0.0
    people_count: float = 0.0

    @property
    def end_time(self) -> float:
        """End time of clip in event timeline."""
        return self.start_time + self.duration

    def overlaps(self, start: float, end: float) -> bool:
        """Check if clip overlaps given time range."""
        return self.start_time < end and self.end_time > start

    def overlap_duration(self, start: float, end: float) -> float:
        """Calculate overlap duration with given time range."""
        overlap_start = max(self.start_time, start)
        overlap_end = min(self.end_time, end)
        return max(0.0, overlap_end - overlap_start)
```

### `CompositionSegment`
```python
@dataclass
class CompositionSegment:
    """
    Represents a segment of the final composition timeline.

    Attributes:
        camera: Camera identifier for this segment
        clip_path: Path to source video clip
        start_time: Start time in final composition (seconds from event start)
        duration: Segment duration in seconds
        source_start: Start position within source clip (seconds)
        needs_review: Flag indicating segment should be reviewed (multiple good options)
        speech_active: Whether speech is active during this segment
    """
    camera: str
    clip_path: str
    start_time: float
    duration: float
    source_start: float = 0.0
    needs_review: bool = False
    speech_active: bool = True

    @property
    def end_time(self) -> float:
        """End time in final composition."""
        return self.start_time + self.duration

    @property
    def source_end(self) -> float:
        """End position within source clip."""
        return self.source_start + self.duration

    def can_coalesce_with(self, other: 'CompositionSegment') -> bool:
        """
        Check if this segment can be merged with another adjacent segment.

        Segments can be merged if they:
        - Are from the same clip
        - Are contiguous in the composition timeline
        - Are contiguous in the source clip
        """
        if self.clip_path != other.clip_path:
            return False

        # Check if adjacent in composition timeline
        time_adjacent = abs(self.end_time - other.start_time) < 0.001

        # Check if contiguous in source
        source_adjacent = abs(self.source_end - other.source_start) < 0.001

        return time_adjacent and source_adjacent
```

### `QualityMetrics`
```python
@dataclass
class QualityMetrics:
    """
    Raw audio quality metrics extracted from FFmpeg analysis.

    All dB values are negative (quieter = more negative).
    """
    rms_db: float  # RMS level in dB (typical range: -60 to 0)
    peak_db: float  # Peak level in dB (typical range: -20 to 0)
    noise_floor_db: float  # Minimum RMS level (typical range: -80 to -40)
    clipping_count: int  # Number of samples at max amplitude
    duration: float  # Analyzed duration in seconds

    @property
    def dynamic_range_db(self) -> float:
        """Calculate dynamic range (difference between RMS and noise floor)."""
        return abs(self.noise_floor_db - self.rms_db)

    @property
    def clipping_rate(self) -> float:
        """Clipping events per second."""
        return self.clipping_count / max(1.0, self.duration)
```

### `QualityScore`
```python
@dataclass
class QualityScore:
    """
    Normalized audio quality score with component breakdown.

    All scores are in range [0, 1] where 1 = best quality.
    """
    overall: float  # Weighted combination of component scores
    rms_score: float  # Score for RMS level (too quiet or too loud = bad)
    peak_score: float  # Score for peak level (clipping = bad)
    noise_score: float  # Score for noise floor (low dynamic range = bad)
    clip_score: float  # Score for clipping (any clipping = bad)

    def __post_init__(self):
        """Validate all scores are in valid range."""
        for field_name in ['overall', 'rms_score', 'peak_score', 'noise_score', 'clip_score']:
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1, got {value}")
```

### `AlignmentResult`
```python
@dataclass
class AlignmentResult:
    """
    Per-clip audio alignment result.

    Attributes:
        clip_path: Path to aligned clip
        offset_seconds: Time shift to apply (positive = clip is behind reference)
        confidence: Confidence score (0-1) based on correlation strength
        reference_clip: Path to reference clip used for alignment
        drift_rate: Estimated clock drift rate (seconds per second), if applicable
    """
    clip_path: str
    offset_seconds: float
    confidence: float
    reference_clip: str
    drift_rate: Optional[float] = None

    def apply_to_clip(self, clip: CameraClip) -> None:
        """Apply alignment offset to clip's start_time."""
        clip.start_time = max(0.0, clip.start_time + self.offset_seconds)
```

### `SpeechSegment`
```python
@dataclass
class SpeechSegment:
    """
    Speech segment with speaker identification.

    Times are relative to event start (after alignment).
    """
    start: float  # Start time in seconds
    end: float  # End time in seconds
    speaker: str  # Speaker label (e.g., "SPEAKER_00")
    text: Optional[str] = None  # Transcribed text (if available)

    @property
    def duration(self) -> float:
        """Duration of speech segment."""
        return self.end - self.start

    def overlaps(self, start: float, end: float) -> bool:
        """Check if segment overlaps given time range."""
        return self.start < end and self.end > start
```

---

## 3. Quality Scoring Module (`quality_scoring.py`)

### `QualityAnalyzer` (Protocol)
```python
from typing import Protocol

class QualityAnalyzer(Protocol):
    """
    Interface for audio/video quality analysis implementations.

    Implementations must provide both raw metric extraction and scoring.
    """

    def analyze(self, video_path: str) -> QualityMetrics:
        """
        Analyze audio/video file and extract raw quality metrics.

        Args:
            video_path: Absolute path to video file

        Returns:
            QualityMetrics with raw measurements

        Raises:
            FileNotFoundError: If video file doesn't exist
            ValueError: If video has no audio stream
            subprocess.TimeoutExpired: If analysis takes too long
        """
        ...

    def score(
        self,
        metrics: QualityMetrics,
        weights: AudioQualityWeights
    ) -> QualityScore:
        """
        Convert raw metrics to normalized quality score.

        Args:
            metrics: Raw quality metrics from analyze()
            weights: Weights for combining component scores

        Returns:
            QualityScore with overall and component scores (all 0-1)
        """
        ...
```

### `FFmpegAudioQualityAnalyzer`
```python
class FFmpegAudioQualityAnalyzer:
    """
    Analyzes audio quality using FFmpeg's astats filter.

    Extracts RMS level, peak level, noise floor, and clipping count.
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize analyzer.

        Args:
            timeout: Maximum seconds to wait for FFmpeg analysis
        """
        self.timeout = timeout
        self._cache: Dict[str, QualityMetrics] = {}

    def analyze(self, video_path: str) -> QualityMetrics:
        """
        Analyze audio quality of video file.

        Runs: ffmpeg -i <video> -af astats=metadata=1 -f null -
        Parses stderr for audio statistics.

        Returns:
            QualityMetrics with extracted measurements

        Example:
            >>> analyzer = FFmpegAudioQualityAnalyzer()
            >>> metrics = analyzer.analyze("clip.mp4")
            >>> print(f"RMS: {metrics.rms_db:.1f} dB")
        """
        ...

    def score(
        self,
        metrics: QualityMetrics,
        weights: AudioQualityWeights
    ) -> QualityScore:
        """
        Convert metrics to normalized scores.

        Scoring logic:
        - RMS: Penalize too quiet (<-60dB) or too loud (>-20dB)
        - Peak: Penalize approaching 0dB (risk of clipping)
        - Noise: Reward high dynamic range (RMS - noise_floor)
        - Clip: Penalize any clipping events

        Returns:
            QualityScore with weighted overall score
        """
        ...

    def clear_cache(self) -> None:
        """Clear analysis cache (useful for testing/retries)."""
        self._cache.clear()
```

### `CachedQualityAnalyzer` (Decorator)
```python
class CachedQualityAnalyzer:
    """
    Wraps a QualityAnalyzer with persistent caching.

    Caches results to disk to avoid re-analyzing same files.
    """

    def __init__(
        self,
        analyzer: QualityAnalyzer,
        cache_dir: Optional[str] = None
    ):
        """
        Initialize caching wrapper.

        Args:
            analyzer: Underlying analyzer to wrap
            cache_dir: Directory for cache files (None = no caching)
        """
        self.analyzer = analyzer
        self.cache_dir = cache_dir
        self._cache: Dict[str, QualityMetrics] = {}

        if cache_dir:
            self._load_cache()

    def analyze(self, video_path: str) -> QualityMetrics:
        """
        Analyze with caching.

        Cache key is based on file path + modification time.
        """
        cache_key = self._make_cache_key(video_path)

        if cache_key in self._cache:
            return self._cache[cache_key]

        metrics = self.analyzer.analyze(video_path)
        self._cache[cache_key] = metrics

        if self.cache_dir:
            self._save_cache()

        return metrics

    def score(
        self,
        metrics: QualityMetrics,
        weights: AudioQualityWeights
    ) -> QualityScore:
        """Score using underlying analyzer (no caching needed)."""
        return self.analyzer.score(metrics, weights)
```

---

## 4. Alignment Engine (`alignment_engine.py`)

### `AlignmentEngine`
```python
class AlignmentEngine:
    """
    Manages audio alignment computation, caching, and application.

    Uses GCC-PHAT cross-correlation to estimate time offsets between clips.
    """

    def __init__(
        self,
        config: AlignmentConfig,
        cache_dir: Optional[str] = None
    ):
        """
        Initialize alignment engine.

        Args:
            config: Alignment configuration (window size, sample rate, etc.)
            cache_dir: Directory for caching alignment results
        """
        self.config = config
        self.cache_dir = cache_dir
        self._cache: Dict[str, AlignmentResult] = {}

        if cache_dir:
            self._load_cache()

    def align_clips(
        self,
        clips: List[CameraClip],
        reference: Optional[CameraClip] = None
    ) -> Dict[str, AlignmentResult]:
        """
        Compute alignment offsets for all clips relative to reference.

        Args:
            clips: List of camera clips to align
            reference: Reference clip (if None, uses clip with best audio quality)

        Returns:
            Mapping of clip_path -> AlignmentResult

        Example:
            >>> engine = AlignmentEngine(AlignmentConfig())
            >>> results = engine.align_clips(clips)
            >>> for path, result in results.items():
            ...     print(f"{path}: offset={result.offset_seconds:.3f}s, conf={result.confidence:.2f}")
        """
        if not clips:
            return {}

        if not self.config.enabled:
            # Return zero offsets if alignment disabled
            return {clip.path: AlignmentResult(
                clip_path=clip.path,
                offset_seconds=0.0,
                confidence=1.0,
                reference_clip=clip.path
            ) for clip in clips}

        # Select reference (best audio quality if not specified)
        if reference is None:
            reference = max(clips, key=lambda c: c.audio_quality_score)

        results = {reference.path: AlignmentResult(
            clip_path=reference.path,
            offset_seconds=0.0,
            confidence=1.0,
            reference_clip=reference.path
        )}

        # Align each clip to reference
        for clip in clips:
            if clip.path == reference.path:
                continue

            # Check cache
            cache_key = self._make_cache_key(reference.path, clip.path)
            if cache_key in self._cache:
                results[clip.path] = self._cache[cache_key]
                continue

            # Compute alignment
            result = self._align_clip_pair(reference, clip)
            results[clip.path] = result
            self._cache[cache_key] = result

        if self.cache_dir:
            self._save_cache()

        return results

    def _align_clip_pair(
        self,
        reference: CameraClip,
        target: CameraClip
    ) -> AlignmentResult:
        """
        Align target clip to reference using GCC-PHAT.

        Delegates to av_alignment.estimate_per_clip_offsets() internally.
        """
        # Find overlap window
        overlap_start = max(reference.start_time, target.start_time)
        overlap_end = min(reference.end_time, target.end_time)
        overlap_duration = overlap_end - overlap_start

        if overlap_duration < 5.0:
            # Insufficient overlap, return zero offset with low confidence
            return AlignmentResult(
                clip_path=target.path,
                offset_seconds=0.0,
                confidence=0.0,
                reference_clip=reference.path
            )

        # Use av_alignment module (existing GCC-PHAT implementation)
        from blink_pipeline.av_alignment import estimate_offset_single_pair

        offset, confidence = estimate_offset_single_pair(
            ref_path=reference.path,
            target_path=target.path,
            window_seconds=min(self.config.analysis_window_seconds, overlap_duration),
            max_shift=self.config.max_shift_seconds,
            sample_rate=self.config.sample_rate,
            bandpass=self.config.bandpass,
            hp=self.config.highpass_hz,
            lp=self.config.lowpass_hz
        )

        return AlignmentResult(
            clip_path=target.path,
            offset_seconds=offset,
            confidence=confidence,
            reference_clip=reference.path
        )

    def apply_offsets(
        self,
        clips: List[CameraClip],
        results: Dict[str, AlignmentResult]
    ) -> None:
        """
        Apply alignment offsets to clip start times (in-place).

        Args:
            clips: List of clips to adjust
            results: Alignment results from align_clips()

        Example:
            >>> engine.apply_offsets(clips, results)
            >>> # clips now have adjusted start_time values
        """
        for clip in clips:
            if clip.path in results:
                result = results[clip.path]
                if abs(result.offset_seconds) > 1e-6:
                    clip.start_time = max(0.0, clip.start_time + result.offset_seconds)
```

---

## 5. Timeline Generator (`timeline_generator.py`)

### `TimelineStrategy` (Abstract Base)
```python
from abc import ABC, abstractmethod
from typing import List, Optional

class TimelineStrategy(ABC):
    """
    Base class for camera selection strategies.

    Strategies implement the logic for choosing which camera to use
    for a given time segment based on available clips and context.
    """

    @abstractmethod
    def select_camera(
        self,
        segment_start: float,
        segment_end: float,
        available_clips: List[CameraClip],
        context: 'TimelineContext'
    ) -> CameraClip:
        """
        Select best camera for given time segment.

        Args:
            segment_start: Segment start time in event timeline
            segment_end: Segment end time in event timeline
            available_clips: Clips that overlap this segment
            context: Additional context (speech data, previous selections, etc.)

        Returns:
            Selected CameraClip for this segment

        Raises:
            ValueError: If no clips available
        """
        ...
```

### `TimelineContext`
```python
@dataclass
class TimelineContext:
    """
    Context passed to strategy during timeline generation.

    Provides access to speech data, previous selections, and other
    state needed for intelligent camera selection.
    """
    speech_segments: List[SpeechSegment] = field(default_factory=list)
    previous_segment: Optional[CompositionSegment] = None
    people_detector: Optional['PeopleDetector'] = None
    people_cache: Dict[Tuple[str, int], int] = field(default_factory=dict)

    def has_speech(self, start: float, end: float) -> bool:
        """Check if any speech segment overlaps time range."""
        return any(seg.overlaps(start, end) for seg in self.speech_segments)

    def get_people_count(
        self,
        clip: CameraClip,
        event_time: float
    ) -> int:
        """
        Get people count for clip at given time (cached).

        Args:
            clip: Clip to analyze
            event_time: Time in event timeline

        Returns:
            Number of people detected (from cache or fresh detection)
        """
        if self.people_detector is None:
            return 0

        # Check cache
        cache_key = (clip.path, int(round(event_time)))
        if cache_key in self.people_cache:
            return self.people_cache[cache_key]

        # Compute and cache
        rel_time = event_time - clip.start_time
        count = self.people_detector.count_people_at_time(clip.path, rel_time)
        self.people_cache[cache_key] = count

        return count
```

### Strategy Implementations

#### `AudioQualityStrategy`
```python
class AudioQualityStrategy(TimelineStrategy):
    """Always select camera with best audio quality."""

    def select_camera(
        self,
        segment_start: float,
        segment_end: float,
        available_clips: List[CameraClip],
        context: TimelineContext
    ) -> CameraClip:
        """Return clip with highest audio_quality_score."""
        if not available_clips:
            raise ValueError("No clips available for segment")
        return max(available_clips, key=lambda c: c.audio_quality_score)
```

#### `TimeBasedStrategy`
```python
class TimeBasedStrategy(TimelineStrategy):
    """
    Prefer continuity (keep same camera) unless clip ends.

    Falls back to best audio quality when switching is necessary.
    """

    def select_camera(
        self,
        segment_start: float,
        segment_end: float,
        available_clips: List[CameraClip],
        context: TimelineContext
    ) -> CameraClip:
        """
        Select camera preferring continuity with previous segment.
        """
        if not available_clips:
            raise ValueError("No clips available")

        # Try to continue previous clip if still available
        if context.previous_segment:
            prev_path = context.previous_segment.clip_path
            continuing = [c for c in available_clips if c.path == prev_path]
            if continuing:
                return continuing[0]

        # Switch to best audio quality
        return max(available_clips, key=lambda c: c.audio_quality_score)
```

#### `SpeechPeopleStrategy`
```python
class SpeechPeopleStrategy(TimelineStrategy):
    """
    Speech-aware strategy:
    - During speech: Use best audio quality
    - During silence: Use camera with most people
    """

    def __init__(self, min_people: int = 1):
        """
        Initialize strategy.

        Args:
            min_people: Minimum people count to consider clip "has people"
        """
        self.min_people = min_people

    def select_camera(
        self,
        segment_start: float,
        segment_end: float,
        available_clips: List[CameraClip],
        context: TimelineContext
    ) -> CameraClip:
        """
        Select based on speech presence.
        """
        if not available_clips:
            raise ValueError("No clips available")

        # Check for speech
        has_speech = context.has_speech(segment_start, segment_end)

        if has_speech:
            # During speech, use best audio
            return max(available_clips, key=lambda c: c.audio_quality_score)
        else:
            # During silence, use camera with most people
            sample_time = segment_start + (segment_end - segment_start) / 2

            # Get people counts for all clips
            people_counts = {
                clip: context.get_people_count(clip, sample_time)
                for clip in available_clips
            }

            # Filter to clips with enough people
            clips_with_people = [
                c for c in available_clips
                if people_counts[c] >= self.min_people
            ]

            if clips_with_people:
                # Choose clip with most people
                return max(clips_with_people, key=lambda c: people_counts[c])
            else:
                # Fallback to best audio if no one visible
                return max(available_clips, key=lambda c: c.audio_quality_score)
```

### `TimelineGenerator`
```python
class TimelineGenerator:
    """
    Generates video and audio timelines using pluggable strategies.

    Handles boundary creation, segment generation, and coalescing.
    """

    def __init__(
        self,
        video_strategy: TimelineStrategy,
        audio_strategy: TimelineStrategy
    ):
        """
        Initialize generator with strategies.

        Args:
            video_strategy: Strategy for selecting video camera
            audio_strategy: Strategy for selecting audio source
        """
        self.video_strategy = video_strategy
        self.audio_strategy = audio_strategy

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None,
        people_detector: Optional['PeopleDetector'] = None
    ) -> Tuple[List[CompositionSegment], List[CompositionSegment]]:
        """
        Generate video and audio timelines.

        Args:
            clips: Analyzed camera clips (with quality scores)
            speech_segments: Optional speech segments for speech-aware strategies
            people_detector: Optional people detector for visual strategies

        Returns:
            (video_timeline, audio_timeline) as lists of CompositionSegments

        Example:
            >>> generator = TimelineGenerator(
            ...     video_strategy=AudioQualityStrategy(),
            ...     audio_strategy=AudioQualityStrategy()
            ... )
            >>> video_timeline, audio_timeline = generator.generate(clips)
        """
        if not clips:
            return [], []

        # Create boundaries from clip start/end times
        boundaries = self._create_boundaries(clips)

        # Initialize context
        context = TimelineContext(
            speech_segments=speech_segments or [],
            people_detector=people_detector
        )

        video_timeline: List[CompositionSegment] = []
        audio_timeline: List[CompositionSegment] = []

        # Generate segments
        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]

            if seg_end <= seg_start:
                continue

            # Find available clips
            available = [
                c for c in clips
                if c.overlaps(seg_start, seg_end)
            ]

            if not available:
                continue

            # Select cameras
            video_clip = self.video_strategy.select_camera(
                seg_start, seg_end, available, context
            )
            audio_clip = self.audio_strategy.select_camera(
                seg_start, seg_end, available, context
            )

            # Create segments
            video_seg = self._make_segment(video_clip, seg_start, seg_end)
            audio_seg = self._make_segment(audio_clip, seg_start, seg_end)

            # Mark if needs review (multiple good options during silence)
            if isinstance(self.video_strategy, SpeechPeopleStrategy):
                if not context.has_speech(seg_start, seg_end):
                    people_counts = [
                        context.get_people_count(c, (seg_start + seg_end) / 2)
                        for c in available
                    ]
                    multiple_good = sum(
                        1 for count in people_counts
                        if count >= self.video_strategy.min_people
                    ) >= 2
                    if multiple_good:
                        video_seg.needs_review = True

            video_timeline.append(video_seg)
            audio_timeline.append(audio_seg)

            # Update context
            context.previous_segment = video_seg

        # Coalesce adjacent segments from same clip
        video_timeline = self._coalesce_segments(video_timeline)
        audio_timeline = self._coalesce_segments(audio_timeline)

        return video_timeline, audio_timeline

    @staticmethod
    def _create_boundaries(clips: List[CameraClip]) -> List[float]:
        """Create sorted list of unique boundary times from clip starts/ends."""
        boundaries = {0.0}  # Always start at 0
        for clip in clips:
            boundaries.add(clip.start_time)
            boundaries.add(clip.end_time)
        return sorted(boundaries)

    @staticmethod
    def _make_segment(
        clip: CameraClip,
        seg_start: float,
        seg_end: float
    ) -> CompositionSegment:
        """Create composition segment from clip and time range."""
        source_start = max(0.0, seg_start - clip.start_time)
        duration = seg_end - seg_start

        return CompositionSegment(
            camera=clip.camera,
            clip_path=clip.path,
            start_time=seg_start,
            duration=duration,
            source_start=source_start
        )

    @staticmethod
    def _coalesce_segments(
        segments: List[CompositionSegment]
    ) -> List[CompositionSegment]:
        """Merge adjacent segments from same clip."""
        if not segments:
            return []

        coalesced = [segments[0]]

        for seg in segments[1:]:
            last = coalesced[-1]
            if last.can_coalesce_with(seg):
                # Merge by extending last segment
                last.duration += seg.duration
            else:
                coalesced.append(seg)

        return coalesced
```

---

## 6. Composition Renderer (`composition_renderer.py`)

### `CompositionRenderer` (Abstract Base)
```python
from abc import ABC, abstractmethod

class CompositionRenderer(ABC):
    """
    Base class for rendering final composition from timelines.

    Subclasses implement different rendering approaches (single-pass, multi-pass, etc.).
    """

    @abstractmethod
    def render(
        self,
        video_timeline: List[CompositionSegment],
        audio_timeline: List[CompositionSegment],
        output_path: str,
        event_start: Optional[datetime] = None
    ) -> bool:
        """
        Render final composition to output file.

        Args:
            video_timeline: Video segment timeline
            audio_timeline: Audio segment timeline
            output_path: Path for output video file
            event_start: Event start datetime (for timestamp overlay)

        Returns:
            True if rendering succeeded, False otherwise

        Raises:
            subprocess.CalledProcessError: If FFmpeg fails
            OSError: If output path is not writable
        """
        ...
```

### `SinglePassRenderer`
```python
class SinglePassRenderer(CompositionRenderer):
    """
    Modern single-pass filter_complex renderer.

    Builds a single FFmpeg command with filter graph for:
    - Video trimming and concatenation
    - Audio trimming and crossfading
    - Timestamp overlay

    Faster and more efficient than multi-pass approach.
    """

    def __init__(
        self,
        config: CompositionConfig,
        audio_processor: 'AudioProcessor',
        overlay_generator: 'OverlayGenerator'
    ):
        """
        Initialize renderer.

        Args:
            config: Composition configuration
            audio_processor: Audio processing module
            overlay_generator: Overlay generation module
        """
        self.config = config
        self.audio_processor = audio_processor
        self.overlay_generator = overlay_generator

    def render(
        self,
        video_timeline: List[CompositionSegment],
        audio_timeline: List[CompositionSegment],
        output_path: str,
        event_start: Optional[datetime] = None
    ) -> bool:
        """
        Render using single-pass filter_complex.

        Example filter graph:
        ```
        [0:v]trim=0:5,setpts=PTS-STARTPTS[v0];
        [1:v]trim=5:10,setpts=PTS-STARTPTS[v1];
        [v0][v1]concat=n=2:v=1:a=0[vout];
        [0:a]atrim=0:5,asetpts=PTS-STARTPTS[a0];
        [1:a]atrim=5:10,asetpts=PTS-STARTPTS[a1];
        [a0][a1]acrossfade=d=0.06[aout]
        ```
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build input list (unique clip paths)
            input_map = self._build_input_map(video_timeline, audio_timeline)

            # Generate overlay if needed
            overlay_path = None
            if self.config.timestamp_overlay_enabled and event_start:
                overlay_path = self.overlay_generator.generate_ass(
                    video_timeline,
                    event_start,
                    tmpdir
                )

            # Build filter graph
            filter_complex = self._build_filter_graph(
                video_timeline,
                audio_timeline,
                input_map,
                overlay_path
            )

            # Execute FFmpeg
            return self._execute_ffmpeg(
                input_map,
                filter_complex,
                output_path
            )

    def _build_filter_graph(
        self,
        video_timeline: List[CompositionSegment],
        audio_timeline: List[CompositionSegment],
        input_map: Dict[str, int],
        overlay_path: Optional[str]
    ) -> str:
        """
        Build complete filter_complex graph.

        Returns:
            Filter graph string for FFmpeg -filter_complex parameter
        """
        filters: List[str] = []

        # Video processing
        video_labels = []
        for i, seg in enumerate(video_timeline):
            input_idx = input_map[seg.clip_path]
            start = seg.source_start
            end = seg.source_start + seg.duration

            # Trim and reset PTS
            filters.append(
                f"[{input_idx}:v]trim=start={start}:end={end},"
                f"setpts=PTS-STARTPTS[v{i}]"
            )
            video_labels.append(f"[v{i}]")

        # Concatenate video
        video_out = "vout"
        if len(video_labels) > 1:
            filters.append(
                f"{''.join(video_labels)}concat=n={len(video_labels)}:v=1:a=0[{video_out}]"
            )
        else:
            video_out = "v0"

        # Apply overlay if needed
        if overlay_path:
            escaped_path = overlay_path.replace('\\', r'\\').replace("'", r"\'")
            filters.append(
                f"[{video_out}]subtitles='{escaped_path}'[vfinal]"
            )
            video_out = "vfinal"

        # Audio processing
        audio_labels = []
        for i, seg in enumerate(audio_timeline):
            input_idx = input_map[seg.clip_path]
            start = seg.source_start
            end = seg.source_start + seg.duration

            # Trim and reset PTS
            filters.append(
                f"[{input_idx}:a]atrim=start={start}:end={end},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
            audio_labels.append(f"[a{i}]")

        # Concatenate/crossfade audio
        audio_out = "aout"
        if len(audio_labels) == 1:
            audio_out = "a0"
        elif self.config.audio_crossfade_seconds > 0:
            # Build crossfade chain
            cf = self.config.audio_crossfade_seconds
            if len(audio_labels) == 2:
                filters.append(
                    f"{audio_labels[0]}{audio_labels[1]}acrossfade=d={cf}[{audio_out}]"
                )
            else:
                # Multi-segment crossfade
                last = "a01"
                filters.append(
                    f"{audio_labels[0]}{audio_labels[1]}acrossfade=d={cf}[{last}]"
                )
                for i in range(2, len(audio_labels)):
                    next_label = f"a{i}{i+1}" if i < len(audio_labels)-1 else audio_out
                    filters.append(
                        f"[{last}]{audio_labels[i]}acrossfade=d={cf}[{next_label}]"
                    )
                    last = next_label
        else:
            # Simple concat without crossfade
            filters.append(
                f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[{audio_out}]"
            )

        return '; '.join(filters)
```

---

## Summary

This interface specification provides:

1. **Type-Safe Configuration**: Pydantic models with validation
2. **Clear Data Models**: Dataclasses for clips, segments, quality metrics
3. **Extensible Strategies**: Abstract base classes for swappable algorithms
4. **Testable Components**: Protocols enable mocking and unit testing
5. **Comprehensive Documentation**: Docstrings with examples for all public APIs

**Next Steps:**
1. Implement each module following these interfaces
2. Write unit tests against the interfaces
3. Create integration tests for full pipeline
4. Measure performance and optimize bottlenecks
