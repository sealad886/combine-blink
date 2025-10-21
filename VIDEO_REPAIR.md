# Video Repair System

## Overview

The Blink Video Processing Pipeline now includes automatic video repair to handle damaged clips caused by connectivity issues. This document explains how the repair system works and how to configure it.

## Problem Statement

Blink security cameras sometimes save damaged video clips with:
- **Missing video frames** due to network connectivity issues
- **Desynchronized audio/video streams** where durations don't match
- **Corrupted h264 frames** that cause decoder errors

These issues manifest as:
- h264 decoder errors: `[h264 @ ...] no frame!`
- Error messages: `Error submitting packet to decoder: Invalid data found`
- Audio and video streams with different durations
- Gaps in video playback while audio continues

## Solution

The video repair system automatically:
1. **Detects issues** by comparing audio/video stream durations
2. **Fills missing frames** using the last known good frame (creates static-like images)
3. **Synchronizes streams** by trimming excess video or padding audio
4. **Maintains audio continuity** ensuring uninterrupted audio playback
5. **Caches results** to avoid re-processing the same clips

## How It Works

### Detection

The system probes each video file to check:
```python
video_duration = 10.5 seconds
audio_duration = 10.3 seconds
difference = 0.2 seconds  # > 0.1s threshold → repair needed
```

### Repair Process

1. **Frame Rate Normalization**: Forces consistent 25 fps (common for Blink cameras)
   ```
   ffmpeg filter: fps=fps=25
   ```

2. **Video Trimming**: If video is longer than audio, trim to match
   ```
   ffmpeg filter: trim=duration={audio_duration}
   ```

3. **Audio Padding**: If audio is shorter than video, pad with silence
   ```
   ffmpeg filter: apad=pad_dur={difference}
   ```

4. **Error Handling**: Ignores corrupted frames gracefully
   ```
   ffmpeg flag: -err_detect ignore_err
   ```

### Output

Repaired videos are:
- Re-encoded with H.264 for consistency
- Saved with AAC audio at 128k bitrate
- Optimized for streaming with faststart flag
- Cached to avoid re-processing

## Configuration

Edit `config.yaml` to control repair behavior:

```yaml
transcription:
  # Repair all videos vs only when issues detected
  always_repair: false  # false = auto-detect, true = always repair

  # Directory to cache repaired videos
  repair_cache_dir: "output/repaired_cache"  # or null to disable
```

### Configuration Options

#### `always_repair`
- **false** (default): Only repair when audio/video duration differs by >100ms
- **true**: Repair all videos regardless of detected issues

#### `repair_cache_dir`
- **Path string**: Cache repaired videos in this directory
- **null**: Disable caching (repair on every run)

## Usage

### Automatic Repair (Default)

The repair system runs automatically during transcription:

```bash
python3 main.py
```

Output:
```
Processing 5 clips sequentially for transcription
  [1/5] Processing clip: 08-37-43_CornerG8T1K0013255014P_081.mp4
    → Repairing video (audio/video sync or corrupted frames)
    ✓ Video repaired successfully
    → Transcribing audio (10.3s)...
```

### Manual Testing

To test repair on a specific file:

```python
from src.media_utils import repair_video

success = repair_video(
    video_path="input/damaged_clip.mp4",
    output_path="output/repaired_clip.mp4",
    cache_dir="output/repaired_cache"
)
```

### Cache Management

Cached repairs are stored as:
```
output/repaired_cache/
  repaired_08-37-43_CornerG8T1K0013255014P_081.mp4
  repaired_08-38-15_FrontDoorG9876543210XYZ_082.mp4
```

To clear the cache:
```bash
rm -rf output/repaired_cache
```

## Performance Impact

### First Run (with repair)
- **Detection**: ~0.1s per clip (ffprobe)
- **Repair**: ~2-5s per clip (depends on length and CPU)
- **Caching**: ~0.5s per clip (file copy)
- **Total overhead**: ~3-6s per damaged clip

### Subsequent Runs (cached)
- **Cache lookup**: ~0.1s per clip
- **Cache copy**: ~0.5s per clip
- **Total overhead**: ~0.6s per clip

