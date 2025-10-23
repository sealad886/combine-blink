# Encoding Configuration Analysis

## Executive Summary

**Critical Finding:** The codebase has significant documentation errors regarding hardware vs. software encoding. The **code implementation is correct**, but the **documentation is backwards** in multiple places.

### Core Misunderstanding

- **libx264** = SOFTWARE encoder (CPU-based, x264 library)
- **h264_videotoolbox** = HARDWARE encoder (macOS VideoToolbox API, uses Media Engine/GPU)

## Current Configuration (CORRECT)

**File:** `config.yaml` lines 129-136

```yaml
encoding:
    # MPS optimization: Use VideoToolbox hardware encoding on macOS for ~5-10x faster encoding
    # with excellent quality. Falls back to software if hardware encoder unavailable.
    use_hw_encode: true         # Enable hardware encoding on macOS (h264_videotoolbox)
    hw_codec: h264_videotoolbox # VideoToolbox for Apple Silicon/Intel Macs
    x264_preset: null           # Software fallback: 'faster' balances speed/quality (upgrade from 'veryfast')
    x264_crf: null              # Software fallback: CRF 20 for higher quality (down from 22)
    bitrate: 8000k              # VideoToolbox target: 8Mbps for excellent 1080p quality (up from 6Mbps)
```

✅ **This configuration is CORRECT:**
- `hw_codec: h264_videotoolbox` correctly specifies the macOS hardware encoder
- `x264_preset` and `x264_crf` correctly specify software fallback parameters
- Comments accurately describe hardware vs. software

## Code Implementation (CORRECT)

**File:** `blink_pipeline/multi_camera_composer.py` lines 1485-1501

```python
def _video_codec_args(self) -> List[str]:
    """Return ffmpeg args for chosen video encoder."""
    if self._use_hw_encode:
        # Hardware encoder (macOS videotoolbox). Use bitrate-based control.
        return [
            '-c:v', self._hw_codec,  # Uses h264_videotoolbox from config
            '-b:v', self._target_bitrate,
            '-pix_fmt', 'yuv420p',
        ]
    # x264 software encoder
    return [
        '-c:v', 'libx264',  # Hardcoded libx264 for software fallback
        '-preset', self._x264_preset,
        '-crf', self._x264_crf,
        '-pix_fmt', 'yuv420p',
    ]
```

✅ **This implementation is CORRECT:**
- When `use_hw_encode: true`, uses `self._hw_codec` (h264_videotoolbox)
- When `use_hw_encode: false`, falls back to hardcoded libx264
- Comments accurately describe the behavior

## Issues Found

### 1. MPS_OPTIMIZATION_NOTES.md (CRITICAL ERROR)

**File:** `MPS_OPTIMIZATION_NOTES.md` lines 8-18

**Current (INCORRECT):**
```markdown
### 1. Hardware Video Encoding (VideoToolbox)
**Change:** Enabled `use_hw_encode: true` with `libx264`
**Impact:** ~5-10x faster video encoding vs software (libx264)
**Quality:** Increased bitrate to 8Mbps (from 6Mbps) for excellent 1080p quality
**Benefit:** Apple Silicon's dedicated Media Engine handles encoding off-CPU, freeing resources for other tasks

```yaml
encoding:
  use_hw_encode: true         # Enable VideoToolbox
  hw_codec: libx264
  bitrate: 8000k              # 8Mbps for high quality
```
```

❌ **Problems:**
1. Line 9: "Enabled hardware encoding with libx264" - **BACKWARDS**: libx264 is SOFTWARE
2. Line 10: "faster than software (libx264)" - Confusing because line 9 said hardware IS libx264
3. Line 17: Shows `hw_codec: libx264` as example - **INCORRECT**: Should be `h264_videotoolbox`

**Should Be:**
```markdown
### 1. Hardware Video Encoding (VideoToolbox)
**Change:** Enabled `use_hw_encode: true` with `h264_videotoolbox` (hardware encoder)
**Impact:** ~5-10x faster video encoding vs software (libx264)
**Quality:** Increased bitrate to 8Mbps (from 6Mbps) for excellent 1080p quality
**Benefit:** Apple Silicon's dedicated Media Engine handles encoding off-CPU, freeing resources for other tasks

```yaml
encoding:
  use_hw_encode: true         # Enable VideoToolbox hardware acceleration
  hw_codec: h264_videotoolbox # macOS hardware encoder (NOT libx264)
  bitrate: 8000k              # 8Mbps for high quality (hardware uses bitrate control)
```
```

### 2. docs/reference/configuration.md (INCORRECT EXAMPLE)

