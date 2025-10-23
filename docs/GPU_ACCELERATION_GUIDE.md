# GPU Acceleration Guide

This guide documents hardware GPU acceleration throughout the Blink video processing pipeline and provides optimization recommendations for different hardware configurations.

## Overview

The pipeline leverages hardware acceleration at multiple stages to maximize performance:

1. **Video Encoding/Decoding** - VideoToolbox (macOS), NVENC (NVIDIA), or other hardware encoders
2. **AI Model Inference** - MPS (Apple Silicon), CUDA (NVIDIA), or ROCm (AMD) acceleration
3. **Audio Processing** - FFmpeg hardware-accelerated filters where available
4. **Parallel Processing** - Multi-core CPU utilization for I/O-bound operations

## Hardware Acceleration by Pipeline Stage

### Stage 0: Video Validation & Repair
**GPU Usage:** Minimal (CPU/FFmpeg based)
**Acceleration:** 
- Parallel processing via worker threads (configurable: `concurrency.validation_workers`)
- FFmpeg hardware decoding for validation (automatic when available)

**Configuration:**
```yaml
concurrency:
  validation_workers: 6  # Increase for fast SSDs (I/O bound)
```

**Hardware Recommendations:**
- Apple Silicon: 4-6 workers (fast unified memory & SSD)
- Intel/AMD with SSD: 3-4 workers
- HDD systems: 2 workers (I/O bottleneck)

### Stage 3: Transcription & Diarization
**GPU Usage:** Heavy (AI model inference)
**Acceleration:**
- **Whisper Transcription:**
  - Core ML (Apple Neural Engine) - `device: coreml`
  - Metal GPU (Apple Silicon) - `device: metal` 
  - CUDA (NVIDIA) - `device: cuda`
  - CPU fallback - `device: cpu`
- **Pyannote Diarization:**
  - MPS (Apple Silicon) - automatic when available
  - CUDA (NVIDIA) - automatic when available
  - CPU fallback

**Configuration:**
```yaml
transcription:
  whisper:
    device: coreml  # or metal, cuda, cpu
    ggml_model_path: /path/to/coreml-encoder-model.mlmodelc
    
speaker_identification:
  device: mps  # or cuda, cpu
  prefer_mps_on_mac: true

concurrency:
  transcription_workers: 2  # Limited by model memory usage
```

**Performance Notes:**
- Core ML (Apple Silicon): ~5-10x faster than CPU, uses Neural Engine
- CUDA (NVIDIA): ~10-20x faster than CPU depending on GPU
- Metal (Apple Silicon): ~3-5x faster than CPU
- Each worker loads full models into memory (~4-6GB per worker)

**Hardware Recommendations:**
- Apple Silicon (16GB+): 2 workers with Core ML
- Apple Silicon (32GB+): 3 workers with Core ML
- NVIDIA GPU (8GB+): 2 workers with CUDA
- NVIDIA GPU (16GB+): 3-4 workers with CUDA
- CPU only: 1 worker (conserve memory)

### Stage 4: Speaker Identification
**GPU Usage:** Moderate (embedding model inference)
**Acceleration:**
- MPS device (Apple Silicon) - Configured via `device: mps`
- CUDA device (NVIDIA) - Configured via `device: cuda`
- CPU fallback

**Configuration:**
```yaml
speaker_identification:
  device: mps  # or cuda, cpu, GPU (auto-detect)
  prefer_mps_on_mac: true
  embedding_model_id: pyannote/wespeaker-voxceleb-resnet34-LM
```

**Performance Notes:**
- MPS (Apple Silicon): ~3-5x faster than CPU
- CUDA (NVIDIA): ~5-10x faster than CPU
- Serial execution (no parallelization to maintain speaker database consistency)

