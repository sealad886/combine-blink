# Multi-Camera Composer Architecture Analysis

## Executive Summary

The `multi_camera_composer.py` module is a **1772-line monolithic composition engine** that orchestrates multi-camera video composition with intelligent camera switching, audio alignment, quality scoring, and FFmpeg video generation. While functionally sophisticated, the current architecture creates significant technical debt for a production release:

- **Tight Coupling**: Quality analysis, alignment, timeline generation, and FFmpeg encoding are intermingled
- **Testing Complexity**: Hard to unit test individual algorithms without running full FFmpeg processes
- **Configuration Sprawl**: 50+ configuration parameters parsed across 200+ lines of `__init__`
- **Code Duplication**: Multiple FFmpeg generation paths (single-pass, multi-pass, simple merge)
- **Extensibility Issues**: Adding new switching strategies or quality metrics requires deep knowledge of the entire system

**Recommendation**: Refactor into 8 modular components with clear interfaces, maintaining 100% backward compatibility through a facade pattern.

---

## Current Architecture Deep Dive

### 1. Monolithic Structure Overview

```
MultiCameraComposer (1772 lines)
├── Initialization (200 lines) - Configuration parsing
├── Entry Point (50 lines) - compose_multi_camera_event()
├── Analysis Phase (400 lines)
│   ├── Audio quality scoring (150 lines)
│   ├── People detection integration (100 lines)
│   ├── Audio alignment estimation (150 lines)
├── Timeline Generation (450 lines)
│   ├── Boundary creation (50 lines)
│   ├── Strategy selection (200 lines)
│   ├── Speech-aware switching (100 lines)
│   ├── Segment coalescing (50 lines)
│   ├── Legacy timeline methods (50 lines)
├── FFmpeg Generation (600 lines)
│   ├── Single-pass filter_complex (300 lines)
│   ├── Multi-pass composition (250 lines)
│   ├── Audio cleanup/crossfade (50 lines)
└── Utilities (72 lines)
    ├── Speech segment loading
    ├── Frame extraction
    ├── Subtitle generation
```

### 2. Responsibilities Analysis

#### 2.1 Configuration Management (Lines 1-220)
**Current Pain Points:**
- 50+ parameters parsed in `__init__`
- Complex conditional logic based on switching strategy
- No validation or schema
- Defaults scattered throughout code

**Dependencies:**
- Uses config dict directly
- No type safety
- Hard to document which parameters affect which features

**What It Does Right:**
- Centralizes all config in one place
- Uses sensible defaults

#### 2.2 Audio Quality Analysis (Lines 650-870)
**Current Pain Points:**
- `_calculate_audio_quality()`: 220 lines of FFmpeg parsing logic
- Regex-based extraction of audio stats
- Weighted scoring calculation mixed with parsing
- No caching of results (re-analyzes on retry)

**Algorithm:**
1. Run `ffmpeg -af astats` on full clip
2. Parse stderr for RMS, peak, noise floor, clipping metrics
3. Normalize each metric to 0-1 scale
4. Apply weighted combination
5. Return composite score

**Dependencies:**
- FFmpeg subprocess execution
- Media info from probe
- Configuration weights

**What It Does Right:**
- Multi-metric quality assessment
- Configurable weighting
- Robust error handling with fallback scores

#### 2.3 Audio Alignment (Lines 401-550)
**Current Pain Points:**
- Two different alignment methods:
  - `_estimate_alignment_offsets()`: Per-camera alignment (deprecated)
  - Per-clip alignment via `estimate_per_clip_offsets()` from `av_alignment.py`
- Audio extraction logic duplicated (`_extract_audio_segment()`)
- Alignment results stored in instance variables mixed with config
- Hard to test without real video files

**Algorithm (per-clip):**
1. Select reference clip (best audio quality)
2. For each other clip:
   - Find overlap window with reference
   - Extract audio segments (16kHz, bandpass filtered)
   - Compute GCC-PHAT cross-correlation
   - Find lag offset (bounded by max_shift_seconds)
3. Adjust clip start_time by offset

**Dependencies:**
- `av_alignment.py` module (GCC-PHAT implementation)
- FFmpeg for audio extraction
- NumPy for signal processing

**What It Does Right:**
- Uses proven GCC-PHAT algorithm
- Handles overlapping clips robustly
- Bounds offsets to prevent unrealistic shifts

#### 2.4 People Detection (Lines 230-310, 597-649)
**Current Pain Points:**
- Lazy initialization of Hugging Face detector
- Cache stored in instance variable dict
- Frame extraction via FFmpeg subprocess
- No batch processing (extracts one frame at a time)
- Detection only enabled for `speech_people` strategy

**Algorithm:**
1. Check if people detection needed (strategy + config)
2. Lazy load Hugging Face YOLOS/DETR model
3. For each segment needing evaluation:
   - Extract frame at segment midpoint
   - Run object detection
   - Count people above threshold
4. Cache results by (clip_path, timestamp)

