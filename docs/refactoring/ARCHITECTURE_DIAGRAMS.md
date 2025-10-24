# Architecture Diagrams

## Current Architecture (Monolithic)

```
┌────────────────────────────────────────────────────────────────────────┐
│                     MultiCameraComposer (1772 lines)                   │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Configuration Parsing (200 lines)                                │ │
│  │ - 50+ parameters from nested dicts                               │ │
│  │ - No validation                                                   │ │
│  │ - Complex conditional logic based on strategy                    │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                  │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Analysis Phase (400 lines)                                       │ │
│  │                                                                  │ │
│  │  ┌────────────────────┐  ┌────────────────────┐                │ │
│  │  │ Audio Quality      │  │ People Detection   │                │ │
│  │  │ (150 lines)        │  │ (100 lines)        │                │ │
│  │  │ - FFmpeg astats    │  │ - Lazy HF model    │                │ │
│  │  │ - Regex parsing    │  │ - Dict cache       │                │ │
│  │  │ - No caching       │  │ - Serial detection │                │ │
│  │  └────────────────────┘  └────────────────────┘                │ │
│  │                                                                  │ │
│  │  ┌────────────────────────────────────────────┐                │ │
│  │  │ Audio Alignment (150 lines)                │                │ │
│  │  │ - Two different methods (confusing)        │                │ │
│  │  │ - Mixed with extraction logic              │                │ │
│  │  │ - Instance variable storage                │                │ │
│  │  └────────────────────────────────────────────┘                │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                  │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Timeline Generation (450 lines)                                  │ │
│  │                                                                  │ │
│  │  ┌─────────────────────────────────────────────────────────┐   │ │
│  │  │ _generate_aligned_timelines() (250 lines)               │   │ │
│  │  │ - Boundary creation                                     │   │ │
│  │  │ - Strategy selection (4 strategies, 1 giant if-else)    │   │ │
│  │  │ - Speech detection                                      │   │ │
│  │  │ - People detection (inline)                             │   │ │
│  │  │ - Review marking                                        │   │ │
│  │  │ - Segment coalescing                                    │   │ │
│  │  │ ALL IN ONE FUNCTION ❌                                  │   │ │
│  │  └─────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  │  ┌────────────────────┐  ┌────────────────────┐                │ │
│  │  │ Legacy Timeline    │  │ Speech Segment     │                │ │
│  │  │ Methods (200 lines)│  │ Loading (120 lines)│                │ │
│  │  │ - Partially unused │  │ - Complex mapping  │                │ │
│  │  └────────────────────┘  └────────────────────┘                │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                  │                                     │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ FFmpeg Generation (600 lines)                                    │ │
│  │                                                                  │ │
│  │  ┌─────────────────────────────────────────────────────────┐   │ │
│  │  │ Single-Pass Renderer (300 lines)                        │   │ │
│  │  │ - Complex filter_complex building                       │   │ │
│  │  │ - Video trimming, concat, overlay                       │   │ │
│  │  │ - Audio crossfade chain                                 │   │ │
│  │  └─────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  │  ┌─────────────────────────────────────────────────────────┐   │ │
│  │  │ Multi-Pass Renderer (250 lines)                         │   │ │
│  │  │ - Extract → overlay → stitch → combine                  │   │ │
│  │  │ - Legacy fallback                                       │   │ │
│  │  └─────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  │  ┌────────────────────┐  ┌────────────────────┐                │ │
│  │  │ Audio Cleanup      │  │ Overlay Generation │                │ │
│  │  │ (50 lines)         │  │ (150 lines)        │                │ │
│  │  └────────────────────┘  └────────────────────┘                │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Utilities & Fallbacks (72 lines)                                │ │
│  │ - Simple copy, sequential merge                                 │ │
│  │ - Frame extraction, dimension probing                           │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘

PROBLEMS:
❌ Hard to test (need video files, FFmpeg, ML models)
❌ Hard to understand (1772 lines, complexity 24)
❌ Hard to extend (adding strategy = modifying core loop)
❌ No type safety (dict-based config)
❌ No caching (re-analyze every time)
❌ Tight coupling (can't swap implementations)
```

---

