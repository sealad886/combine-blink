# Implementation & Migration Plan

## Overview

This document provides a **detailed, actionable plan** for refactoring the multi-camera composition system from a 1772-line monolith to a modular architecture. The migration is designed to be:

- **Incremental**: Each phase is independently testable and deployable
- **Low-Risk**: Backward compatibility maintained throughout
- **Measurable**: Clear success criteria for each phase
- **Reversible**: Feature flags enable quick rollback if issues arise

**Total Timeline**: 5 weeks (1 developer full-time)
**Risk Level**: Medium (architectural changes, but incremental approach mitigates)

---

## Pre-Migration Checklist

### ☐ 1. Establish Baseline

```bash
# Run full test suite and capture results
pytest tests/ --cov=blink_pipeline --cov-report=html -v > baseline_tests.log

# Benchmark current performance
python tests/benchmarks/benchmark_composition.py > baseline_perf.json

# Document current behavior
python tests/regression/capture_reference_outputs.py

# Generate current metrics
radon cc blink_pipeline/multi_camera_composer.py -a -s
radon mi blink_pipeline/multi_camera_composer.py -s
```

**Success Criteria:**
- ✅ All existing tests passing
- ✅ Performance baseline captured (timeline generation time, render time)
- ✅ Reference outputs saved for regression testing
- ✅ Complexity metrics documented

### ☐ 2. Set Up Refactoring Infrastructure

```bash
# Create refactoring branch
git checkout -b refactor/modular-composition

# Create new module directories
mkdir -p blink_pipeline/composition/{config,quality,alignment,timeline,rendering}
touch blink_pipeline/composition/__init__.py

# Set up type checking
pip install mypy
echo "[mypy]
python_version = 3.9
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True" > mypy.ini

# Set up coverage tracking
echo "[coverage:run]
source = blink_pipeline
omit = tests/*

[coverage:report]
precision = 2
show_missing = True
skip_covered = False

[coverage:html]
directory = htmlcov" > .coveragerc
```

### ☐ 3. Create Feature Flag System

```python
# blink_pipeline/composition/feature_flags.py
import os
from typing import Dict, Any

class CompositionFeatureFlags:
    """Feature flags for progressive rollout of refactored modules."""

    def __init__(self, config: Dict[str, Any]):
        env_prefix = "BLINK_COMPOSITION_"

        # Phase 1: Use new config models
        self.use_pydantic_config = self._get_flag(
            config, 'use_pydantic_config',
            env_var=f"{env_prefix}PYDANTIC_CONFIG",
            default=False
        )

        # Phase 2: Use new quality scorer
        self.use_new_quality_scorer = self._get_flag(
            config, 'use_new_quality_scorer',
            env_var=f"{env_prefix}NEW_QUALITY",
            default=False
        )

        # Phase 3: Use new alignment engine
        self.use_new_alignment = self._get_flag(
            config, 'use_new_alignment',
            env_var=f"{env_prefix}NEW_ALIGNMENT",
            default=False
        )

        # Phase 4: Use new timeline generator
        self.use_new_timeline_generator = self._get_flag(
            config, 'use_new_timeline_generator',
            env_var=f"{env_prefix}NEW_TIMELINE",
            default=False
        )

        # Phase 5: Use new renderer
        self.use_new_renderer = self._get_flag(
            config, 'use_new_renderer',
            env_var=f"{env_prefix}NEW_RENDERER",
            default=False
        )

    @staticmethod
    def _get_flag(
        config: Dict[str, Any],
        key: str,
        env_var: str,
        default: bool
    ) -> bool:
        """Get flag value from config or environment."""
        # Environment takes precedence
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value.lower() in ('true', '1', 'yes')

        # Then config
        return config.get('feature_flags', {}).get(key, default)
```

---

## Phase 1: Configuration Models (Week 1)

**Goal**: Replace dict-based configuration with type-safe Pydantic models

**Rationale**: Type safety catches configuration errors early and enables better IDE support

### Tasks

#### 1.1 Implement Configuration Models
**File**: `blink_pipeline/composition/config.py`

```python
# Implement all models from INTERFACE_SPECIFICATIONS.md
# - AudioQualityWeights
# - AlignmentConfig
# - PeopleDetectionConfig
# - CompositionConfig

# Add backward-compatible from_dict() and to_dict() methods
```

**Test**:
```python
# tests/unit/test_composition_config.py
def test_config_validation():
    """Test Pydantic validation catches invalid configs."""
    with pytest.raises(ValidationError):
        AudioQualityWeights(rms=1.5)  # > 1.0

def test_config_from_dict_legacy():
    """Test conversion from legacy dict format."""
    legacy = {
        'multi_camera_composition': {
            'switching_strategy': 'audio_quality',
            'audio_quality_weights': {'rms': 0.5, 'peak': 0.5}
        }
    }
    config = CompositionConfig.from_dict(legacy)
    assert config.switching_strategy == SwitchingStrategy.AUDIO_QUALITY
    assert config.quality_weights.rms == 0.5
```

