# Audio/Video Alignment and Stitching (Revamped)

This pipeline now uses a robust, multi-window GCC-PHAT approach to align audio across cameras and smooth audio stitching between segments. For motion-triggered cameras, alignment is performed per-clip rather than per-camera.

## What changed

- Multi-window GCC-PHAT analysis estimates per-clip base offset relative to the best-audio reference camera (fallback: filename timestamp when audio is unusable).
- Base offsets are applied to each clip's `start_time` to better synchronize video for that clip only (no global camera-wide assumption).
- Audio segment extraction applies the same per-clip base offset, keeping the audio bed aligned without re-timing video.
- Audio segments are stitched using FFmpeg `acrossfade` to remove clicks at boundaries while preserving total duration.

## How it works

1. Alignment windows: For each clip vs the reference camera clip(s) that overlap in time, multiple windows (default 12 s, 50% hop) are analyzed. The GCC-PHAT time delay is computed per window and aggregated with the median.
2. Fallback to timestamp: If no usable windows exist (no overlap or decode issues), offset defaults to 0.0 so filename timestamps determine placement.
3. Video timeline: The per-clip base offset is applied to that clip's `start_time` (no per-frame resampling).
4. Audio timeline: Each segment's extraction `source_start` includes the same per-clip base offset to keep audio locked to the reference.
5. Audio stitching: Segment audio is joined with `acrossfade` (default 60 ms triangular curves) to eliminate clicks at joins.

## Configuration (config.yaml)

Under `multi_camera_composition.audio_alignment`:

- `enabled`: true|false
- `max_shift_seconds`: Max search window (default 1.0–1.5 s)
- `analysis_window_seconds`: Window length (default 12.0)
- `hop_seconds`: Hop length (default window/2)
- `sample_rate`: Analysis sample rate (default 16000)
- `bandpass`: Enable speech-focused bandpass
- `highpass_hz`, `lowpass_hz`: Bandpass cutoffs
- `estimate_drift`: Deprecated for motion-triggered clip alignment; per-clip base offsets are preferred.

At `multi_camera_composition` level:

- `audio_crossfade_seconds`: Crossfade duration when stitching audio (default 0.06 s)

## Notes and trade-offs

- Drift is applied to audio only to avoid re-timing video across cameras. This keeps visual cuts/continuity stable and focuses precision where it matters most perceptually.
- If audio selection switches between cameras, both the per-segment dynamic offset and the crossfade help hide tiny discontinuities.
- If desired, video crossfades can be added later using FFmpeg `xfade` (requires a single filter graph with all video segments).

## Implementation files

- `src/av_alignment.py`: Multi-window GCC-PHAT alignment. Adds `estimate_per_clip_offsets()` for motion-triggered clips.
- `src/multi_camera_composer.py`: Integration of per-clip offsets and audio acrossfade stitching; dynamic people detection for camera selection.
- `src/people_detection.py`: Hugging Face DETR-based people counter used during composition (no OpenCV).