## Proposed Architecture (Modular)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                MultiCameraComposer (Facade - 250 lines)                 │
│                         ┌───────────────────┐                           │
│                         │  Feature Flags    │                           │
│                         │  (Rollback Ready) │                           │
│                         └───────────────────┘                           │
│                                   │                                     │
│                         ┌───────────────────┐                           │
│                         │ CompositionConfig │                           │
│                         │ (Pydantic Model)  │                           │
│                         │ ✅ Type-safe      │                           │
│                         │ ✅ Validated      │                           │
│                         │ ✅ IDE support    │                           │
│                         └───────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       │                            │                            │
       ▼                            ▼                            ▼
┌──────────────┐            ┌──────────────┐            ┌──────────────┐
│   Quality    │            │  Alignment   │            │   Timeline   │
│   Scoring    │            │   Engine     │            │  Generator   │
│ (250 lines)  │            │ (200 lines)  │            │ (350 lines)  │
│              │            │              │            │              │
│ ┌──────────┐ │            │ ┌──────────┐ │            │ ┌──────────┐ │
│ │ Analyzer │ │            │ │  Cache   │ │            │ │ Strategy │ │
│ │ (FFmpeg) │ │            │ │(Disk IO) │ │            │ │ Pattern  │ │
│ └──────────┘ │            │ └──────────┘ │            │ └──────────┘ │
│      │       │            │      │       │            │      │       │
│ ┌────▼────┐  │            │ ┌────▼────┐  │            │ ┌────▼────┐  │
│ │  Cache  │  │            │ │ GCC-PHAT│  │            │ │AudioQual│  │
│ │(Disk IO)│  │            │ │ Wrapper │  │            │ │ Strategy│  │
│ └─────────┘  │            │ └─────────┘  │            │ └─────────┘  │
│      │       │            │      │       │            │      │       │
│ ┌────▼────┐  │            │ ┌────▼────┐  │            │ ┌────▼────┐  │
│ │ Scorer  │  │            │ │Confidence│ │            │ │TimeBased│  │
│ │(Weights)│  │            │ │ Scores  │  │            │ │ Strategy│  │
│ └─────────┘  │            │ └─────────┘  │            │ └─────────┘  │
│              │            │              │            │      │       │
│ ✅ Testable  │            │ ✅ Testable  │            │ ┌────▼────┐  │
│ ✅ Cacheable │            │ ✅ Cacheable │            │ │SpeechPpl│  │
│ ✅ Swappable │            │ ✅ Robust    │            │ │ Strategy│  │
└──────────────┘            └──────────────┘            │ └─────────┘  │
                                                        │              │
                                                        │ ✅ Testable  │
                                                        │ ✅ Pluggable │
                                                        │ ✅ Extensible│
                                                        └──────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       │                            │                            │
       ▼                            ▼                            ▼
┌──────────────┐            ┌──────────────┐            ┌──────────────┐
│ Composition  │            │    Audio     │            │   Overlay    │
│  Renderer    │            │  Processor   │            │  Generator   │
│ (400 lines)  │            │ (200 lines)  │            │ (180 lines)  │
│              │            │              │            │              │
│ ┌──────────┐ │            │ ┌──────────┐ │            │ ┌──────────┐ │
│ │SinglePass│ │            │ │ Extract  │ │            │ │   ASS    │ │
│ │ Renderer │ │            │ │ Segments │ │            │ │Generator │ │
│ └──────────┘ │            │ └──────────┘ │            │ └──────────┘ │
│      │       │            │      │       │            │      │       │
│ ┌────▼────┐  │            │ ┌────▼────┐  │            │ ┌────▼────┐  │
│ │MultiPass│  │            │ │ Cleanup │  │            │ │Timestamp│  │
│ │ Renderer│  │            │ │ Filters │  │            │ │ Format  │  │
│ └─────────┘  │            │ └─────────┘  │            │ └─────────┘  │
│      │       │            │      │       │            │      │       │
│ ┌────▼────┐  │            │ ┌────▼────┐  │            │ ┌────▼────┐  │
│ │ Factory │  │            │ │Crossfade│  │            │ │ Review  │  │
│ │ Pattern │  │            │ │ Chain   │  │            │ │ Markers │  │
│ └─────────┘  │            │ └─────────┘  │            │ └─────────┘  │
│              │            │              │            │              │
│ ✅ Testable  │            │ ✅ Testable  │            │ ✅ Testable  │
│ ✅ Swappable │            │ ✅ Reusable  │            │ ✅ Flexible  │
└──────────────┘            └──────────────┘            └──────────────┘

                           ┌──────────────┐
                           │ Data Models  │
                           │ (200 lines)  │
                           │              │
                           │ CameraClip   │
                           │ Composition  │
                           │ Segment      │
                           │ Quality      │
                           │ Metrics      │
                           │ Alignment    │
                           │ Result       │
                           │              │
                           │ ✅ Type-safe │
                           │ ✅ Validated │
                           └──────────────┘