**Estimated Time**: 2 days

#### 1.2 Create Data Models
**File**: `blink_pipeline/composition/data_models.py`

```python
# Implement dataclasses from INTERFACE_SPECIFICATIONS.md
# - CameraClip (with overlaps(), overlap_duration())
# - CompositionSegment (with can_coalesce_with())
# - QualityMetrics
# - QualityScore
# - AlignmentResult
# - SpeechSegment
```

**Test**:
```python
# tests/unit/test_data_models.py
def test_camera_clip_overlap():
    """Test overlap detection."""
    clip = CameraClip("clip.mp4", "cam1", 5.0, 10.0)
    assert clip.overlaps(0.0, 6.0)  # Overlaps start
    assert clip.overlaps(14.0, 20.0)  # Overlaps end
    assert not clip.overlaps(0.0, 4.0)  # Before clip

def test_composition_segment_coalesce():
    """Test segment merging logic."""
    seg1 = CompositionSegment("cam1", "clip.mp4", 0.0, 5.0, 0.0)
    seg2 = CompositionSegment("cam1", "clip.mp4", 5.0, 5.0, 5.0)
    assert seg1.can_coalesce_with(seg2)

    seg3 = CompositionSegment("cam2", "other.mp4", 5.0, 5.0, 0.0)
    assert not seg1.can_coalesce_with(seg3)  # Different clip
```

**Estimated Time**: 1 day

#### 1.3 Update MultiCameraComposer to Use New Models
**File**: `blink_pipeline/multi_camera_composer.py`

```python
class MultiCameraComposer:
    def __init__(self, config: Dict[str, Any]):
        self.feature_flags = CompositionFeatureFlags(config)

        if self.feature_flags.use_pydantic_config:
            # New path: use Pydantic config
            self.config = CompositionConfig.from_dict(config)
        else:
            # Legacy path: keep existing dict-based config
            self.config = config
            self.composition_config = config.get('multi_camera_composition', {})
            # ... existing init code
```

**Test**:
```python
# tests/integration/test_config_migration.py
def test_pydantic_config_produces_same_behavior():
    """Verify new config produces identical results."""
    legacy_composer = MultiCameraComposer(legacy_config)

    pydantic_config = legacy_config.copy()
    pydantic_config['feature_flags'] = {'use_pydantic_config': True}
    pydantic_composer = MultiCameraComposer(pydantic_config)

    # Both should produce same timeline
    legacy_clips = legacy_composer._analyze_clips(test_clips)
    pydantic_clips = pydantic_composer._analyze_clips(test_clips)

    assert_clips_equivalent(legacy_clips, pydantic_clips)
```

**Estimated Time**: 2 days

### Phase 1 Success Criteria

- ✅ All configuration models implemented with validation
- ✅ 100% test coverage for config and data models
- ✅ Feature flag allows toggling between old/new config
- ✅ All existing integration tests pass with both paths
- ✅ Type checking passes with mypy
- ✅ Documentation updated

**Deliverables**:
- `blink_pipeline/composition/config.py` (150 lines)
- `blink_pipeline/composition/data_models.py` (200 lines)
- `tests/unit/test_composition_config.py` (150 lines)
- `tests/unit/test_data_models.py` (200 lines)
- `tests/integration/test_config_migration.py` (100 lines)

---

## Phase 2: Quality Scoring Module (Week 1-2)

**Goal**: Extract audio quality analysis into testable module with caching

**Rationale**: Quality analysis is expensive (FFmpeg subprocess) and should be cached

### Tasks

#### 2.1 Implement Quality Analyzer
**File**: `blink_pipeline/composition/quality.py`

```python
# Implement QualityAnalyzer protocol and FFmpegAudioQualityAnalyzer
# Extract _calculate_audio_quality() logic from composer

class FFmpegAudioQualityAnalyzer:
    def analyze(self, video_path: str) -> QualityMetrics:
        # Extract FFmpeg astats parsing logic
        # Return structured QualityMetrics
        ...

    def score(
        self,
        metrics: QualityMetrics,
        weights: AudioQualityWeights
    ) -> QualityScore:
        # Extract scoring calculation
        # Return QualityScore with component breakdown
        ...
```

**Test**:
```python
# tests/unit/test_quality_scoring.py
def test_analyze_with_mock_ffmpeg(mocker):
    """Test analysis without running actual FFmpeg."""
    mock_output = """
    [Parsed_astats_0 @ 0x...] Overall
    RMS level dB: -25.3
    Peak level dB: -3.1
    RMS min dB: -45.2
    Peak count: 5
    """
    mocker.patch('subprocess.run', return_value=Mock(
        returncode=0,
        stderr=mock_output
    ))

    analyzer = FFmpegAudioQualityAnalyzer()
    metrics = analyzer.analyze("fake.mp4")

    assert metrics.rms_db == -25.3
    assert metrics.peak_db == -3.1

def test_scoring_normalization():
    """Test scoring produces values in 0-1 range."""
    metrics = QualityMetrics(-25, -3, -45, 0, 10.0)
    weights = AudioQualityWeights(rms=0.5, peak=0.3, noise=0.2)

    analyzer = FFmpegAudioQualityAnalyzer()
    score = analyzer.score(metrics, weights)

    assert 0 <= score.overall <= 1
    assert 0 <= score.rms_score <= 1
```

