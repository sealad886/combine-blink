# Audio/Video Alignment and Stitching (Revamped)

This pipeline now uses a robust, multi-window GCC-PHAT approach to align audio across cameras and smooth audio stitching between segments.

## What changed

- Multi-window GCC-PHAT analysis estimates per-camera base offset and optional linear drift relative to the best-audio reference camera.
- Base offsets are applied to clip `start_time` to better synchronize video.
- A time-varying correction (base + drift × t) is applied to the audio segment extraction, aligning the audio bed precisely to the reference over time.
- Audio segments are stitched using FFmpeg `acrossfade` to remove clicks at boundaries while preserving total duration.

## How it works

1. Alignment windows: For each camera vs the reference camera, overlapping intervals are scanned with multiple windows (default 12 s, 50% hop). The GCC-PHAT time delay is computed per window and robustly aggregated (median).
2. Drift estimation: With enough windows, a linear regression of delay vs time provides a small drift term (bounded to ±1 ms/s) to compensate slow clock offsets.
3. Video timeline: Base alignment offsets are applied to clip `start_time` (video remains globally aligned without per-frame resampling).
4. Audio timeline: For each segment, the source start is adjusted by the time-local correction `offset_at(t) = base + drift × segment_start_time` to keep audio locked to the reference.
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
- `estimate_drift`: Enable drift estimation (default true)

At `multi_camera_composition` level:

- `audio_crossfade_seconds`: Crossfade duration when stitching audio (default 0.06 s)

## Notes and trade-offs

- Drift is applied to audio only to avoid re-timing video across cameras. This keeps visual cuts/continuity stable and focuses precision where it matters most perceptually.
- If audio selection switches between cameras, both the per-segment dynamic offset and the crossfade help hide tiny discontinuities.
- If desired, video crossfades can be added later using FFmpeg `xfade` (requires a single filter graph with all video segments).

## Implementation files

- `src/av_alignment.py`: Multi-window GCC-PHAT alignment and drift estimation.
- `src/multi_camera_composer.py`: Integration points for offset/drift and audio acrossfade stitching.