BENEFITS:
✅ Unit testable (mock interfaces)
✅ Small modules (<500 lines)
✅ Clear responsibilities
✅ Type-safe (Pydantic + mypy)
✅ Cacheable (performance)
✅ Extensible (strategy pattern)
```

---

## Data Flow: Current vs. Proposed

### Current Flow (Monolithic)

```
┌──────────────┐
│ Video Clips  │
│   (Input)    │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│   MultiCameraComposer.__init__()                 │
│   Parse 50+ params from nested dicts             │
│   No validation ❌                                │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│   compose_multi_camera_event()                   │
│   Main orchestration method                      │
└──────────────────┬───────────────────────────────┘
                   │
                   ├─────► _analyze_clips()
                   │       ├─► _calculate_audio_quality()
                   │       │   └─► FFmpeg subprocess (NO CACHE ❌)
                   │       └─► probe_media_info()
                   │
                   ├─────► estimate_per_clip_offsets()
                   │       └─► GCC-PHAT cross-correlation
                   │
                   ├─────► _generate_aligned_timelines()
                   │       │   250 lines, complexity 20+ ❌
                   │       ├─► Boundary creation
                   │       ├─► Strategy selection (giant if-else)
                   │       ├─► Speech detection (inline)
                   │       ├─► People detection (serial)
                   │       └─► Segment coalescing
                   │
                   └─────► _create_composite_video()
                           ├─► _create_composite_video_single_pass()
                           │   └─► _build_filter_graph()
                           │       └─► Complex filter_complex string
                           │
                           └─► Execute FFmpeg
                               └─► Output video
```

### Proposed Flow (Modular)

```
┌──────────────┐
│ Video Clips  │
│   (Input)    │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│   MultiCameraComposer.__init__()                 │
│   ┌──────────────────────────────────┐           │
│   │ CompositionConfig.from_dict()    │           │
│   │ ✅ Pydantic validation           │           │
│   │ ✅ Type safety                   │           │
│   └──────────────────────────────────┘           │
│                                                   │
│   ┌──────────────────────────────────┐           │
│   │ Initialize Modules:              │           │
│   │ - QualityAnalyzer                │           │
│   │ - AlignmentEngine                │           │
│   │ - TimelineGenerator              │           │
│   │ - CompositionRenderer            │           │
│   └──────────────────────────────────┘           │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│   compose_multi_camera_event()                   │
│   Orchestrate modules (thin facade)              │
└──────────────────┬───────────────────────────────┘
                   │
                   ├─────► QualityAnalyzer.analyze()
                   │       ├─► FFmpeg subprocess
                   │       └─► ✅ CACHED to disk
                   │
                   ├─────► QualityAnalyzer.score()
                   │       └─► Weighted combination
                   │
                   ├─────► AlignmentEngine.align_clips()
                   │       ├─► GCC-PHAT wrapper
                   │       └─► ✅ CACHED to disk
                   │
                   ├─────► AlignmentEngine.apply_offsets()
                   │       └─► Adjust clip start_time
                   │
                   ├─────► TimelineGenerator.generate()
                   │       │   ✅ Strategy pattern
                   │       ├─► _create_boundaries()
                   │       ├─► VideoStrategy.select_camera()
                   │       │   └─► AudioQualityStrategy
                   │       │   └─► TimeBasedStrategy
                   │       │   └─► SpeechPeopleStrategy
                   │       ├─► AudioStrategy.select_camera()
                   │       └─► _coalesce_segments()
                   │
                   └─────► CompositionRenderer.render()
                           │   ✅ Factory pattern
                           ├─► AudioProcessor.extract_segments()
                           ├─► AudioProcessor.stitch_with_crossfade()
                           ├─► OverlayGenerator.generate_ass()
                           └─► _execute_ffmpeg()
                               └─► Output video