### Without Repair
If you disable repair (`always_repair: false` and no sync issues):
- **Detection**: ~0.1s per clip
- **No repair performed**
- **Total overhead**: ~0.1s per clip

## Technical Details

### FFmpeg Command

The repair system builds an ffmpeg command like:

```bash
ffmpeg -y \
  -loglevel error \
  -err_detect ignore_err \
  -i input.mp4 \
  -vf "fps=fps=25,trim=duration=10.3,setpts=PTS-STARTPTS" \
  -af "apad=pad_dur=0.2" \
  -c:v libx264 -preset fast -crf 23 \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  output.mp4
```

### Video Filters
- `fps=fps=25`: Force 25 fps frame rate
- `trim=duration=X`: Trim video to X seconds
- `setpts=PTS-STARTPTS`: Reset timestamps after trim

### Audio Filters
- `apad=pad_dur=X`: Add X seconds of silence at end

### Encoding
- `libx264`: H.264 video codec
- `preset fast`: Balance speed vs compression
- `crf 23`: Constant quality (23 = good quality)
- `aac`: AAC audio codec
- `b:a 128k`: 128 kbps audio bitrate

### Error Handling
- `err_detect ignore_err`: Continue on corrupted frames
- `loglevel error`: Only show actual errors
- Timeout: 300 seconds max per repair

## Limitations

### Known Limitations

1. **Frame Rate Assumption**: Assumes 25 fps (adjust in code if different)
2. **Re-encoding**: All videos are re-encoded (adds processing time)
3. **Quality Loss**: Minimal quality loss from re-encoding (CRF 23)
4. **Disk Space**: Cached repairs take up disk space

### When Repair May Not Help

- **Completely missing streams**: If audio or video is entirely missing
- **Extreme corruption**: If more than 50% of frames are corrupted
- **Audio glitches**: Repair doesn't fix corrupted audio data

## Troubleshooting

### Problem: "ffmpeg repair failed"

**Possible causes:**
- ffmpeg not installed or not in PATH
- Input file severely corrupted
- Insufficient disk space

**Solutions:**
```bash
# Check ffmpeg installation
which ffmpeg
ffmpeg -version

# Check disk space
df -h

# Try manual repair
ffmpeg -i damaged.mp4 -c copy test_output.mp4
```

### Problem: "ffmpeg repair timed out"

**Possible causes:**
- Very large video file (>5 minutes)
- Slow CPU or disk

**Solutions:**
- Increase timeout in `repair_video()` function
- Use faster storage (SSD vs HDD)
- Reduce video resolution before repair

### Problem: Repairs not cached

**Check:**
```python
# In config.yaml
repair_cache_dir: "output/repaired_cache"  # Must not be null

# Verify directory creation
import os
os.makedirs("output/repaired_cache", exist_ok=True)
```

### Problem: Cache grows too large

**Solution:**
```bash
# Clear old repairs
find output/repaired_cache -mtime +30 -delete  # Delete >30 days old

# Or clear all
rm -rf output/repaired_cache/*
```

## Future Enhancements

Potential improvements:
- [ ] Smart frame interpolation instead of duplication
- [ ] Audio repair (not just video)
- [ ] Configurable frame rate detection
- [ ] Parallel repair of multiple clips
- [ ] Progress reporting for long repairs
- [ ] Automatic cache cleanup based on age/size

## Contributing

If you encounter issues or have suggestions:
1. Check the troubleshooting section
2. Review the ffmpeg logs (`-loglevel error`)
3. Test with `ffmpeg` directly to isolate the issue
4. Submit an issue with: input file characteristics, error logs, ffmpeg version

## References

- ffmpeg documentation: https://ffmpeg.org/ffmpeg.html
- h264 decoder: https://ffmpeg.org/ffmpeg-codecs.html#h264
- Audio filters: https://ffmpeg.org/ffmpeg-filters.html#Audio-Filters
- Video filters: https://ffmpeg.org/ffmpeg-filters.html#Video-Filters