**File:** `docs/reference/configuration.md` lines 111-112

**Current (INCORRECT):**
```yaml
    use_hw_encode: false            # Enable hardware encode (videotoolbox/qsv/amf/nvenc)
    hw_codec: libx264     # Used when use_hw_encode is true
```

❌ **Problem:** Shows `hw_codec: libx264` which is SOFTWARE, not hardware

**Should Be:**
```yaml
    use_hw_encode: true             # Enable hardware encode (videotoolbox/qsv/amf/nvenc)
    hw_codec: h264_videotoolbox     # Hardware codec (macOS: h264_videotoolbox, Windows: h264_nvenc/h264_qsv/h264_amf)
```

### 3. multi_camera_composer.py (INCORRECT DEFAULT)

**File:** `blink_pipeline/multi_camera_composer.py` line 224

**Current (INCORRECT):**
```python
self._hw_codec = str(enc_cfg.get('hw_codec', 'libx264'))
```

❌ **Problem:** Default value is `libx264` (software), not a hardware codec

**Should Be:**
```python
# Default to platform-appropriate hardware encoder
import platform
default_hw_codec = 'h264_videotoolbox' if platform.system() == 'Darwin' else 'libx264'
self._hw_codec = str(enc_cfg.get('hw_codec', default_hw_codec))
```

Or at minimum:
```python
self._hw_codec = str(enc_cfg.get('hw_codec', 'h264_videotoolbox'))  # Default to macOS hardware encoder
```

### 4. MPS_OPTIMIZATION_NOTES.md Rollback Section (INCORRECT)

**File:** `MPS_OPTIMIZATION_NOTES.md` lines 122-126

**Current (INCONSISTENT):**
```yaml
encoding:
  use_hw_encode: false
  x264_preset: veryfast
  x264_crf: '22'
```

⚠️ **Issue:** Missing `hw_codec` in rollback config (would use incorrect default 'libx264')

**Should Be:**
```yaml
encoding:
  use_hw_encode: false           # Disable hardware encoding
  hw_codec: h264_videotoolbox   # Still specify, even if not used when hw disabled
  x264_preset: veryfast          # Software fallback settings
  x264_crf: '22'
```

## FFmpeg Encoder Reference

### Hardware Encoders (Platform-Specific)

| Codec Name | Platform | Hardware | Performance | Quality |
|------------|----------|----------|-------------|---------|
| **h264_videotoolbox** | macOS | Media Engine/GPU | Very Fast | Good |
| **hevc_videotoolbox** | macOS | Media Engine/GPU | Very Fast | Excellent |
| **h264_nvenc** | Windows/Linux | NVIDIA GPU | Very Fast | Good |
| **hevc_nvenc** | Windows/Linux | NVIDIA GPU | Very Fast | Excellent |
| **h264_qsv** | Windows/Linux | Intel QuickSync | Fast | Good |
| **h264_amf** | Windows/Linux | AMD GPU | Fast | Good |

### Software Encoders (Cross-Platform)

| Codec Name | Platform | Hardware | Performance | Quality |
|------------|----------|----------|-------------|---------|
| **libx264** | All | CPU | Slow | Excellent |
| **libx265** | All | CPU | Very Slow | Outstanding |
| **libvpx-vp9** | All | CPU | Very Slow | Excellent |

## How Encoding Selection Works

### Flow Diagram

```
User sets use_hw_encode in config.yaml
           ↓
multi_camera_composer.py reads config
           ↓
_video_codec_args() is called
           ↓
    ┌─────────────────┐
    │ use_hw_encode?  │
    └────────┬────────┘
             │
     ┌───────┴────────┐
     ↓                ↓
   TRUE             FALSE
     │                │
     ↓                ↓
Use hw_codec     Use libx264
from config      (hardcoded)
     │                │
     ↓                ↓
h264_videotoolbox  libx264 + preset + crf
+ bitrate
+ yuv420p
```

### Configuration Parameters

**Hardware Path (`use_hw_encode: true`):**
- `hw_codec`: Name of hardware encoder (e.g., `h264_videotoolbox`)
- `bitrate`: Target bitrate (e.g., `8000k`)
- Quality control: **Bitrate-based** (hardware encoders use bitrate, not CRF)

**Software Path (`use_hw_encode: false`):**
- Codec: **Hardcoded** to `libx264` in code
- `x264_preset`: Speed vs. quality tradeoff (e.g., `faster`, `veryfast`, `medium`)
- `x264_crf`: Constant Rate Factor (lower = higher quality, e.g., `20`, `22`)
- Quality control: **CRF-based** (perceptual quality target)