```

**Key Improvements**:
1. ✅ **Type Safety**: Pydantic validation at entry
2. ✅ **Caching**: Quality and alignment cached
3. ✅ **Modularity**: Each module testable independently
4. ✅ **Extensibility**: Strategy pattern for algorithms
5. ✅ **Clarity**: Clear data flow, single responsibility

---

## Strategy Pattern: Timeline Generation

### Current (Monolithic If-Else)

```python
def _generate_aligned_timelines(self, camera_clips):
    # ... 250 lines of complexity

    for i in range(len(boundaries) - 1):
        seg_start = boundaries[i]
        seg_end = boundaries[i + 1]
        available_clips = [...]

        # Giant strategy selection if-else ❌
        if self.switching_strategy == 'speech_people':
            speech_active = self._segment_has_speech(seg_start, seg_end)
            if not speech_active:
                # Inline people detection
                sample_t = seg_start + 0.5 * seg_dur
                counts = {}
                for c in available_clips:
                    counts[c.path] = self._get_people_count_for_clip_at(c, sample_t)
                available_people = [c for c in avail if counts.get(c.path, 0) >= self._people_min_count]
                selected = max(available_people, key=lambda x: counts[x.path])
            else:
                selected = max(available_clips, key=lambda x: x.audio_quality_score)
        elif self.switching_strategy == 'audio_quality':
            selected = max(available_clips, key=lambda x: x.audio_quality_score)
        elif self.switching_strategy == 'round_robin':
            # ... round robin logic
        else:  # 'time_based'
            # ... time-based logic

        # ... 100 more lines
```

**Problems**:
- ❌ Adding strategy = modifying core loop
- ❌ All strategies mixed together (hard to test)
- ❌ People detection inlined (can't test independently)
- ❌ Complexity: 20+

### Proposed (Strategy Pattern)

```python
# Strategy interface
class TimelineStrategy(ABC):
    @abstractmethod
    def select_camera(
        self,
        seg_start: float,
        seg_end: float,
        available_clips: List[CameraClip],
        context: TimelineContext
    ) -> CameraClip:
        pass

# Implementations
class AudioQualityStrategy(TimelineStrategy):
    def select_camera(self, seg_start, seg_end, available_clips, context):
        return max(available_clips, key=lambda c: c.audio_quality_score)

class SpeechPeopleStrategy(TimelineStrategy):
    def __init__(self, min_people: int):
        self.min_people = min_people

    def select_camera(self, seg_start, seg_end, available_clips, context):
        if context.has_speech(seg_start, seg_end):
            return max(available_clips, key=lambda c: c.audio_quality_score)
        else:
            # Use people detection
            sample_t = seg_start + (seg_end - seg_start) / 2
            people_counts = {
                c: context.get_people_count(c, sample_t)
                for c in available_clips
            }
            clips_with_people = [
                c for c in available_clips
                if people_counts[c] >= self.min_people
            ]
            return max(clips_with_people, key=lambda c: people_counts[c])

# Generator (clean, simple)
class TimelineGenerator:
    def __init__(self, video_strategy, audio_strategy):
        self.video_strategy = video_strategy
        self.audio_strategy = audio_strategy

    def generate(self, clips, speech_segments):
        boundaries = self._create_boundaries(clips)
        context = TimelineContext(speech_segments)

        timeline = []
        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            available = [c for c in clips if c.overlaps(seg_start, seg_end)]

            # ✅ Delegate to strategy
            selected = self.video_strategy.select_camera(
                seg_start, seg_end, available, context
            )
            timeline.append(self._make_segment(selected, seg_start, seg_end))

        return timeline
```

**Benefits**:
- ✅ Adding strategy = new class (no core changes)
- ✅ Each strategy testable independently
- ✅ People detection abstracted (mockable)
- ✅ Complexity: <6 per function

---

## Testing Strategy: Current vs. Proposed

### Current (Integration Tests Only)

```python
# tests/integration/test_composition.py
def test_multi_camera_composition():
    """
    ❌ Requires:
    - Real video files (GB of data)
    - FFmpeg installed
    - Hugging Face model downloaded
    - 30+ seconds to run
    """
    composer = MultiCameraComposer(config)
    success = composer.compose_multi_camera_event(
        video_clips=real_video_files,
        output_path="output.mp4"
    )
    assert success
    assert os.path.exists("output.mp4")
    # Hard to debug if fails ❌