**Estimated Time**: 2 days

#### 2.2 Add Caching Layer
**File**: `blink_pipeline/composition/quality.py`

```python
class CachedQualityAnalyzer:
    """Wrapper that adds persistent caching to QualityAnalyzer."""

    def __init__(self, analyzer: QualityAnalyzer, cache_dir: Optional[str]):
        self.analyzer = analyzer
        self.cache_file = os.path.join(cache_dir, 'quality_cache.json') if cache_dir else None
        self._cache: Dict[str, QualityMetrics] = {}
        self._load_cache()

    def analyze(self, video_path: str) -> QualityMetrics:
        # Cache key based on path + mtime
        cache_key = self._make_cache_key(video_path)

        if cache_key in self._cache:
            return self._cache[cache_key]

        metrics = self.analyzer.analyze(video_path)
        self._cache[cache_key] = metrics
        self._save_cache()

        return metrics
```

**Test**:
```python
def test_caching_avoids_reanalysis(tmp_path, test_video):
    """Verify cached results are used."""
    cache_dir = str(tmp_path)
    analyzer = CachedQualityAnalyzer(
        FFmpegAudioQualityAnalyzer(),
        cache_dir
    )

    # First call
    metrics1 = analyzer.analyze(test_video)

    # Second call should use cache (much faster)
    import time
    start = time.time()
    metrics2 = analyzer.analyze(test_video)
    elapsed = time.time() - start

    assert metrics1 == metrics2
    assert elapsed < 0.1  # Should be instant from cache
```

**Estimated Time**: 1 day

#### 2.3 Integrate into MultiCameraComposer
**File**: `blink_pipeline/multi_camera_composer.py`

```python
class MultiCameraComposer:
    def __init__(self, config: Dict[str, Any]):
        # ...

        if self.feature_flags.use_new_quality_scorer:
            from blink_pipeline.composition.quality import (
                FFmpegAudioQualityAnalyzer,
                CachedQualityAnalyzer
            )
            base_analyzer = FFmpegAudioQualityAnalyzer()
            self.quality_analyzer = CachedQualityAnalyzer(
                base_analyzer,
                cache_dir='output/audio_cache'
            )
        else:
            self.quality_analyzer = None  # Use legacy path

    def _calculate_audio_quality(self, video_path: str, media_info: Any) -> float:
        if self.quality_analyzer:
            # New path
            metrics = self.quality_analyzer.analyze(video_path)
            score = self.quality_analyzer.score(
                metrics,
                self.config.quality_weights
            )
            return score.overall
        else:
            # Legacy path (existing implementation)
            # ... existing code
```

**Test**:
```python
def test_quality_scorer_integration(test_clips):
    """Verify new scorer produces equivalent results."""
    legacy_config = get_test_config()
    legacy_composer = MultiCameraComposer(legacy_config)

    new_config = legacy_config.copy()
    new_config['feature_flags'] = {
        'use_pydantic_config': True,
        'use_new_quality_scorer': True
    }
    new_composer = MultiCameraComposer(new_config)

    # Analyze same clips
    legacy_clips = legacy_composer._analyze_clips(test_clips)
    new_clips = new_composer._analyze_clips(test_clips)

    # Scores should be within tolerance
    for old, new in zip(legacy_clips, new_clips):
        assert abs(old.audio_quality_score - new.audio_quality_score) < 0.01
```

**Estimated Time**: 2 days

### Phase 2 Success Criteria

- ✅ Quality analysis extracted to separate module
- ✅ Caching implemented and tested
- ✅ Feature flag allows toggling
- ✅ Scores match legacy implementation (within 1%)
- ✅ Performance improvement measured (cache hit rate > 80% on re-runs)
- ✅ All integration tests pass

**Deliverables**:
- `blink_pipeline/composition/quality.py` (250 lines)
- `tests/unit/test_quality_scoring.py` (300 lines)
- `tests/integration/test_quality_integration.py` (100 lines)

---

## Phase 3: Alignment Engine (Week 2)

**Goal**: Extract alignment logic with caching and confidence scores

### Tasks

#### 3.1 Implement Alignment Engine
**File**: `blink_pipeline/composition/alignment.py`