**Dependencies:**
- `people_detection.py` module (Hugging Face wrapper)
- PIL for image handling
- FFmpeg for frame extraction

**What It Does Right:**
- Lazy loading avoids model load when not needed
- Caching prevents duplicate detection
- Configurable model and threshold

#### 2.5 Timeline Generation (Lines 912-1150)
**Current Pain Points:**
- `_generate_aligned_timelines()`: 250 lines handling ALL strategies
- Boundary creation, strategy selection, speech awareness, people detection all in one method
- Legacy timeline methods (`_timeline_time_based`, `_timeline_round_robin`) partially unused
- Segment coalescing logic duplicated for video and audio

**Algorithm (overlap-aligned):**
1. **Boundary Creation**: Collect all clip start/end times into sorted list
2. **Segmentation**: For each interval between boundaries:
   - Find available clips (overlap segment)
   - Apply strategy selection (see 2.5.1)
   - Create video segment with camera choice
   - Create audio segment with separate selection logic
3. **Coalescing**: Merge adjacent segments with same source
4. Return separate video and audio timelines

**2.5.1 Strategy Selection Logic:**

| Strategy | Video Selection | Audio Selection |
|----------|----------------|-----------------|
| `time_based` | Prefer continuity (same clip as last), else best audio | Best quality or per config |
| `round_robin` | Cycle through cameras equally | Best quality |
| `audio_quality` | Camera with best audio score | Best quality |
| `speech_people` | **Complex multi-criteria** | Best quality |

**Speech-People Strategy (Most Complex):**
- Check if segment has speech (from diarization)
- **During speech**: Use best audio quality camera
- **No speech**:
  - Run people detection at segment midpoint for all cameras
  - Filter to cameras with >= min_count people
  - Choose camera with most people
  - Mark segment as `needs_review` if multiple cameras have people

**Dependencies:**
- Speech segment data (from transcription stage)
- People detection results (on-demand)
- Audio quality scores (from analysis)
- Configuration (strategy, intervals, thresholds)

**What It Does Right:**
- Elegant boundary-based segmentation
- Separate video/audio timeline generation
- Coalescing reduces unnecessary cuts

#### 2.6 Speech Segment Integration (Lines 610-730)
**Current Pain Points:**
- `_load_speech_segments()`: 120 lines of timeline mapping logic
- Converts diarization segments to event time
- Complex cursor logic to map through clip timeline
- Interval merging duplicated

**Algorithm:**
1. Load speech segments (start/end times with speaker)
2. If speech_timeline provided:
   - Map each segment to event time via clip timeline
   - Handle cursor advancement across clip boundaries
3. Merge overlapping intervals
4. Store as `_speech_segments_event`

**Dependencies:**
- Diarization output from transcription
- Clip timeline from transcription
- Camera clip list for timing

**What It Does Right:**
- Correctly handles multi-clip transcription
- Robust interval merging

#### 2.7 FFmpeg Generation (Lines 1150-1772)
**Current Pain Points:**
- **Two complete composition paths**:
  - `_create_composite_video_single_pass()`: 400 lines - Modern filter_complex
  - `_create_composite_video()`: 200 lines - Legacy multi-pass
- Configuration toggle (`single_pass_filter_complex`)
- Different audio handling (crossfade vs concat)
- Overlay generation mixed with encoding
- Timestamp ASS generation (150 lines)

**Single-Pass Algorithm:**
1. Build input list (unique clip paths)
2. Probe video dimensions from reference
3. Generate timestamp ASS subtitle file (optional)
4. Build filter_complex graph:
   - Video: `trim → setpts → scale → concat`
   - Audio: `atrim → crossfade chain`
   - Overlay: `subtitles` filter (if enabled)
5. Run single ffmpeg command with complex filter
6. Encode with configured codec (h264/videotoolbox)

**Multi-Pass Algorithm (Legacy):**
1. Extract and concatenate video segments (concat demuxer)
2. Generate timestamp overlay as separate subtitle file
3. Extract audio segments with cleanup filters
4. Crossfade audio segments using filter_complex
5. Combine video + audio in final pass

**Dependencies:**
- FFmpeg subprocess execution
- Temp directory for intermediate files
- Video probe utilities
- Audio cleanup filter generation

**What It Does Right:**
- Single-pass is efficient (one encode)
- Comprehensive error handling with fallbacks
- Hardware encoding support

#### 2.8 Simple Fallback Paths (Lines 1650-1772)
**What They Do:**
- `_simple_copy()`: Single clip → copy to output
- `_sequential_merge()`: Multiple clips same camera → concat
- `_sequential_merge_ffmpeg()`: FFmpeg-based concatenation

**When Used:**
- Single clip events
- Composition disabled
- All clips from same camera
- Error fallback

---

## Multi-Dimensional Optimization Problem

### The Core Challenge

Timeline generation is a **constrained optimization problem** with multiple competing objectives:

```python
# Objective: Maximize overall quality while minimizing jarring transitions
def quality_score(timeline):
    return (
        α * audio_quality_score(timeline) +
        β * visual_continuity_score(timeline) +
        γ * people_presence_score(timeline) +
        δ * speech_coverage_score(timeline) -
        ε * transition_penalty(timeline)
    )
```

**Constraints:**
1. **Temporal**: Must cover entire event duration without gaps
2. **Availability**: Can only use camera if clip overlaps timeline segment
3. **Continuity**: Prefer fewer camera switches (reduce transition_penalty)
4. **Speech-Aware**: During speech, prioritize audio quality
5. **Non-Speech**: During silence, prioritize visual interest (people)
6. **Review Marking**: Flag segments with multiple good options for manual review

### Why It's Complex

1. **Dynamic Boundaries**: Segment boundaries are created from clip start/end times, not fixed intervals
   - Number of segments = 2N - 1 (where N = number of clips) in worst case
   - Boundary times are data-dependent

2. **Strategy-Dependent Scoring**: Different strategies use different quality functions
   - `audio_quality`: Single metric (audio score)
   - `speech_people`: Conditional - audio during speech, people detection during silence
   - `time_based`: Continuity preference overrides quality

3. **Stateful Selection**: Some strategies maintain state across segments
   - `round_robin`: Camera index counter
   - `time_based`: Previous camera preference

4. **Lazy Evaluation**: People detection is expensive, only computed when needed
   - Not pre-computed for all clips
   - Cache grows dynamically during timeline generation

5. **Separate Audio/Video**: Must generate two independent timelines
   - Video timeline: Complex strategy-based selection
   - Audio timeline: Simpler best-quality selection
   - Can result in different segmentation patterns

### Current Approach: Greedy Segment-by-Segment

```python
for each boundary_interval:
    available_clips = clips_overlapping(interval)

    if strategy == 'speech_people':
        if has_speech(interval):
            selected = max(available_clips, key=audio_quality)
        else:
            people_clips = [c for c in available_clips if detect_people(c) >= threshold]
            selected = max(people_clips, key=people_count)
    elif strategy == 'audio_quality':
        selected = max(available_clips, key=audio_quality)
    # ... other strategies

    timeline.append(segment(selected, interval))
```

**Tradeoffs:**
- ✅ **Simple**: Easy to understand and implement
- ✅ **Fast**: O(N × M) where N=segments, M=avg clips per segment
- ❌ **Locally Optimal**: Doesn't consider global transition costs
- ❌ **No Lookahead**: Can't anticipate better options in next segment

### Alternative Approaches (Not Implemented)

**1. Dynamic Programming:**
```python
dp[segment][camera] = max(
    quality(segment, camera) + dp[segment-1][prev_camera] - transition_cost(prev_camera, camera)
    for prev_camera in available_cameras(segment-1)
)
```
- ✅ Globally optimal
- ❌ O(N × M²) complexity
- ❌ Requires pre-computing people detection for all possibilities

**2. Greedy with Lookahead:**
```python
selected = max(
    available_clips,
    key=lambda c: quality(current, c) + α * expected_future_quality(next_segment, c)
)
```
- ✅ Balances current and future quality
- ❌ More complex
- ❌ Still locally optimal

**3. Post-Processing Optimization:**
```python
timeline = greedy_generate()
timeline = smooth_transitions(timeline)  # Merge short segments, reduce rapid switching
timeline = optimize_boundaries(timeline)  # Adjust segment boundaries for better cuts
```
- ✅ Can improve greedy result
- ✅ Separates concerns
- ❌ May miss better global solutions

---

## Pain Points Summary

### Critical Issues for Production

1. **Testability**:
   - Can't unit test timeline generation without FFmpeg, video files, ML models
   - Integration tests take minutes to run
   - Hard to reproduce edge cases

2. **Maintainability**:
   - Changes to timeline logic require understanding entire 1772-line module
   - Adding new strategy requires modifying core loop
   - Configuration changes ripple through codebase

3. **Performance**:
   - People detection done serially (could batch)
   - Audio quality analysis not cached across retries
   - No profiling/metrics for optimization bottlenecks

4. **Reliability**:
   - Fallback paths not well tested
   - Error handling inconsistent (some retry, some fail)
   - Temp file cleanup not guaranteed

5. **Observability**:
   - Limited logging of decision rationale
   - No metrics on quality scores, transition counts
   - Hard to debug "why did it choose this camera?"

### Technical Debt

- **Code Duplication**: Two complete FFmpeg generation paths (single-pass vs multi-pass)
- **Dead Code**: Legacy timeline methods partially unused
- **Global State**: Instance variables used for temporary computation state
- **Magic Numbers**: Hardcoded thresholds (5s overlap, 0.06s crossfade)
- **Mixed Concerns**: Audio cleanup filter generation in composer class

---