```

**Coverage**: ~45% (integration tests only)

### Proposed (Pyramid of Tests)

```python
# Unit Tests (Fast, No Dependencies)
# tests/unit/test_quality_scoring.py
def test_quality_scorer_with_mock_ffmpeg(mocker):
    """
    ✅ Mocked FFmpeg output
    ✅ Runs in <1ms
    ✅ Easy to debug
    """
    mock_ffmpeg_output = "RMS level dB: -25.3\nPeak level dB: -3.1"
    mocker.patch('subprocess.run', return_value=Mock(stderr=mock_ffmpeg_output))

    analyzer = FFmpegAudioQualityAnalyzer()
    metrics = analyzer.analyze("fake.mp4")

    assert metrics.rms_db == -25.3
    assert metrics.peak_db == -3.1

# tests/unit/test_timeline_strategies.py
def test_audio_quality_strategy():
    """
    ✅ Mock clips (no files)
    ✅ Runs in <1ms
    """
    clips = [
        CameraClip("c1.mp4", "cam1", 0.0, 10.0, audio_quality_score=0.8),
        CameraClip("c2.mp4", "cam2", 0.0, 10.0, audio_quality_score=0.6)
    ]
    strategy = AudioQualityStrategy()
    selected = strategy.select_camera(0.0, 5.0, clips, TimelineContext())
    assert selected.camera == "cam1"

# Integration Tests (Medium, Some Dependencies)
# tests/integration/test_quality_integration.py
def test_quality_scorer_with_test_video():
    """
    ✅ Small test video (1MB)
    ✅ Runs in <1s
    """
    analyzer = FFmpegAudioQualityAnalyzer()
    metrics = analyzer.analyze("tests/fixtures/test_clip.mp4")
    assert 0 <= metrics.rms_db <= 0
    assert metrics.duration > 0

# End-to-End Tests (Slow, Full Stack)
# tests/integration/test_full_composition.py
def test_full_composition_pipeline():
    """
    ✅ Real videos (but small)
    ✅ Runs in 10-30s
    """
    composer = MultiCameraComposer(config)
    success = composer.compose_multi_camera_event(...)
    assert success
```

**Coverage Target**: >90%

---

## Performance: Caching Impact

### Current (No Caching)

```
Run 1: Analyze 5 clips
├─ Clip 1: FFmpeg subprocess (5s)
├─ Clip 2: FFmpeg subprocess (5s)
├─ Clip 3: FFmpeg subprocess (5s)
├─ Clip 4: FFmpeg subprocess (5s)
└─ Clip 5: FFmpeg subprocess (5s)
Total: 25 seconds ❌

Run 2: Analyze same 5 clips (retry after error)
├─ Clip 1: FFmpeg subprocess (5s) ← WASTED
├─ Clip 2: FFmpeg subprocess (5s) ← WASTED
├─ Clip 3: FFmpeg subprocess (5s) ← WASTED
├─ Clip 4: FFmpeg subprocess (5s) ← WASTED
└─ Clip 5: FFmpeg subprocess (5s) ← WASTED
Total: 25 seconds ❌
```

**Total Time**: 50 seconds (25 + 25)

### Proposed (With Caching)

```
Run 1: Analyze 5 clips
├─ Clip 1: FFmpeg subprocess (5s) → Cache write
├─ Clip 2: FFmpeg subprocess (5s) → Cache write
├─ Clip 3: FFmpeg subprocess (5s) → Cache write
├─ Clip 4: FFmpeg subprocess (5s) → Cache write
└─ Clip 5: FFmpeg subprocess (5s) → Cache write
Total: 25 seconds

Run 2: Analyze same 5 clips (retry after error)
├─ Clip 1: Cache hit (<1ms) ✅
├─ Clip 2: Cache hit (<1ms) ✅
├─ Clip 3: Cache hit (<1ms) ✅
├─ Clip 4: Cache hit (<1ms) ✅
└─ Clip 5: Cache hit (<1ms) ✅
Total: <0.1 seconds ✅
```

**Total Time**: ~25 seconds (25 + 0.1)
**Speedup**: 2x on retry, 100x+ on cache hits

**Cache Hit Rate** (expected): >80% in production

---

## Risk Mitigation: Feature Flags

```python
# Default: All flags OFF (legacy behavior)
config = {
    'multi_camera_composition': { ... }
}
composer = MultiCameraComposer(config)
# ✅ Uses legacy code (100% safe)