```python
from blink_pipeline.av_alignment import estimate_offset_single_pair

class AlignmentEngine:
    def __init__(self, config: AlignmentConfig, cache_dir: Optional[str]):
        self.config = config
        self.cache = self._load_cache(cache_dir) if cache_dir else {}

    def align_clips(
        self,
        clips: List[CameraClip],
        reference: Optional[CameraClip] = None
    ) -> Dict[str, AlignmentResult]:
        """Compute alignment offsets using GCC-PHAT."""
        if not self.config.enabled:
            return {c.path: AlignmentResult(c.path, 0.0, 1.0, c.path) for c in clips}

        # Select reference (best audio if not specified)
        ref = reference or max(clips, key=lambda c: c.audio_quality_score)

        results = {}
        for clip in clips:
            if clip.path == ref.path:
                results[clip.path] = AlignmentResult(clip.path, 0.0, 1.0, ref.path)
                continue

            # Check cache
            cache_key = (ref.path, clip.path)
            if cache_key in self.cache:
                results[clip.path] = self.cache[cache_key]
                continue

            # Compute alignment
            result = self._align_pair(ref, clip)
            results[clip.path] = result
            self.cache[cache_key] = result

        return results
```

**Test**:
```python
def test_alignment_with_synthetic_audio(tmp_path):
    """Test alignment using generated audio signals."""
    # Generate two audio files with known offset
    ref_audio = generate_sine_wave(duration=10, freq=440)
    target_audio = add_delay(ref_audio, delay=0.5)  # 500ms delay

    ref_path = tmp_path / "ref.wav"
    target_path = tmp_path / "target.wav"
    write_wav(ref_path, ref_audio)
    write_wav(target_path, target_audio)

    engine = AlignmentEngine(AlignmentConfig())
    ref_clip = CameraClip(str(ref_path), "ref", 0.0, 10.0)
    target_clip = CameraClip(str(target_path), "target", 0.0, 10.0)

    results = engine.align_clips([ref_clip, target_clip])

    # Should detect 0.5s offset
    assert abs(results[str(target_path)].offset_seconds - 0.5) < 0.05
    assert results[str(target_path)].confidence > 0.8
```

**Estimated Time**: 2 days

#### 3.2 Integrate into Composer
```python
class MultiCameraComposer:
    def __init__(self, config: Dict[str, Any]):
        # ...

        if self.feature_flags.use_new_alignment:
            from blink_pipeline.composition.alignment import AlignmentEngine
            self.alignment_engine = AlignmentEngine(
                self.config.alignment,
                cache_dir='output/alignment_cache'
            )
        else:
            self.alignment_engine = None

    def compose_multi_camera_event(self, ...):
        # ...
        camera_clips = self._analyze_clips(video_clips)

        if self.alignment_engine:
            # New path
            alignment_results = self.alignment_engine.align_clips(camera_clips)
            self.alignment_engine.apply_offsets(camera_clips, alignment_results)
        else:
            # Legacy path
            if self._alignment_enabled:
                # ... existing alignment code
```

**Test**:
```python
def test_alignment_integration(test_clips):
    """Verify alignment produces equivalent offsets."""
    legacy_composer = MultiCameraComposer(legacy_config)
    new_composer = MultiCameraComposer(new_config_with_alignment_flag)

    legacy_clips = legacy_composer._analyze_clips(test_clips)
    new_clips = new_composer._analyze_clips(test_clips)

    # Apply alignment
    legacy_composer._estimate_alignment_offsets(legacy_clips)
    # (new composer already applied via feature flag)

    # Compare adjusted start times
    for old, new in zip(legacy_clips, new_clips):
        assert abs(old.start_time - new.start_time) < 0.01
```

**Estimated Time**: 1 day

### Phase 3 Success Criteria

- ✅ Alignment engine implemented with caching
- ✅ Confidence scores calculated
- ✅ Offsets match legacy implementation (within 10ms)
- ✅ Cache improves performance on re-runs
- ✅ All tests pass

**Deliverables**:
- `blink_pipeline/composition/alignment.py` (200 lines)
- `tests/unit/test_alignment_engine.py` (250 lines)

---

## Phase 4: Timeline Generator (Week 3)

**Goal**: Extract timeline generation with strategy pattern

**Risk**: HIGH - This is the core algorithm. Extensive testing required.

### Tasks

#### 4.1 Implement Strategy Base and Implementations
**File**: `blink_pipeline/composition/timeline.py`

```python
# Implement from INTERFACE_SPECIFICATIONS.md:
# - TimelineStrategy (abstract base)
# - TimelineContext
# - AudioQualityStrategy
# - TimeBasedStrategy
# - SpeechPeopleStrategy
# - TimelineGenerator
```

