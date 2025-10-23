# Audio/Video Alignment and Camera Control

This document describes the audio/video alignment system and the enhanced camera control features for multi-camera composition.

## Table of Contents
1. [Audio/Video Alignment](#audiovideo-alignment)
2. [Camera Control System](#camera-control-system)
3. [Configuration Reference](#configuration-reference)

## Audio/Video Alignment

### Overview

This pipeline uses a robust, multi-window GCC-PHAT approach to align audio across cameras and smooth audio stitching between segments. For motion-triggered cameras, alignment is performed per-clip rather than per-camera.

### What Changed

- Multi-window GCC-PHAT analysis estimates per-clip base offset relative to the best-audio reference camera (fallback: filename timestamp when audio is unusable).
- Base offsets are applied to each clip's `start_time` to better synchronize video for that clip only (no global camera-wide assumption).
- Audio segment extraction applies the same per-clip base offset, keeping the audio bed aligned without re-timing video.
- Audio segments are stitched using FFmpeg `acrossfade` to remove clicks at boundaries while preserving total duration.

### How it Works

1. **Alignment windows:** For each clip vs the reference camera clip(s) that overlap in time, multiple windows (default 12 s, 50% hop) are analyzed. The GCC-PHAT time delay is computed per window and aggregated with the median.
2. **Fallback to timestamp:** If no usable windows exist (no overlap or decode issues), offset defaults to 0.0 so filename timestamps determine placement.
3. **Video timeline:** The per-clip base offset is applied to that clip's `start_time` (no per-frame resampling).
4. **Audio timeline:** Each segment's extraction `source_start` includes the same per-clip base offset to keep audio locked to the reference.
5. **Audio stitching:** Segment audio is joined with `acrossfade` (default 60 ms triangular curves) to eliminate clicks at joins.

### Performance Tuning

The alignment process is CPU-bound (NumPy operations). You can trade accuracy for speed:

**Fast alignment (50% faster):**
```yaml
audio_alignment:
  analysis_window_seconds: 8.0
  hop_seconds: 8.0
  sample_rate: 8000
```

**Balanced (default):**
```yaml
audio_alignment:
  analysis_window_seconds: 12.0
  hop_seconds: 6.0
  sample_rate: 16000
```

**Accurate (2x slower):**
```yaml
audio_alignment:
  analysis_window_seconds: 16.0
  hop_seconds: 4.0
  sample_rate: 48000
```

## Camera Control System

### Overview

The enhanced camera control system provides fine-grained control over which cameras are displayed and when, overriding the automatic selection algorithms when needed. This is useful for:

- **Privacy:** Exclude cameras from video (use audio only)
- **Quality:** Prefer specific cameras with better angles/lighting
- **Debugging:** Force specific cameras to verify alignment/quality
- **Story:** Create specific viewing sequences for events

### Features

#### 1. Camera Priority

Prefer specific cameras when quality scores are similar:

```yaml
camera_control:
  priority_cameras: ['FrontDoor', 'Entry', 'Backyard']
```

**Behavior:**
- When multiple cameras are available with similar quality, cameras earlier in the list are preferred
- Does not override quality-based selection when differences are significant
- Empty list means no priority (use algorithm defaults)

**Example:**
```
Available cameras: FrontDoor (score: 0.85), Entry (score: 0.84), Backyard (score: 0.83)
With priority: Shows FrontDoor (highest priority)
Without priority: Shows FrontDoor (highest score)
```

#### 2. Camera Exclusion

Prevent specific cameras from appearing in video (audio may still be used):

```yaml
camera_control:
  exclude_cameras: ['Garage', 'Storage']
```

**Behavior:**
- Excluded cameras are never shown in the final video
- Audio from excluded cameras can still be used if it has the best quality
- Useful for cameras with poor angles, privacy concerns, or quality issues

**Example:**
```
Available cameras: FrontDoor, Garage, Backyard
With exclude: Shows FrontDoor or Backyard only
Audio: May still use Garage if it has best audio quality
```

#### 3. Forced Camera Segments

Override all selection logic for specific time windows:

```yaml
camera_control:
  forced_segments:
    - camera: 'FrontDoor'
      start: 0.0    # Event start
      end: 10.0     # 10 seconds in
    - camera: 'Backyard'
      start: 25.0
      end: 35.0
```

**Behavior:**
- Highest priority - overrides all other selection logic
- Times are relative to event start (0 = first frame)
- Camera must be available (have footage) at the specified time
- If camera is unavailable, falls back to normal selection

**Use Cases:**
- Show specific camera during critical moments
- Create specific viewing sequences
- Debug alignment issues by forcing known-good camera
- Manual override for automated events

**Example:**
```
Event: 60 seconds, 3 cameras available
Config: Force FrontDoor for 0-10s, Backyard for 25-35s
Result: FrontDoor (0-10s) → Auto (10-25s) → Backyard (25-35s) → Auto (35-60s)
```

#### 4. Minimum Display Duration

Prevent rapid camera switching by enforcing minimum display time:

```yaml
camera_control:
  min_display_duration: 2.0  # seconds
```

**Behavior:**
- Once a camera is shown, it stays on screen for at least this duration
- Prevents jarring rapid switches between cameras
- Applied after other selection rules
- Does not apply to forced segments (those can be any duration)

**Example:**
```
Without min_duration: A (0.5s) → B (0.5s) → C (0.5s) → A (0.5s) [jarring]
With min_duration=2.0: A (2.0s) → B (2.0s) → C (2.0s) [smooth]
```

#### 5. Video Quality Preference

Prefer better video quality when audio quality is similar:

```yaml
camera_control:
  prefer_video_quality_threshold: 0.05
```

**Behavior:**
- When `switching_strategy` is `audio_quality` or `speech_people`
- If audio scores are within threshold, pick camera with better video quality
- Balances audio and video quality for best overall result
- Threshold of 0.05 means audio scores must differ by <5% to consider video

**Example:**
```
Camera A: audio=0.85, video=0.90
Camera B: audio=0.87, video=0.70
Difference: 0.02 (within 0.05 threshold)
Result: Shows Camera A (better video, similar audio)
```

#### 6. Selection Reasoning Logging

Log camera selection decisions for debugging and analysis:

```yaml
camera_control:
  log_selection_reasoning: true
```

**Output Example:**
```
INFO: Camera control: Forcing FrontDoor at 5.2s (forced segment 0.0-10.0s)
DEBUG: Camera control: Prioritizing Entry at 15.8s (priority #2)
DEBUG: Camera control: Selected FrontDoor at 32.5s (similar audio, better video: 0.92)
INFO: Camera control fallback: Using Backyard at 45.1s (all preferred cameras unavailable)
```

### Selection Algorithm

The camera selection process follows this priority order:

1. **Check forced segments** - If time falls within a forced segment, use that camera
2. **Filter excluded cameras** - Remove cameras in `exclude_cameras` list
3. **Apply minimum duration** - Continue previous camera if min_display_duration not met
4. **Apply priority** - Sort remaining cameras by priority list
5. **Apply strategy** - Use configured switching strategy (audio_quality, speech_people, etc.)
6. **Apply video preference** - If audio similar, prefer better video quality
7. **Fallback** - If all rules filtered out cameras, use best audio quality

### Integration with Switching Strategies

Camera control works with all switching strategies:

#### time_based
```yaml
switching_strategy: time_based
camera_control:
  priority_cameras: ['FrontDoor', 'Entry']
  min_display_duration: 5.0
```
Switches at regular intervals, but prefers priority cameras and enforces minimum duration.

#### round_robin
```yaml
switching_strategy: round_robin
camera_control:
  exclude_cameras: ['Garage']
  min_display_duration: 3.0
```
Cycles through available cameras, skipping excluded ones, minimum 3s per camera.

#### audio_quality
```yaml
switching_strategy: audio_quality
camera_control:
  priority_cameras: ['FrontDoor']
  prefer_video_quality_threshold: 0.05
```
Prefers best audio, but favors FrontDoor when similar, and considers video quality.

#### speech_people
```yaml
switching_strategy: speech_people
camera_control:
  forced_segments:
    - camera: 'FrontDoor'
      start: 0.0
      end: 5.0
  min_display_duration: 2.5
```
Anchors to speaking camera or most people, but forces FrontDoor at start and prevents rapid switching.

### Best Practices

1. **Start minimal** - Use camera control sparingly, let algorithms work first
2. **Debug with logging** - Enable `log_selection_reasoning` to understand decisions
3. **Test incrementally** - Add one rule at a time and verify behavior
4. **Forced segments last** - Use forced segments only when other rules don't work
5. **Balance duration** - min_display_duration of 2-3s prevents jarring but stays responsive
6. **Video threshold tuning** - 0.05 is good default, increase to prioritize audio more

### Example Configurations

#### Privacy-Focused
```yaml
camera_control:
  exclude_cameras: ['Bedroom', 'Bathroom']
  priority_cameras: ['Entry', 'Hallway']
```

#### Quality-Focused
```yaml
camera_control:
  priority_cameras: ['FrontDoor4K', 'Entry4K']
  prefer_video_quality_threshold: 0.10  # Prioritize video more
  min_display_duration: 3.0
```

#### Manual Control
```yaml
camera_control:
  forced_segments:
    - camera: 'FrontDoor'
      start: 0.0
      end: 15.0
    - camera: 'Backyard'
      start: 30.0
      end: 45.0
  priority_cameras: ['FrontDoor', 'Entry']
```

#### Smooth Playback
```yaml
camera_control:
  min_display_duration: 4.0  # Longer stability
  prefer_video_quality_threshold: 0.08
  log_selection_reasoning: false  # Less logging
```


## Configuration Reference

### Audio Alignment Configuration

Under `multi_camera_composition.audio_alignment`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | true | Enable/disable audio alignment |
| `max_shift_seconds` | float | 1.0-1.5 | Maximum time shift to search (clamps estimate) |
| `analysis_window_seconds` | float | 12.0 | Window length for each GCC-PHAT analysis |
| `hop_seconds` | float | 6.0 | Hop between analysis windows (default: window/2) |
| `sample_rate` | int | 16000 | Downsample rate for alignment analysis |
| `bandpass` | bool | true | Apply speech-focused bandpass filter |
| `highpass_hz` | int | 300 | High-pass filter cutoff (removes rumble) |
| `lowpass_hz` | int | 3000 | Low-pass filter cutoff (removes high noise) |
| `estimate_drift` | bool | true | Estimate slow linear drift (deprecated for per-clip offsets) |

### Audio Stitching Configuration

At `multi_camera_composition` level:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `audio_crossfade_seconds` | float | 0.06 | Crossfade duration when stitching audio segments |

### Camera Control Configuration

Under `multi_camera_composition.camera_control`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `priority_cameras` | list[str] | [] | Camera priority list (prefer earlier cameras) |
| `exclude_cameras` | list[str] | [] | Cameras to exclude from video (audio-only) |
| `forced_segments` | list[dict] | [] | Force specific cameras at specific times |
| `min_display_duration` | float | 2.0 | Minimum time to show a camera before switching |
| `prefer_video_quality_threshold` | float | 0.05 | If audio similar, prefer better video quality |
| `log_selection_reasoning` | bool | true | Log camera selection decisions |

#### Forced Segment Format

Each forced segment is a dictionary:
```yaml
forced_segments:
  - camera: 'CameraName'  # Camera identifier (must match exactly)
    start: 0.0            # Start time in seconds (relative to event start)
    end: 10.0             # End time in seconds (relative to event start)
```

## Notes and Trade-Offs

- **Drift correction:** Applied to audio only to avoid re-timing video across cameras. This keeps visual cuts/continuity stable and focuses precision where it matters most perceptually.
- **Audio switching:** If audio selection switches between cameras, both the per-segment dynamic offset and the crossfade help hide tiny discontinuities.
- **Video crossfades:** Currently not implemented. Video uses hard cuts for stability. Video crossfades can be added later using FFmpeg `xfade` filter (requires single filter graph with all video segments).
- **Camera control performance:** Forced segments and exclusions have minimal performance impact. Priority sorting happens once per segment boundary.
- **Alignment caching:** Alignment results are cached in `output/audio_cache` when `use_modular_composition: true`. Delete cache to re-compute alignment.

## Implementation Files

- **`blink_pipeline/av_alignment.py`:** Multi-window GCC-PHAT alignment. Includes `estimate_per_clip_offsets()` for motion-triggered clips.
- **`blink_pipeline/multi_camera_composer.py`:** Integration of per-clip offsets, audio acrossfade stitching, and camera control system.
- **`blink_pipeline/people_detection.py`:** Hugging Face DETR/YOLOS-based people counter for `speech_people` strategy.
- **`blink_pipeline/composition/alignment.py`:** Modular alignment engine with caching support.

## Debugging

### Enable Alignment Debugging

```yaml
logging:
  log_level: DEBUG

multi_camera_composition:
  camera_control:
    log_selection_reasoning: true
```

### Check Alignment Logs

Look for lines like:
```
DEBUG: Estimated alignment offset for Camera2 vs Camera1: +0.12s
DEBUG: Applied per-clip offset to audio: Camera2 +0.15s
INFO: Audio alignment: ref=Camera1, Camera2=+0.12s, Camera3=-0.08s
```

### Check Camera Selection Logs

```
INFO: Camera control: Forcing FrontDoor at 5.2s (forced segment 0.0-10.0s)
DEBUG: Camera control: Prioritizing Entry at 15.8s (priority #2)
DEBUG: Camera control: Continuing FrontDoor at 17.2s (min_display_duration=2.0s)
```

### Verify Alignment Quality

1. **Listen for audio discontinuities:** Clicks, pops, or echo at camera switches indicate misalignment
2. **Check sync:** Watch for lip-sync issues if switching between cameras during speech
3. **Test different windows:** If alignment is poor, try larger windows or higher sample rate
4. **Disable if problematic:** Set `audio_alignment.enabled: false` to use timestamp-only alignment

### Verify Camera Control

1. **Check forced segments:** Ensure specified cameras appear at expected times
2. **Check exclusions:** Verify excluded cameras never appear in video
3. **Check priorities:** When multiple cameras available, verify preferred ones are chosen
4. **Check durations:** Ensure cameras stay on screen for at least min_display_duration

## Future Enhancements

Potential improvements for alignment and camera control:

1. **GPU-accelerated alignment:** Port NumPy cross-correlation to CuPy (CUDA) or Metal Performance Shaders (MPS)
2. **Visual alignment:** Use optical flow or feature matching for video synchronization
3. **Per-camera calibration:** Save learned offsets and reuse across events
4. **Smart camera selection:** ML model to predict best camera based on scene content
5. **Interactive review:** UI for manual camera selection and forced segment creation
6. **Video crossfades:** Implement smooth video transitions using FFmpeg xfade filter
7. **Dynamic priority:** Adjust camera priority based on detected scene content (faces, motion, etc.)