# Phase 1: Enable config + quality
config['feature_flags'] = {
    'use_pydantic_config': True,
    'use_new_quality_scorer': True
}
composer = MultiCameraComposer(config)
# ✅ New config + quality, rest legacy

# Phase 3: Enable timeline (risky)
config['feature_flags']['use_new_timeline_generator'] = True
composer = MultiCameraComposer(config)
# ⚠️ New timeline generation

# Problem detected? Rollback instantly:
config['feature_flags']['use_new_timeline_generator'] = False
# ✅ Back to legacy timeline (< 1 minute)

# Or via environment:
export BLINK_COMPOSITION_NEW_TIMELINE=false
# ✅ Instant rollback without code change
```

**Rollback Time**: <5 minutes (disable flag + restart)

---

## Metrics & Observability

### Current (Limited Logging)

```python
logging.info("Composing multi-camera event from %d clips", len(clips))
# ... [150 lines of code] ...
logging.info("Successfully composed multi-camera event")
```

**Problems**:
- ❌ Hard to debug (what happened in between?)
- ❌ No metrics (how long did each step take?)
- ❌ No quality scores logged
- ❌ Can't answer "why did it choose this camera?"

### Proposed (Rich Logging + Metrics)

```python
# Configuration
logger.info("Initialized composer", extra={
    'strategy': config.switching_strategy.value,
    'quality_weights': config.quality_weights.dict(),
    'flags': feature_flags.to_dict()
})

# Quality Analysis
for clip in clips:
    metrics = quality_analyzer.analyze(clip.path)
    score = quality_analyzer.score(metrics, weights)
    logger.info("Quality analysis", extra={
        'clip': clip.path,
        'rms_db': metrics.rms_db,
        'peak_db': metrics.peak_db,
        'score': score.overall,
        'cached': was_cached,
        'duration_ms': analysis_time_ms
    })

# Alignment
logger.info("Alignment results", extra={
    'reference': ref_clip.path,
    'results': {
        clip.path: {
            'offset_seconds': result.offset_seconds,
            'confidence': result.confidence
        }
        for clip, result in alignment_results.items()
    }
})

# Timeline
for seg in timeline:
    logger.debug("Timeline segment", extra={
        'start': seg.start_time,
        'duration': seg.duration,
        'camera': seg.camera,
        'strategy_reason': seg.selection_reason,  # New field
        'needs_review': seg.needs_review
    })

# Metrics (Prometheus-style)
metrics.histogram('composition.timeline_generation_seconds', timeline_gen_time)
metrics.counter('composition.total_segments', len(timeline))
metrics.gauge('composition.average_segment_duration', avg_seg_duration)
metrics.counter('composition.cache_hits', cache_hits)
metrics.counter('composition.cache_misses', cache_misses)
```

**Benefits**:
- ✅ Detailed debug logs
- ✅ Performance metrics per phase
- ✅ Decision rationale logged
- ✅ Can answer "why camera X at time Y?"

---

## Summary: Why Refactor?

| Aspect | Current | Proposed | Benefit |
|--------|---------|----------|---------|
| **Lines of Code** | 1772 monolith | 8 modules, <500 each | ✅ Maintainability |
| **Test Coverage** | ~45% (integration) | >90% (unit + integration) | ✅ Reliability |
| **Testability** | Requires video files | Mock interfaces | ✅ Fast feedback |
| **Complexity** | 24 (max function) | <10 (all functions) | ✅ Understandability |
| **Type Safety** | Dict-based config | Pydantic + mypy | ✅ Fewer bugs |
| **Extensibility** | Modify core loop | Add new class | ✅ Innovation |
| **Performance** | No caching | Disk cache | ✅ 2x+ speedup |
| **Observability** | Limited logging | Rich metrics | ✅ Debuggability |
| **Risk** | N/A | Feature flags | ✅ Rollback ready |

**Timeline**: 5 weeks
**Risk**: Medium (mitigated by incremental approach + feature flags)
**ROI**: Positive after ~3 months

**Recommendation**: Start with Phase 1 (Week 1) for immediate value with minimal risk.