**Test**:
```python
def test_audio_quality_strategy():
    """Test strategy selects best audio."""
    clips = [
        CameraClip("clip1.mp4", "cam1", 0.0, 10.0, audio_quality_score=0.8),
        CameraClip("clip2.mp4", "cam2", 0.0, 10.0, audio_quality_score=0.6)
    ]

    strategy = AudioQualityStrategy()
    context = TimelineContext()

    selected = strategy.select_camera(0.0, 5.0, clips, context)
    assert selected.camera == "cam1"

def test_speech_people_strategy_with_speech(mocker):
    """Test speech-aware selection during speech."""
    clips = [...]
    speech_segments = [SpeechSegment(2.0, 8.0, "SPEAKER_00")]

    context = TimelineContext(speech_segments=speech_segments)
    strategy = SpeechPeopleStrategy(min_people=1)

    # During speech, should use best audio
    selected = strategy.select_camera(3.0, 5.0, clips, context)
    assert selected == max(clips, key=lambda c: c.audio_quality_score)

def test_timeline_generator_boundary_creation():
    """Test boundary creation from clip times."""
    clips = [
        CameraClip("c1.mp4", "cam1", 0.0, 10.0),
        CameraClip("c2.mp4", "cam2", 5.0, 15.0)
    ]

    generator = TimelineGenerator(
        AudioQualityStrategy(),
        AudioQualityStrategy()
    )

    video_timeline, audio_timeline = generator.generate(clips)

    # Should have 3 segments: [0-5], [5-10], [10-15]
    assert len(video_timeline) == 3
    assert video_timeline[0].start_time == 0.0
    assert video_timeline[0].duration == 5.0
```

**Estimated Time**: 3 days

#### 4.2 Integrate into Composer
```python
class MultiCameraComposer:
    def __init__(self, config: Dict[str, Any]):
        # ...

        if self.feature_flags.use_new_timeline_generator:
            self.timeline_generator = self._create_timeline_generator()
        else:
            self.timeline_generator = None

    def _create_timeline_generator(self) -> TimelineGenerator:
        """Factory for creating timeline generator with configured strategies."""
        if self.config.switching_strategy == SwitchingStrategy.AUDIO_QUALITY:
            video_strategy = AudioQualityStrategy()
        elif self.config.switching_strategy == SwitchingStrategy.SPEECH_PEOPLE:
            video_strategy = SpeechPeopleStrategy(
                min_people=self.config.people_detection.min_count
            )
        else:  # TIME_BASED
            video_strategy = TimeBasedStrategy()

        # Audio strategy typically best quality
        audio_strategy = AudioQualityStrategy()

        return TimelineGenerator(video_strategy, audio_strategy)

    def compose_multi_camera_event(self, ...):
        # ...

        if self.timeline_generator:
            # New path
            video_timeline, audio_timeline = self.timeline_generator.generate(
                camera_clips,
                speech_segments=parsed_speech_segments,
                people_detector=self._get_people_detector()
            )
        else:
            # Legacy path
            video_timeline, audio_timeline = self._generate_aligned_timelines(
                camera_clips
            )
```

**Test**:
```python
@pytest.mark.parametrize("strategy", [
    "time_based",
    "audio_quality",
    "speech_people"
])
def test_timeline_strategies_equivalence(strategy, test_clips):
    """Verify each strategy produces equivalent timeline to legacy."""
    legacy_config = get_test_config()
    legacy_config['multi_camera_composition']['switching_strategy'] = strategy
    legacy_composer = MultiCameraComposer(legacy_config)

    new_config = legacy_config.copy()
    new_config['feature_flags'] = {
        'use_pydantic_config': True,
        'use_new_timeline_generator': True
    }
    new_composer = MultiCameraComposer(new_config)

    # Generate timelines
    legacy_v, legacy_a = legacy_composer._generate_aligned_timelines(test_clips)
    new_v, new_a = new_composer.timeline_generator.generate(test_clips)

    # Compare (allow minor differences due to floating point)
    assert_timelines_equivalent(legacy_v, new_v, tolerance=0.01)
    assert_timelines_equivalent(legacy_a, new_a, tolerance=0.01)
```

**Estimated Time**: 2 days

### Phase 4 Success Criteria

- ✅ All strategies implemented and tested
- ✅ Timeline generation matches legacy (within 10ms per segment)
- ✅ Strategy pattern enables easy extension
- ✅ People detection integrated correctly
- ✅ Segment coalescing works
- ✅ All integration tests pass

**Deliverables**:
- `blink_pipeline/composition/timeline.py` (350 lines)
- `tests/unit/test_timeline_strategies.py` (400 lines)
- `tests/integration/test_timeline_integration.py` (200 lines)

---

## Phase 5: Rendering & Audio Processing (Week 3-4)

**Goal**: Extract FFmpeg generation and audio processing

**Risk**: HIGH - FFmpeg commands are complex and error-prone

### Tasks

#### 5.1 Implement Audio Processor
**File**: `blink_pipeline/composition/audio.py`