## Proposed Modular Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│               MultiCameraComposer (Facade)                  │
│          ┌───────────────────────────────────┐              │
│          │  Configuration (Pydantic Models)  │              │
│          └───────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Media        │   │  Quality     │   │  Alignment   │
│ Analysis     │   │  Scoring     │   │  Engine      │
│ (Probe/Info) │   │  Module      │   │  (GCC-PHAT)  │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌──────────────┐
                   │  Timeline    │
                   │  Generator   │
                   │  (Strategies)│
                   └──────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Composition  │   │  Audio       │   │  Overlay     │
│ Renderer     │   │  Processor   │   │  Generator   │
│ (FFmpeg)     │   │  (Cleanup)   │   │  (ASS/SRT)   │
└──────────────┘   └──────────────┘   └──────────────┘
```

### Module Breakdown

#### 1. Configuration Module (`composition_config.py`)
**Purpose**: Type-safe configuration with validation

```python
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional

class AudioQualityWeights(BaseModel):
    rms: float = Field(0.4, ge=0, le=1)
    peak: float = Field(0.2, ge=0, le=1)
    noise: float = Field(0.2, ge=0, le=1)
    clip: float = Field(0.2, ge=0, le=1)

    @validator('*')
    def validate_sum(cls, v, values):
        # Ensure weights sum to 1.0
        ...

class AlignmentConfig(BaseModel):
    enabled: bool = True
    max_shift_seconds: float = Field(1.5, gt=0, le=5.0)
    analysis_window_seconds: float = Field(12.0, gt=0)
    sample_rate: int = Field(16000, gt=0)
    bandpass: bool = True
    highpass_hz: int = Field(300, gt=0)
    lowpass_hz: int = Field(3000, gt=0)

class CompositionConfig(BaseModel):
    switching_strategy: Literal['time_based', 'round_robin', 'audio_quality', 'speech_people'] = 'time_based'
    switching_interval: float = Field(5.0, gt=0)
    audio_source: Literal['best_quality', 'first', 'longest', 'per_segment'] = 'best_quality'

    quality_weights: AudioQualityWeights = AudioQualityWeights()
    alignment: AlignmentConfig = AlignmentConfig()
    # ... other configs
```

**Benefits:**
- ✅ Type safety and IDE autocomplete
- ✅ Automatic validation
- ✅ JSON schema generation for docs
- ✅ Easy to extend with new parameters

#### 2. Quality Scoring Module (`quality_scoring.py`)
**Purpose**: Isolated audio/video quality analysis

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class QualityMetrics:
    """Raw metrics extracted from media analysis."""
    rms_db: float
    peak_db: float
    noise_floor_db: float
    clipping_count: int
    duration: float

@dataclass
class QualityScore:
    """Normalized quality score with component breakdown."""
    overall: float  # 0-1 composite score
    rms_score: float
    peak_score: float
    noise_score: float
    clip_score: float

class QualityAnalyzer(Protocol):
    """Interface for quality analysis implementations."""
    def analyze(self, video_path: str) -> QualityMetrics:
        ...

    def score(self, metrics: QualityMetrics, weights: AudioQualityWeights) -> QualityScore:
        ...

class FFmpegAudioQualityAnalyzer:
    """Analyzes audio quality using ffmpeg astats filter."""

    def analyze(self, video_path: str) -> QualityMetrics:
        # Extract current _calculate_audio_quality FFmpeg logic
        ...

    def score(self, metrics: QualityMetrics, weights: AudioQualityWeights) -> QualityScore:
        # Extract current scoring calculation
        ...
```

**Benefits:**
- ✅ Testable with mock metrics (no FFmpeg needed)
- ✅ Swappable implementations (could add ML-based scoring)
- ✅ Clear separation of extraction vs. scoring
- ✅ Cacheable results

#### 3. Alignment Engine (`alignment_engine.py`)
**Purpose**: Audio synchronization with caching

```python
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class AlignmentResult:
    """Per-clip alignment offset."""
    clip_path: str
    offset_seconds: float
    confidence: float  # 0-1 based on correlation strength
    reference_clip: str

class AlignmentEngine:
    """Manages audio alignment computation and caching."""

    def __init__(self, config: AlignmentConfig, cache_dir: Optional[str] = None):
        self.config = config
        self.cache = AlignmentCache(cache_dir) if cache_dir else None

    def align_clips(
        self,
        clips: List[CameraClip],
        reference: Optional[CameraClip] = None
    ) -> Dict[str, AlignmentResult]:
        """Compute alignment offsets for all clips relative to reference."""
        # Use av_alignment.py functions
        # Add caching layer
        # Return structured results with confidence
        ...

    def apply_offsets(self, clips: List[CameraClip], results: Dict[str, AlignmentResult]):
        """Adjust clip start times based on alignment results."""
        for clip in clips:
            if clip.path in results:
                clip.start_time += results[clip.path].offset_seconds
```

**Benefits:**
- ✅ Caching prevents re-computation
- ✅ Confidence scores for quality assessment
- ✅ Easy to test with synthetic audio
- ✅ Decoupled from timeline generation

#### 4. Timeline Generator (`timeline_generator.py`)
**Purpose**: Strategy-based timeline creation