## Usage in Other Files

### video.py (Legacy Sequential Merge)

**File:** `blink_pipeline/video.py`

Uses environment variables instead of config:
- `CB_USE_HW="1"`: Enable hardware encoding
- `CB_HW_CODEC="h264_videotoolbox"`: Hardware codec name

✅ **Correctly defaults to `h264_videotoolbox`** (line 13, 45, 85, 121)

### Observation

The older `video.py` module **correctly** uses `h264_videotoolbox` as the default hardware codec. The newer `multi_camera_composer.py` has an incorrect default of `libx264`.

## Recommendations

### Immediate Fixes (High Priority)

1. **Fix MPS_OPTIMIZATION_NOTES.md:**
   - Replace all instances of `hw_codec: libx264` with `hw_codec: h264_videotoolbox`
   - Clarify that libx264 is SOFTWARE, h264_videotoolbox is HARDWARE
   - Update line 9 from "with libx264" to "with h264_videotoolbox"

2. **Fix docs/reference/configuration.md:**
   - Change example `hw_codec: libx264` to `hw_codec: h264_videotoolbox`
   - Add comments explaining hardware vs. software

3. **Fix multi_camera_composer.py default:**
   - Change default from `'libx264'` to `'h264_videotoolbox'`
   - Consider adding platform detection for Windows/Linux

### Future Enhancements (Medium Priority)

4. **Add codec validation:**
   - Detect if hardware codec is available before using it
   - Automatically fall back to software if hardware encoder fails
   - Log warnings when hardware encoding is unavailable

5. **Platform-aware defaults:**
   - macOS: `h264_videotoolbox` or `hevc_videotoolbox`
   - Windows with NVIDIA: `h264_nvenc`
   - Windows with Intel: `h264_qsv`
   - Windows with AMD: `h264_amf`
   - Fallback: `libx264`

6. **Add encoding presets:**
   - Preset: `hardware_fast` → Uses hardware encoder with moderate bitrate
   - Preset: `hardware_quality` → Uses hardware encoder with high bitrate
   - Preset: `software_fast` → libx264 with fast preset
   - Preset: `software_quality` → libx264 with slow preset, low CRF

### Documentation Improvements (Low Priority)

7. **Create encoding guide:**
   - Explain hardware vs. software encoding
   - List supported hardware encoders per platform
   - Provide benchmarks and quality comparisons
   - Troubleshooting guide for encoding failures

8. **Add examples for different scenarios:**
   - macOS with Apple Silicon (hardware)
   - Windows with NVIDIA GPU (hardware)
   - Linux without GPU (software)
   - Quality-focused workflow (software + slow preset)
   - Speed-focused workflow (hardware + high bitrate)

## Testing Recommendations

### Verify Hardware Encoding is Active

```bash
# Run pipeline and check logs
python main.py

# Search logs for encoding codec
grep -i "codec\|encoder" logs/pipeline.log

# Expected for hardware: "-c:v h264_videotoolbox -b:v 8000k"
# Expected for software: "-c:v libx264 -preset faster -crf 20"
```

### Monitor Hardware Utilization

```bash
# macOS: Check VideoToolbox usage
# Activity Monitor > Window > GPU History
# Look for "Video Encoder" or "Video Decoder" activity

# Check if Media Engine is being used
pmset -g thermlog | grep -i "gpu\|media"
```

### Compare Performance

```bash
# Test hardware encoding (current default)
time python main.py

# Test software encoding
# Edit config.yaml: use_hw_encode: false
time python main.py

# Expected: Hardware should be 5-10x faster
```

## Summary

| Component | Status | Issue | Priority |
|-----------|--------|-------|----------|
| config.yaml | ✅ Correct | None | N/A |
| multi_camera_composer.py (logic) | ✅ Correct | None | N/A |
| multi_camera_composer.py (default) | ❌ Wrong | Default is 'libx264' instead of 'h264_videotoolbox' | High |
| MPS_OPTIMIZATION_NOTES.md | ❌ Wrong | Shows libx264 as hardware encoder | High |
| docs/reference/configuration.md | ❌ Wrong | Example shows libx264 as hw_codec | High |
| video.py | ✅ Correct | Correctly defaults to h264_videotoolbox | N/A |

**Bottom Line:** The system currently works correctly because `config.yaml` explicitly sets `hw_codec: h264_videotoolbox`. However, if that line were removed, the system would incorrectly default to software encoding even when `use_hw_encode: true`. The documentation also misleads users about which codec is hardware vs. software.