```python
class AudioProcessor:
    """Handles audio extraction, cleanup, and stitching."""

    def __init__(self, config: CompositionConfig):
        self.config = config

    def build_cleanup_filter(self) -> str:
        """Generate FFmpeg audio filter string."""
        filters = []

        if self.config.highpass_hz:
            filters.append(f"highpass=f={self.config.highpass_hz}")
        if self.config.lowpass_hz:
            filters.append(f"lowpass=f={self.config.lowpass_hz}")
        if self.config.denoise:
            filters.append(f"afftdn=nf=-25")
        if self.config.loudness_normalize:
            filters.append("loudnorm=I=-24:TP=-2:LRA=11")

        return ','.join(filters) if filters else None

    def extract_segments(
        self,
        timeline: List[CompositionSegment],
        output_dir: str
    ) -> List[str]:
        """Extract audio segments with cleanup filters applied."""
        cleanup_filter = self.build_cleanup_filter()
        segment_paths = []

        for i, seg in enumerate(timeline):
            output_path = os.path.join(output_dir, f"audio_{i:03d}.wav")

            cmd = [
                'ffmpeg', '-y', '-loglevel', 'error',
                '-ss', str(seg.source_start),
                '-i', seg.clip_path,
                '-t', str(seg.duration),
                '-vn'
            ]

            if cleanup_filter:
                cmd.extend(['-af', cleanup_filter])

            cmd.extend([
                '-acodec', 'pcm_s16le',
                '-ar', '48000',
                '-ac', '2',
                output_path
            ])

            subprocess.run(cmd, check=True)
            segment_paths.append(output_path)

        return segment_paths

    def stitch_with_crossfade(
        self,
        segment_paths: List[str],
        output_path: str,
        crossfade_seconds: float
    ) -> bool:
        """Concatenate segments with crossfades."""
        if len(segment_paths) == 1:
            shutil.copy(segment_paths[0], output_path)
            return True

        # Build acrossfade filter chain
        # ... (complex filter logic)
```

**Estimated Time**: 2 days

#### 5.2 Implement Overlay Generator
**File**: `blink_pipeline/composition/overlay.py`

```python
class OverlayGenerator:
    """Generates ASS/SRT subtitles for timestamps and review markers."""

    def generate_ass(
        self,
        timeline: List[CompositionSegment],
        event_start: datetime,
        output_path: str,
        review_segments: List[Tuple[float, float]] = None
    ) -> str:
        """Generate ASS subtitle file."""
        # Extract current _generate_timestamp_ass logic
        ...
```

**Estimated Time**: 1 day

#### 5.3 Implement Renderers
**File**: `blink_pipeline/composition/rendering.py`

```python
class SinglePassRenderer(CompositionRenderer):
    def render(self, video_timeline, audio_timeline, output_path, event_start):
        """Render using filter_complex."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build input map
            input_map = self._build_input_map(video_timeline, audio_timeline)

            # Generate overlay
            overlay_path = None
            if self.config.timestamp_overlay_enabled:
                overlay_path = self.overlay_generator.generate_ass(
                    video_timeline, event_start, tmpdir
                )

            # Build filter graph
            filter_complex = self._build_filter_graph(
                video_timeline,
                audio_timeline,
                input_map,
                overlay_path
            )

            # Execute FFmpeg
            return self._execute_ffmpeg(input_map, filter_complex, output_path)

class MultiPassRenderer(CompositionRenderer):
    """Legacy multi-pass renderer (fallback)."""
    # Extract existing multi-pass logic
    ...
```

**Estimated Time**: 3 days

#### 5.4 Integrate into Composer
```python
class MultiCameraComposer:
    def __init__(self, config: Dict[str, Any]):
        # ...

        if self.feature_flags.use_new_renderer:
            from blink_pipeline.composition.rendering import (
                SinglePassRenderer,
                MultiPassRenderer
            )
            from blink_pipeline.composition.audio import AudioProcessor
            from blink_pipeline.composition.overlay import OverlayGenerator

            self.audio_processor = AudioProcessor(self.config)
            self.overlay_generator = OverlayGenerator(self.config)

            if self.config.single_pass:
                self.renderer = SinglePassRenderer(
                    self.config,
                    self.audio_processor,
                    self.overlay_generator
                )
            else:
                self.renderer = MultiPassRenderer(self.config)
        else:
            self.renderer = None
```

**Test**:
```python
def test_renderer_produces_valid_output(tmp_path, test_timeline):
    """Verify renderer creates valid video file."""
    renderer = SinglePassRenderer(test_config, audio_proc, overlay_gen)

    output_path = tmp_path / "output.mp4"
    success = renderer.render(
        test_timeline.video,
        test_timeline.audio,
        str(output_path)
    )

    assert success
    assert output_path.exists()

    # Verify output properties
    info = probe_media_info(str(output_path))
    assert info.has_video
    assert info.has_audio
    assert info.duration > 0

def test_filter_graph_generation():
    """Test filter_complex string generation."""
    renderer = SinglePassRenderer(test_config, audio_proc, overlay_gen)

    filter_graph = renderer._build_filter_graph(
        video_timeline,
        audio_timeline,
        input_map,
        overlay_path=None
    )

    # Verify filter structure
    assert "trim=" in filter_graph
    assert "concat=" in filter_graph
    assert "acrossfade=" in filter_graph if len(audio_timeline) > 1 else True
```