### Stage 5: Video Composition/Merging
**GPU Usage:** Heavy (video encoding)
**Acceleration:**
- **VideoToolbox (macOS):** Hardware H.264/H.265 encoding via Media Engine
- **NVENC (NVIDIA):** Hardware encoding on GPU
- **QSV (Intel):** Quick Sync Video hardware encoding
- **FFmpeg filter_complex:** GPU-accelerated filters (when available)

**Configuration:**
```yaml
multi_camera_composition:
  encoding:
    use_hw_encode: true  # Enable hardware encoding
    hw_codec: h264_videotoolbox  # macOS: h264_videotoolbox, h265_videotoolbox
                                  # NVIDIA: h264_nvenc, hevc_nvenc
                                  # Intel: h264_qsv, hevc_qsv
    bitrate: 8000k  # Higher bitrate = better quality
    
    # Software fallback settings (if hardware unavailable)
    x264_preset: faster  # faster, fast, medium, slow (slower = better quality)
    x264_crf: 20  # Lower = better quality (18-23 recommended)

concurrency:
  merge_workers: 4  # Parallel video composition
```

**Performance Notes:**
- VideoToolbox (Apple Silicon): ~5-10x faster than libx264, excellent quality
- NVENC (NVIDIA): ~5-15x faster than libx264, very good quality
- QSV (Intel): ~3-8x faster than libx264, good quality
- Multiple workers can encode in parallel (limited by GPU/memory)

**Hardware Recommendations:**
- Apple Silicon: 4-6 workers (Media Engine handles parallel encoding well)
- NVIDIA GPU: 2-3 workers (NVENC has session limits)
- Intel QSV: 2-3 workers
- CPU only: 1-2 workers

### Stage 6: Final Transcription
**GPU Usage:** Same as Stage 3
**Acceleration:** Whisper + Pyannote with GPU acceleration

**Configuration:** Same as Stage 3

### Audio Quality Analysis
**GPU Usage:** Minimal (FFmpeg based)
**Acceleration:**
- Parallel analysis when using modular composition
- FFmpeg astats filter (CPU-efficient)
- Caching to avoid redundant analysis

**Configuration:**
```yaml
multi_camera_composition:
  use_modular_composition: true  # Enable caching
  audio_quality_weights:
    rms: 0.4
    peak: 0.2
    noise: 0.2
    clipping: 0.3
```

### Audio/Video Alignment
**GPU Usage:** None (NumPy CPU-based)
**Acceleration:**
- Optimized NumPy operations
- Audio caching to avoid repeated decoding
- Configurable window sizes for speed/accuracy tradeoff

**Configuration:**
```yaml
multi_camera_composition:
  audio_alignment:
    enabled: true
    analysis_window_seconds: 12.0  # Smaller = faster (less accurate)
    hop_seconds: 6.0  # Larger = fewer windows (faster)
    sample_rate: 16000  # Lower = faster (adequate for alignment)
```

**Performance Tuning:**
- Fast alignment: `window=8.0, hop=8.0, rate=8000` (~50% faster)
- Balanced: `window=12.0, hop=6.0, rate=16000` (default)
- Accurate: `window=16.0, hop=4.0, rate=48000` (~2x slower)

### People Detection (speech_people strategy)
**GPU Usage:** Moderate (object detection model)
**Acceleration:**
- **Vision Framework (macOS):** Apple Neural Engine, fastest option
- **Hugging Face + MPS (Apple Silicon):** GPU acceleration
- **Hugging Face + CUDA (NVIDIA):** GPU acceleration
- CPU fallback

**Configuration:**
```yaml
multi_camera_composition:
  people_detection:
    enabled: true
    backend: vision  # vision (macOS), huggingface, auto
    
    # HuggingFace backend options (if not using Vision):
    model_name: hustvl/yolos-tiny  # Lighter model (faster)
    # model_name: facebook/detr-resnet-50  # Heavier model (more accurate)
    resize_width: 480  # Smaller = faster
    sample_frames: 12  # Fewer = faster
```