```python
from abc import ABC, abstractmethod
from typing import List, Protocol

class TimelineStrategy(ABC):
    """Base class for timeline generation strategies."""

    @abstractmethod
    def select_camera(
        self,
        segment_start: float,
        segment_end: float,
        available_clips: List[CameraClip],
        context: 'TimelineContext'
    ) -> CameraClip:
        """Select best camera for given segment."""
        ...

class AudioQualityStrategy(TimelineStrategy):
    def select_camera(self, start, end, clips, context):
        return max(clips, key=lambda c: c.audio_quality_score)

class SpeechPeopleStrategy(TimelineStrategy):
    def __init__(self, speech_detector, people_detector, min_people=1):
        self.speech = speech_detector
        self.people = people_detector
        self.min_people = min_people

    def select_camera(self, start, end, clips, context):
        if self.speech.has_speech(start, end):
            return max(clips, key=lambda c: c.audio_quality_score)
        else:
            # People detection logic
            ...

class TimelineGenerator:
    """Generates video and audio timelines using pluggable strategies."""

    def __init__(self, video_strategy: TimelineStrategy, audio_strategy: TimelineStrategy):
        self.video_strategy = video_strategy
        self.audio_strategy = audio_strategy

    def generate(
        self,
        clips: List[CameraClip],
        speech_segments: Optional[List[SpeechSegment]] = None
    ) -> Tuple[List[CompositionSegment], List[CompositionSegment]]:
        """Generate video and audio timelines."""
        boundaries = self._create_boundaries(clips)

        video_timeline = []
        audio_timeline = []

        context = TimelineContext(speech_segments=speech_segments)

        for start, end in zip(boundaries[:-1], boundaries[1:]):
            available = self._clips_at_time(clips, start)

            video_clip = self.video_strategy.select_camera(start, end, available, context)
            audio_clip = self.audio_strategy.select_camera(start, end, available, context)

            video_timeline.append(self._make_segment(video_clip, start, end))
            audio_timeline.append(self._make_segment(audio_clip, start, end))

        video_timeline = self._coalesce_segments(video_timeline)
        audio_timeline = self._coalesce_segments(audio_timeline)

        return video_timeline, audio_timeline
```

**Benefits:**
- ✅ Strategy pattern enables easy extension
- ✅ Testable with mock clips (no people detection needed)
- ✅ Clear separation of boundary creation vs. selection
- ✅ Strategies can be composed/chained

#### 5. Composition Renderer (`composition_renderer.py`)
**Purpose**: FFmpeg filter graph generation and execution

```python
from abc import ABC, abstractmethod
from typing import List

class CompositionRenderer(ABC):
    """Base class for video composition rendering."""

    @abstractmethod
    def render(
        self,
        video_timeline: List[CompositionSegment],
        audio_timeline: List[CompositionSegment],
        output_path: str
    ) -> bool:
        """Render final composition to output file."""
        ...

class SinglePassRenderer(CompositionRenderer):
    """Modern single-pass filter_complex renderer."""

    def __init__(self, config: EncodingConfig, overlay_gen: OverlayGenerator):
        self.config = config
        self.overlay = overlay_gen

    def render(self, video_timeline, audio_timeline, output_path):
        filter_graph = self._build_filter_complex(video_timeline, audio_timeline)
        overlay_path = self.overlay.generate(video_timeline) if self.config.overlay_enabled else None

        return self._execute_ffmpeg(filter_graph, overlay_path, output_path)

    def _build_filter_complex(self, video_timeline, audio_timeline) -> str:
        # Extract current single-pass logic
        ...

class MultiPassRenderer(CompositionRenderer):
    """Legacy multi-pass renderer (fallback)."""
    # Extract current multi-pass logic
    ...

class CompositionRendererFactory:
    @staticmethod
    def create(config: EncodingConfig) -> CompositionRenderer:
        if config.single_pass:
            return SinglePassRenderer(config, OverlayGenerator(config))
        else:
            return MultiPassRenderer(config)
```

**Benefits:**
- ✅ Clear separation of rendering approaches
- ✅ Easy to add new renderers (e.g., hardware-accelerated)
- ✅ Testable filter graph generation
- ✅ Factory pattern simplifies selection

#### 6. Audio Processor (`audio_processor.py`)
**Purpose**: Audio cleanup and stitching

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class AudioCleanupConfig:
    highpass_hz: Optional[float] = 120.0
    lowpass_hz: Optional[float] = 7000.0
    denoise: bool = True
    denoise_nf: float = -25.0
    loudness_normalize: bool = True
    # ...

class AudioProcessor:
    """Handles audio extraction, cleanup, and stitching."""

    def __init__(self, config: AudioCleanupConfig):
        self.config = config

    def build_cleanup_filter(self) -> str:
        """Generate ffmpeg audio filter string."""
        # Extract current _build_audio_cleanup_filter logic
        ...

    def extract_segments(
        self,
        timeline: List[CompositionSegment],
        output_dir: str
    ) -> List[str]:
        """Extract audio segments to temp files."""
        ...

    def stitch_with_crossfade(
        self,
        segment_paths: List[str],
        output_path: str,
        crossfade_seconds: float = 0.06
    ) -> bool:
        """Concatenate segments with crossfades."""
        # Extract current crossfade logic
        ...