**Estimated Time**: 2 days (integration + testing)

### Phase 5 Success Criteria

- ✅ Audio processor extracts and stitches correctly
- ✅ Overlay generator creates valid ASS files
- ✅ Single-pass renderer produces valid output
- ✅ Multi-pass renderer (fallback) works
- ✅ Output video matches legacy (perceptual similarity > 99%)
- ✅ All tests pass

**Deliverables**:
- `blink_pipeline/composition/audio.py` (200 lines)
- `blink_pipeline/composition/overlay.py` (180 lines)
- `blink_pipeline/composition/rendering.py` (400 lines)
- `tests/unit/test_audio_processor.py` (150 lines)
- `tests/unit/test_rendering.py` (250 lines)
- `tests/integration/test_end_to_end.py` (200 lines)

---

## Phase 6: Integration & Testing (Week 4)

**Goal**: Enable all flags, comprehensive testing, performance validation

### Tasks

#### 6.1 End-to-End Integration Tests
```python
# tests/integration/test_full_refactor.py

def test_all_modules_enabled(test_clips, test_speech):
    """Test with all refactored modules enabled."""
    config = get_test_config()
    config['feature_flags'] = {
        'use_pydantic_config': True,
        'use_new_quality_scorer': True,
        'use_new_alignment': True,
        'use_new_timeline_generator': True,
        'use_new_renderer': True
    }

    composer = MultiCameraComposer(config)

    success = composer.compose_multi_camera_event(
        video_clips=test_clips,
        output_path="test_output.mp4",
        speech_segments=test_speech
    )

    assert success
    assert os.path.exists("test_output.mp4")

    # Verify output quality
    info = probe_media_info("test_output.mp4")
    assert info.duration > 0
    assert info.has_audio and info.has_video

@pytest.mark.parametrize("strategy", [
    "time_based",
    "audio_quality",
    "speech_people"
])
def test_strategies_with_real_videos(strategy, real_video_clips):
    """Integration test with real video files."""
    # ... full composition with each strategy
```

**Estimated Time**: 2 days

#### 6.2 Performance Benchmarking
```python
# tests/benchmarks/benchmark_refactored.py

def benchmark_timeline_generation(benchmark, test_clips):
    """Benchmark timeline generation speed."""
    generator = TimelineGenerator(AudioQualityStrategy(), AudioQualityStrategy())

    result = benchmark(generator.generate, test_clips)

    # Should be fast (< 1s for 10 clips)
    assert benchmark.stats['mean'] < 1.0

def benchmark_full_composition(benchmark, test_clips):
    """Benchmark full composition pipeline."""
    composer = MultiCameraComposer(get_config_all_flags_enabled())

    result = benchmark(
        composer.compose_multi_camera_event,
        test_clips,
        "output.mp4"
    )

    # Compare to baseline
    baseline = load_baseline_perf()
    assert benchmark.stats['mean'] < baseline['mean'] * 1.05  # At most 5% slower
```

**Estimated Time**: 1 day

#### 6.3 Regression Testing
```python
# tests/regression/test_output_consistency.py

def test_output_matches_reference(test_clips, reference_output):
    """Verify refactored code produces equivalent output."""
    composer = MultiCameraComposer(get_config_all_flags_enabled())

    output_path = "test_output.mp4"
    composer.compose_multi_camera_event(test_clips, output_path)

    # Compare to reference
    similarity = compute_video_similarity(output_path, reference_output)

    # Should be perceptually identical (allowing for timestamp differences)
    assert similarity > 0.99

def test_timeline_determinism():
    """Verify timeline generation is deterministic."""
    composer = MultiCameraComposer(test_config)

    timeline1 = composer.timeline_generator.generate(test_clips)
    timeline2 = composer.timeline_generator.generate(test_clips)

    assert timeline1 == timeline2
```

**Estimated Time**: 2 days

### Phase 6 Success Criteria

- ✅ All integration tests pass with flags enabled
- ✅ Performance within 5% of baseline
- ✅ Output videos perceptually identical (>99% similarity)
- ✅ No memory leaks detected
- ✅ Test coverage > 90%

---

## Phase 7: Finalization & Rollout (Week 5)

**Goal**: Enable by default, remove legacy code, document

### Tasks

#### 7.1 Enable Refactored Modules by Default
```python
# blink_pipeline/composition/feature_flags.py

class CompositionFeatureFlags:
    def __init__(self, config: Dict[str, Any]):
        # Change all defaults to True
        self.use_pydantic_config = self._get_flag(
            config, 'use_pydantic_config',
            default=True  # Changed from False
        )
        # ... (all flags default to True)
```

**Estimated Time**: 0.5 days