**Performance Notes:**
- Vision (Apple Silicon): ~10-20ms per frame (fastest)
- YOLOS-tiny + MPS: ~50-100ms per frame
- DETR-ResNet-50 + MPS: ~200-400ms per frame
- CUDA performance similar to MPS, depends on GPU

**Hardware Recommendations:**
- macOS: Use Vision backend (fastest, no model download)
- NVIDIA GPU: Hugging Face + CUDA with YOLOS-tiny
- Apple Silicon (no Vision): Hugging Face + MPS with YOLOS-tiny
- CPU only: Disable people detection or use very small models

## Hardware-Specific Optimization Guides

### Apple Silicon (M1/M2/M3/M4)

**Optimal Configuration:**
```yaml
transcription:
  whisper:
    device: coreml
    ggml_model_path: /path/to/coreml-encoder-model.mlmodelc

speaker_identification:
  device: mps
  prefer_mps_on_mac: true

multi_camera_composition:
  encoding:
    use_hw_encode: true
    hw_codec: h264_videotoolbox
    bitrate: 8000k
  people_detection:
    enabled: true
    backend: vision
    
concurrency:
  validation_workers: 6  # Fast SSD
  transcription_workers: 2  # 16GB RAM
  merge_workers: 4  # Media Engine parallelism
```

**Expected Performance:**
- Full pipeline on 10-minute event: ~2-4 minutes (16GB M1)
- Core ML transcription: ~2-3x realtime
- VideoToolbox encoding: ~5-10x realtime
- Vision people detection: ~50 frames/second

### NVIDIA GPU (RTX 3060+)

**Optimal Configuration:**
```yaml
transcription:
  whisper:
    device: cuda
    # Use standard GGML models for CUDA

speaker_identification:
  device: cuda

multi_camera_composition:
  encoding:
    use_hw_encode: true
    hw_codec: h264_nvenc
    bitrate: 8000k
  people_detection:
    enabled: true
    backend: huggingface
    model_name: hustvl/yolos-tiny
    
concurrency:
  validation_workers: 4
  transcription_workers: 2  # GPU memory dependent
  merge_workers: 2  # NVENC session limit
```

**Expected Performance:**
- Full pipeline on 10-minute event: ~1-3 minutes (RTX 3080)
- CUDA transcription: ~3-5x realtime
- NVENC encoding: ~10-15x realtime

### Intel/AMD CPU Only

**Optimal Configuration:**
```yaml
transcription:
  whisper:
    device: cpu
    # Consider smaller model for speed

speaker_identification:
  device: cpu

multi_camera_composition:
  encoding:
    use_hw_encode: false
    x264_preset: faster  # Balance speed/quality
    x264_crf: 22
  people_detection:
    enabled: false  # Too slow on CPU
    
concurrency:
  validation_workers: 3
  transcription_workers: 1  # Memory constrained
  merge_workers: 2
```

**Expected Performance:**
- Full pipeline on 10-minute event: ~10-30 minutes (varies widely)
- CPU transcription: ~0.2-0.5x realtime
- libx264 encoding: ~1-3x realtime

## Performance Monitoring

### Check GPU Utilization

**macOS (Apple Silicon):**
```bash
# Terminal 1: Monitor GPU usage
sudo powermetrics --samplers gpu_power -i 1000

# Terminal 2: Run pipeline
python main.py
```

**Linux/Windows (NVIDIA):**
```bash
# Terminal 1: Monitor GPU
watch -n 1 nvidia-smi

# Terminal 2: Run pipeline
python main.py
```

### Check Pipeline Stage Performance

Pipeline logs (in `logs/` directory) include timing for each stage:
```
INFO: Stage 3 completed in 02:15 (Transcription & Diarization)
INFO: Stage 5 completed in 01:30 (Video Composition)
```

### Profiling Individual Components

Enable debug logging for detailed timing:
```yaml
logging:
  log_level: DEBUG
```