```

**Benefits:**
- ✅ Reusable audio processing
- ✅ Testable filter generation
- ✅ Clear interface for renderer

#### 7. Overlay Generator (`overlay_generator.py`)
**Purpose**: Subtitle and timestamp overlay generation

```python
from datetime import datetime
from typing import List, Optional

class OverlayGenerator:
    """Generates ASS/SRT subtitles for timestamp and review markers."""

    def __init__(self, config: OverlayConfig):
        self.config = config

    def generate_ass(
        self,
        timeline: List[CompositionSegment],
        event_start: datetime,
        review_segments: List[Tuple[float, float]],
        output_path: str
    ) -> str:
        """Generate ASS subtitle file with timestamps and markers."""
        # Extract current _generate_timestamp_ass logic
        ...
```

#### 8. Facade (MultiCameraComposer)
**Purpose**: Backward-compatible interface

```python
class MultiCameraComposer:
    """
    Composes multi-camera events (facade over modular components).

    Maintains 100% API compatibility with existing code.
    """

    def __init__(self, config: Dict[str, Any]):
        # Parse config into Pydantic models
        self.config = CompositionConfig.from_dict(config)

        # Initialize modules
        self.quality_analyzer = FFmpegAudioQualityAnalyzer(self.config.quality_weights)
        self.alignment_engine = AlignmentEngine(self.config.alignment)
        self.timeline_generator = self._create_timeline_generator()
        self.renderer = CompositionRendererFactory.create(self.config.encoding)
        self.audio_processor = AudioProcessor(self.config.audio_cleanup)
        self.overlay_generator = OverlayGenerator(self.config.overlay)

    def compose_multi_camera_event(
        self,
        video_clips: List[Dict[str, Any]],
        output_path: str,
        speech_segments: Optional[List[Dict[str, Any]]] = None,
        speech_timeline: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Create a composite video from multiple camera angles.

        API-compatible with existing implementation.
        """
        # Orchestrate modules
        clips = self._analyze_clips(video_clips)
        alignment_results = self.alignment_engine.align_clips(clips)
        self.alignment_engine.apply_offsets(clips, alignment_results)

        video_timeline, audio_timeline = self.timeline_generator.generate(
            clips, speech_segments
        )

        return self.renderer.render(video_timeline, audio_timeline, output_path)
```

---

## Migration Plan

### Phase 1: Extract Data Models (Week 1)
**Goal**: Type-safe configuration and data structures

**Tasks:**
1. Create `composition_config.py` with Pydantic models
2. Create `data_models.py` for CameraClip, CompositionSegment, etc.
3. Update `MultiCameraComposer.__init__` to use new config
4. Add tests for config validation
5. **Validation**: Run existing integration tests, verify no behavior change

**Risk**: Low - additive changes only

### Phase 2: Extract Quality Scoring (Week 1-2)
**Goal**: Isolated, testable quality analysis

**Tasks:**
1. Create `quality_scoring.py` module
2. Extract `_calculate_audio_quality` logic
3. Add result caching
4. Create unit tests with mock FFmpeg output
5. Update `MultiCameraComposer` to use new module
6. **Validation**: Compare quality scores before/after on test clips

**Risk**: Medium - changes scoring calculation path

### Phase 3: Extract Alignment Engine (Week 2)
**Goal**: Cacheable alignment with confidence scores

**Tasks:**
1. Create `alignment_engine.py` module
2. Wrap `av_alignment.py` functions
3. Add persistent caching (JSON/pickle)
4. Create unit tests with synthetic audio
5. Update `MultiCameraComposer` to use new engine
6. **Validation**: Compare alignment offsets before/after

**Risk**: Medium - changes alignment timing

### Phase 4: Extract Timeline Generator (Week 3)
**Goal**: Strategy pattern for timeline generation

**Tasks:**
1. Create `timeline_generator.py` with strategy base class
2. Implement strategies: `AudioQualityStrategy`, `SpeechPeopleStrategy`, etc.
3. Extract boundary creation logic
4. Create unit tests with mock clips
5. Update `MultiCameraComposer` to use new generator
6. **Validation**: Compare generated timelines before/after on test events

**Risk**: High - core algorithm changes

### Phase 5: Extract Rendering (Week 3-4)
**Goal**: Separate FFmpeg generation from orchestration

**Tasks:**
1. Create `composition_renderer.py` with base class
2. Implement `SinglePassRenderer` and `MultiPassRenderer`
3. Create `audio_processor.py` for cleanup/stitching
4. Create `overlay_generator.py` for subtitles
5. Create unit tests for filter graph generation
6. Update `MultiCameraComposer` to use new renderers
7. **Validation**: Compare output videos before/after (MD5 hash)

**Risk**: High - FFmpeg command generation changes

### Phase 6: Integration & Testing (Week 4)
**Goal**: Full integration with comprehensive tests

**Tasks:**
1. Create end-to-end integration tests
2. Performance benchmarking (before/after comparison)
3. Update documentation
4. Code review
5. **Validation**: Full regression test suite

**Risk**: Low - validation phase

### Phase 7: Deprecation & Cleanup (Week 5)
**Goal**: Remove legacy code

**Tasks:**
1. Mark old methods as deprecated
2. Remove dead code (legacy timeline methods)
3. Simplify facade
4. Final documentation pass

**Risk**: Low - cleanup only

---

## Testing Strategy

### Unit Tests (Per Module)
```python
# tests/unit/test_quality_scoring.py
def test_audio_quality_scoring():
    metrics = QualityMetrics(rms_db=-25, peak_db=-3, noise_floor_db=-45, clipping_count=0, duration=10.0)
    weights = AudioQualityWeights(rms=0.5, peak=0.3, noise=0.2, clip=0.0)

    scorer = FFmpegAudioQualityAnalyzer()
    score = scorer.score(metrics, weights)

    assert 0.0 <= score.overall <= 1.0
    assert score.rms_score > 0.5  # Good RMS level

# tests/unit/test_timeline_generator.py
def test_audio_quality_strategy():
    clips = [
        CameraClip("clip1.mp4", "cam1", 0.0, 10.0, audio_quality_score=0.8),
        CameraClip("clip2.mp4", "cam2", 0.0, 10.0, audio_quality_score=0.6),
    ]

    strategy = AudioQualityStrategy()
    selected = strategy.select_camera(0.0, 5.0, clips, TimelineContext())

    assert selected.camera == "cam1"  # Higher quality

# tests/unit/test_alignment_engine.py
def test_alignment_caching(tmp_path):
    engine = AlignmentEngine(AlignmentConfig(), cache_dir=str(tmp_path))
    clips = [...]  # Mock clips

    # First call computes
    results1 = engine.align_clips(clips)

    # Second call uses cache
    results2 = engine.align_clips(clips)

    assert results1 == results2
    assert (tmp_path / "alignment_cache.json").exists()
```

### Integration Tests
```python
# tests/integration/test_multi_camera_composition.py
def test_full_composition_pipeline(test_clips):
    """Verify full pipeline produces valid output."""
    composer = MultiCameraComposer(default_config)

    success = composer.compose_multi_camera_event(
        video_clips=test_clips,
        output_path="test_output.mp4"
    )

    assert success
    assert os.path.exists("test_output.mp4")

    # Verify output properties
    info = probe_media_info("test_output.mp4")
    assert info.duration > 0
    assert info.has_audio
    assert info.has_video

def test_timeline_comparison(test_clips):
    """Ensure refactored code produces same timeline as original."""
    old_composer = OriginalMultiCameraComposer(default_config)
    new_composer = MultiCameraComposer(default_config)

    old_timeline = old_composer._generate_aligned_timelines(test_clips)
    new_timeline = new_composer.timeline_generator.generate(test_clips)

    assert_timelines_equivalent(old_timeline, new_timeline)
```

### Regression Tests
```python
# tests/regression/test_output_consistency.py
def test_output_md5_consistency(test_clips, tmp_path):
    """Verify output video is byte-identical (or perceptually equivalent)."""
    composer = MultiCameraComposer(default_config)

    output1 = tmp_path / "output1.mp4"
    output2 = tmp_path / "output2.mp4"

    composer.compose_multi_camera_event(test_clips, str(output1))
    composer.compose_multi_camera_event(test_clips, str(output2))

    # Note: Exact MD5 match may not be possible due to timestamps
    # Use perceptual similarity instead
    assert videos_perceptually_similar(output1, output2, threshold=0.99)
```

### Performance Benchmarks
```python
# tests/benchmarks/test_performance.py
import pytest

@pytest.mark.benchmark
def test_timeline_generation_speed(benchmark, test_clips):
    """Ensure timeline generation is not slower than original."""
    composer = MultiCameraComposer(default_config)

    result = benchmark(
        composer.timeline_generator.generate,
        test_clips
    )

    # Should complete in < 1 second for 10 clips
    assert benchmark.stats['mean'] < 1.0

@pytest.mark.benchmark
def test_quality_analysis_caching(benchmark, test_clip):
    """Verify caching improves performance."""
    analyzer = FFmpegAudioQualityAnalyzer()

    # First call (no cache)
    metrics1 = analyzer.analyze(test_clip)

    # Second call (from cache)
    metrics2 = benchmark(analyzer.analyze, test_clip)

    assert metrics1 == metrics2
    # Cached call should be 10x faster
    assert benchmark.stats['mean'] < 0.1
```

---

## Success Criteria

### Functional Requirements
- ✅ **100% API Compatibility**: All existing calls to `compose_multi_camera_event` work unchanged
- ✅ **Identical Output**: Same input produces equivalent video output (perceptual similarity > 99%)
- ✅ **Feature Parity**: All strategies, configs, and edge cases supported

### Quality Requirements
- ✅ **Test Coverage**: >90% line coverage, >95% branch coverage for new modules
- ✅ **Performance**: No regression >5% on existing benchmarks
- ✅ **Memory**: No memory leaks, peak usage not increased

### Maintainability Requirements
- ✅ **Module Size**: No module >500 lines
- ✅ **Cyclomatic Complexity**: All functions <10 complexity score
- ✅ **Documentation**: All public APIs have docstrings with examples
- ✅ **Type Hints**: 100% type hint coverage

### Production Readiness
- ✅ **Logging**: Structured logging with context (clip paths, strategies, scores)
- ✅ **Metrics**: Expose composition metrics (timeline length, switch count, quality scores)
- ✅ **Error Handling**: Graceful degradation with informative errors
- ✅ **Observability**: Debug mode with detailed decision logs

---

## Risk Mitigation

### Risk: Timeline Generation Changes Break Output
**Mitigation:**
- Extensive regression tests comparing old vs new timelines
- Feature flag to toggle between old/new implementation
- Phased rollout with A/B testing

### Risk: Performance Regression
**Mitigation:**
- Benchmark suite run on every commit
- Profile before/after with real-world data
- Caching for expensive operations (quality analysis, alignment)

### Risk: FFmpeg Command Changes Cause Encoding Errors
**Mitigation:**
- Fallback to multi-pass renderer on single-pass failure
- Comprehensive error handling with retries
- Test suite with diverse video formats/codecs

### Risk: Breaking Changes for High-Value Customer
**Mitigation:**
- 100% API compatibility maintained via facade
- Private beta testing with customer
- Rollback plan with old code preserved

---

## Future Enhancements (Post-Refactor)

### 1. Machine Learning Integration
- **ML-Based Quality Scoring**: Replace FFmpeg astats with ML model (speech clarity, background noise)
- **Smart Camera Selection**: Train model on manual edits to learn user preferences
- **Anomaly Detection**: Automatically flag segments with quality issues

### 2. Advanced Timeline Optimization
- **Dynamic Programming**: Globally optimal camera selection
- **Lookahead**: Consider next N segments when choosing camera
- **Post-Processing**: Smooth timeline with boundary optimization

### 3. Real-Time Composition
- **Streaming Support**: Compose live streams instead of recorded clips
- **Incremental Updates**: Update composition as new clips arrive

### 4. User Interface
- **Timeline Visualizer**: Interactive web UI to view and edit timelines
- **Manual Override**: Allow users to pin cameras for specific segments
- **Quality Dashboard**: Real-time metrics during composition

### 5. Performance Optimizations
- **Parallel Processing**: Batch people detection, parallel audio analysis
- **GPU Acceleration**: Hardware-accelerated people detection
- **Distributed Rendering**: Split FFmpeg work across multiple machines

---

## Appendix: Code Metrics

### Current State (multi_camera_composer.py)
```
Lines of Code: 1772
Functions: 32
Classes: 3 (CameraClip, CompositionSegment, MultiCameraComposer)
Cyclomatic Complexity: 8.2 average, 24 max (_generate_aligned_timelines)
Dependencies: 12 imports
Test Coverage: ~45% (integration tests only)
```

### Target State (Refactored)
```
Modules: 8
Lines per Module: 100-400
Functions per Module: 5-15
Classes per Module: 2-5
Cyclomatic Complexity: <6 average, <10 max
Test Coverage: >90%
```

### LOC Breakdown (Estimated)
```
composition_config.py:        150 lines (Pydantic models)
quality_scoring.py:           250 lines (analysis + scoring)
alignment_engine.py:          200 lines (wrapper + caching)
timeline_generator.py:        350 lines (strategies + generator)
composition_renderer.py:      400 lines (single/multi-pass renderers)
audio_processor.py:           200 lines (cleanup + stitching)
overlay_generator.py:         180 lines (ASS generation)
multi_camera_composer.py:     250 lines (facade + orchestration)
-----------------------------------------------------
Total:                       1980 lines (+200 for structure/tests)
```

---

## Conclusion

The proposed refactoring transforms a 1772-line monolith into **8 modular, testable, maintainable components** while maintaining **100% backward compatibility**. This architecture:

1. **Enables Testing**: Each module can be unit tested without FFmpeg/video files
2. **Improves Maintainability**: Clear separation of concerns, <500 lines per module
3. **Facilitates Extension**: Strategy pattern for timeline generation, swappable renderers
4. **Preserves Functionality**: Facade pattern ensures existing code works unchanged
5. **Increases Observability**: Structured logging and metrics at each layer

The migration plan is incremental (5 weeks), low-risk (each phase validated independently), and delivers value progressively (config validation → quality caching → testable timeline generation → clean rendering).

**Recommendation**: Proceed with Phase 1 (data models) immediately for the high-value customer release. Phases 2-5 can follow in subsequent sprints without blocking the current release.