#### 7.2 Remove Legacy Code
```python
# Mark old methods as deprecated
@deprecated("Use timeline_generator.generate() instead")
def _generate_aligned_timelines(self, clips):
    ...

# After 1-2 releases, remove completely
```

**Estimated Time**: 1 day

#### 7.3 Documentation
- Update README with new architecture
- Create architecture diagrams
- Document each module's API
- Add usage examples
- Migration guide for external users

**Estimated Time**: 2 days

#### 7.4 Performance Optimization Pass
- Profile hot paths
- Add caching where beneficial
- Optimize FFmpeg filter generation
- Parallel people detection (batch frames)

**Estimated Time**: 1.5 days

### Phase 7 Success Criteria

- ✅ Refactored code enabled by default
- ✅ Legacy code marked deprecated
- ✅ Documentation complete
- ✅ Performance optimized
- ✅ Ready for production release

---

## Rollback Plan

If critical issues are discovered:

### Immediate Rollback (< 5 minutes)
```bash
# Disable all feature flags via environment
export BLINK_COMPOSITION_PYDANTIC_CONFIG=false
export BLINK_COMPOSITION_NEW_QUALITY=false
export BLINK_COMPOSITION_NEW_ALIGNMENT=false
export BLINK_COMPOSITION_NEW_TIMELINE=false
export BLINK_COMPOSITION_NEW_RENDERER=false

# Or in config
config['feature_flags'] = {
    'use_pydantic_config': False,
    'use_new_quality_scorer': False,
    'use_new_alignment': False,
    'use_new_timeline_generator': False,
    'use_new_renderer': False
}
```

### Partial Rollback (Phase-Specific)
```python
# If only timeline generation has issues, disable that flag
config['feature_flags'] = {
    'use_pydantic_config': True,
    'use_new_quality_scorer': True,
    'use_new_alignment': True,
    'use_new_timeline_generator': False,  # Rollback this phase
    'use_new_renderer': True
}
```

### Git Rollback (Last Resort)
```bash
# Revert to last stable commit
git revert <refactor-commit-range>
git push origin main
```

---

## Success Metrics

### Code Quality
- ✅ Test coverage > 90% (currently ~45%)
- ✅ Cyclomatic complexity < 10 per function (currently 8.2 avg, 24 max)
- ✅ Module size < 500 lines (currently 1772)
- ✅ Type hint coverage 100% (new modules)

### Performance
- ✅ No regression > 5% on timeline generation
- ✅ No regression > 5% on rendering
- ✅ Cache hit rate > 80% on quality analysis re-runs
- ✅ Memory usage stable (no leaks)

### Maintainability
- ✅ New strategies can be added without touching core logic
- ✅ Unit tests don't require video files or FFmpeg
- ✅ Clear separation of concerns (config/analysis/timeline/rendering)
- ✅ Documentation complete and up-to-date

### Production Readiness
- ✅ All existing integration tests pass
- ✅ New integration tests cover refactored paths
- ✅ Performance benchmarks run in CI
- ✅ Feature flags allow gradual rollout
- ✅ Rollback plan tested

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Timeline generation changes break output | Medium | High | Extensive regression testing, feature flags, gradual rollout |
| Performance regression | Medium | Medium | Benchmarking, profiling, optimization pass |
| FFmpeg commands fail with edge cases | Low | High | Comprehensive test suite, fallback to multi-pass renderer |
| Integration issues between modules | Low | Medium | Integration tests at each phase boundary |
| Schedule slips | Medium | Low | Incremental approach allows partial delivery |
| Customer-facing bug in production | Low | Critical | Feature flags enable instant rollback |

---

## Timeline Summary

| Week | Phase | Deliverables | Risk |
|------|-------|--------------|------|
| 1 | Configuration + Quality | Pydantic models, Quality scorer with caching | Low |
| 2 | Alignment | Alignment engine with caching, Integration | Low-Med |
| 3 | Timeline Generation | Strategy pattern, All strategies implemented | High |
| 3-4 | Rendering | Audio processor, Overlay generator, Renderers | High |
| 4 | Integration & Testing | End-to-end tests, Benchmarks, Regression suite | Medium |
| 5 | Finalization | Enable by default, Docs, Optimization | Low |

**Total**: 5 weeks, 1 developer full-time

---

## Conclusion

This migration plan provides a **structured, low-risk approach** to refactoring the multi-camera composition system. The incremental nature allows for:

- **Continuous validation** at each phase
- **Quick rollback** if issues arise
- **Partial delivery** if timeline pressures require
- **Gradual learning curve** for the team

The refactored architecture will provide:
- **90% test coverage** (vs. current 45%)
- **<500 lines per module** (vs. current 1772-line monolith)
- **Type safety** with Pydantic and mypy
- **Extensibility** via strategy pattern
- **Performance** through caching and optimization

**Recommendation**: Begin Phase 1 immediately for the high-value customer release. The configuration models and quality scorer can be delivered in Week 1, providing immediate value (type safety, caching) without architectural risk.
