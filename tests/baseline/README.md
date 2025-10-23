# Baseline Tests and Benchmarks

This directory contains baseline tests and performance benchmarks established **before** the modular composition refactoring began. These serve as the source of truth for validating that refactoring doesn't break functionality or degrade performance.

## Purpose

1. **Functional Baseline**: Capture expected behavior of multi_camera_composer.py before refactoring
2. **Performance Baseline**: Establish performance metrics to compare against after refactoring
3. **Regression Detection**: Quickly identify any regressions introduced during refactoring

## Test Categories

### 1. Functional Baseline Tests (`test_baseline_functional.py`)
- Tests core composition functionality with real video clips
- Captures expected output characteristics (duration, resolution, audio properties)
- Validates timeline generation logic
- Verifies audio/video synchronization

### 2. Performance Benchmarks (`benchmark_baseline.py`)
- Measures execution time for key operations:
  - Configuration parsing
  - Audio quality analysis
  - Audio alignment (GCC-PHAT)
  - Timeline generation
  - FFmpeg rendering
- Captures memory usage patterns
- Records CPU utilization

### 3. Output Validation (`test_baseline_output.py`)
- Captures checksums/hashes of generated videos
- Records frame counts, audio samples, codec info
- Documents expected quality metrics

## Success Criteria

After refactoring, we must achieve:
- ✅ All functional tests pass with identical behavior
- ✅ Performance within ±5% of baseline (or better)
- ✅ Output video characteristics match baseline
- ✅ No memory leaks or resource exhaustion
- ✅ Error handling maintains same behavior

## Running Baseline Tests

```bash
# Run all baseline tests
pytest tests/baseline/ -v

# Run specific test category
pytest tests/baseline/test_baseline_functional.py -v
pytest tests/baseline/benchmark_baseline.py -v

# Run with performance profiling
pytest tests/baseline/ -v --profile
```

## Baseline Metrics (Established: 2025-10-23)

### Performance Baseline (Apple Silicon M1/M2)
- Configuration parsing: ~10ms
- Audio quality analysis (per clip): ~200-500ms (depends on clip length)
- Audio alignment (GCC-PHAT): ~100-300ms (depends on overlap)
- Timeline generation: ~50-200ms (depends on strategy and clip count)
- FFmpeg rendering (1080p, 30s clip): ~5-15s (with VideoToolbox HW encoding)

### Functional Baseline
- Timeline strategies: time_based, round_robin, audio_quality, speech_people
- Audio source selection: best_quality, first, longest
- Transition styles: cut, crossfade
- Audio cleanup: highpass, lowpass, denoise, loudnorm
- People detection: Vision (macOS) or HuggingFace
- Timestamp overlay: DST offset support

## Notes

- Baseline tests use **real test videos** from `tests/fixtures/test_videos/`
- Performance benchmarks run with **standard config** (config.yaml defaults)
- All tests run on the **original monolithic** multi_camera_composer.py
- Baseline established on branch: `main` (commit: before refactor/modular-composition-architecture)