Then check logs for per-clip timing:
```
DEBUG: Transcribed clip in 12.3s (2.1x realtime)
DEBUG: Encoded video in 8.5s (7.2x realtime)
```

## Troubleshooting

### Issue: Hardware encoder not working

**Symptoms:** Falls back to software encoding (slow)

**Solutions:**
1. Check hardware support:
   ```bash
   ffmpeg -encoders | grep h264
   # Look for h264_videotoolbox, h264_nvenc, h264_qsv
   ```

2. Verify driver installation:
   - macOS: VideoToolbox is always available
   - NVIDIA: Install latest GPU drivers
   - Intel: Install media SDK

3. Check configuration:
   ```yaml
   encoding:
     use_hw_encode: true
     hw_codec: h264_videotoolbox  # Must match hardware
   ```

### Issue: CUDA out of memory

**Symptoms:** "CUDA out of memory" errors during transcription

**Solutions:**
1. Reduce worker count:
   ```yaml
   concurrency:
     transcription_workers: 1  # Was 2
   ```

2. Use smaller models:
   ```yaml
   transcription:
     whisper:
       model_name: base  # Was medium or large
   ```

3. Monitor VRAM:
   ```bash
   nvidia-smi
   # Check memory usage before/during pipeline
   ```

### Issue: Core ML model not found

**Symptoms:** Core ML errors, falls back to CPU

**Solutions:**
1. Verify model path:
   ```yaml
   transcription:
     whisper:
       ggml_model_path: /full/path/to/coreml-encoder-model.mlmodelc
   ```

2. Check model compilation:
   ```bash
   ls -la /path/to/model.mlmodelc
   # Should be a directory with .mlmodel files
   ```

3. Recompile if needed:
   ```bash
   cd whisper.cpp/models
   ./generate-coreml-model.sh base.en
   ```

### Issue: Slow alignment

**Symptoms:** Stage 5 spends long time on alignment

**Solutions:**
1. Reduce window size:
   ```yaml
   audio_alignment:
     analysis_window_seconds: 8.0  # Was 12.0
     hop_seconds: 8.0  # Was 6.0
   ```

2. Disable drift estimation:
   ```yaml
   audio_alignment:
     estimate_drift: false
   ```

3. Disable alignment completely:
   ```yaml
   audio_alignment:
     enabled: false
   ```

## Best Practices

1. **Start with default settings** - The provided configuration is tuned for common hardware
2. **Monitor first run** - Watch GPU/CPU/memory usage to identify bottlenecks
3. **Tune one variable at a time** - Change one setting, measure impact, repeat
4. **Balance quality and speed** - Higher quality = slower processing
5. **Cache everything** - Use repair cache, diarization cache, quality cache for faster re-runs
6. **Scale workers conservatively** - More workers ≠ faster if memory/GPU bound

## Performance Comparison

Approximate processing times for a 30-minute multi-camera event (3 cameras, 10 clips each):

| Hardware | Configuration | Total Time | Transcription | Composition |
|----------|--------------|------------|---------------|-------------|
| M1 Pro 16GB | Core ML + VideoToolbox | 6 min | 3 min | 2 min |
| M3 Max 64GB | Core ML + VideoToolbox | 4 min | 2 min | 1 min |
| RTX 3080 | CUDA + NVENC | 5 min | 2.5 min | 1.5 min |
| RTX 4090 | CUDA + NVENC | 3 min | 1.5 min | 1 min |
| i9-13900K (CPU only) | No GPU | 35 min | 25 min | 8 min |

*Times are approximate and vary based on video resolution, complexity, and configuration*

## Future Optimization Opportunities

1. **Batch people detection** - Process multiple frames in parallel
2. **GPU-accelerated alignment** - Port NumPy operations to CuPy/Metal Performance Shaders
3. **Async encoding** - Start encoding segments while still analyzing later ones
4. **Model quantization** - Use INT8 models for faster inference
5. **ROCm support** - Add AMD GPU acceleration for Linux systems
