# Orchestration Architecture

This document describes the architecture and flow of the Blink video processing pipeline, with emphasis on modularity, clarity, and hardware acceleration.

## Table of Contents
1. [High-Level Overview](#high-level-overview)
2. [Pipeline Stages](#pipeline-stages)
3. [Module Boundaries](#module-boundaries)
4. [Data Flow](#data-flow)
5. [Concurrency Model](#concurrency-model)
6. [Hardware Acceleration Integration](#hardware-acceleration-integration)
7. [Extension Points](#extension-points)

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BLINK VIDEO PIPELINE                         │
│                         (orchestrator.py)                           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: File Discovery                                            │
│  ├─ Scan input directory recursively                                │
│  ├─ Parse filenames (timestamp, camera name)                        │
│  └─ Parse date folders                                              │
│  Module: discovery.py                                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Video Grouping                                            │
│  ├─ Sort clips chronologically                                      │
│  ├─ Group by time-based overlap detection                           │
│  └─ Create multi-camera event groups                                │
│  Module: grouping.py                                                │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 0: Video Validation & Repair (Preprocessing)                 │
│  ├─ Probe all videos for A/V sync issues                            │
│  ├─ Repair damaged clips (fill missing frames)                      │
│  ├─ Cache repaired videos for reuse                                 │
│  └─ Update clip paths to repaired versions                          │
│  Module: media_validation.py                                        │
│  Acceleration: Parallel workers (I/O bound)                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: Transcription & Diarization (Parallel per Group)          │
│  ├─ Extract audio from video clips                                  │
│  ├─ Whisper transcription (GPU-accelerated)                         │
│  ├─ Pyannote speaker diarization (GPU-accelerated)                  │
│  ├─ Merge segments by timeline offsets                              │
│  └─ Cache diarization results                                       │
│  Module: transcription.py                                           │
│  Workers: ProcessPoolExecutor (configurable)                        │
│  Acceleration: Core ML, Metal, CUDA, MPS                            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 4: Speaker Identification (Serial)                           │
│  ├─ Extract audio windows for each speech segment                   │
│  ├─ Generate embeddings (GPU-accelerated)                           │
│  ├─ Match to existing speakers via cosine similarity                │
│  ├─ Register new speakers with unique IDs                           │
│  ├─ Save voice samples for new speakers                             │
│  └─ Substitute speaker names in transcripts                         │
│  Module: identify_speaker.py                                        │
│  Acceleration: MPS, CUDA for embedding model                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5: Video Composition/Merging (Parallel per Group)            │
│  ├─ Detect multi-camera vs single-camera groups                     │
│  ├─ [Multi-camera] Analyze audio/video quality                      │
│  ├─ [Multi-camera] Align clips via GCC-PHAT                         │
│  ├─ [Multi-camera] Detect people in frames (optional)               │
│  ├─ [Multi-camera] Generate timeline (camera switching)             │
│  ├─ [Multi-camera] Apply camera control rules                       │
│  ├─ [Multi-camera] Render composite video                           │
│  └─ [Single-camera] Simple sequential merge                         │
│  Module: multi_camera_composer.py, video.py                         │
│  Workers: ProcessPoolExecutor (configurable)                        │
│  Acceleration: VideoToolbox, NVENC, QSV hardware encoding           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 6: Final Transcription of Merged Videos                      │
│  ├─ Run Whisper + Diarization on composed videos                    │
│  ├─ Match speakers to profiles                                      │
│  ├─ Format as human-readable transcript                             │
│  └─ Include wall-clock timestamps                                   │
│  Module: transcription.py                                           │
│  Acceleration: Same as Stage 3                                      │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 7: Speaker Profiles Export                                   │
│  ├─ Gather all speaker voice samples                                │
│  ├─ Load existing names from config/profiles                        │
│  ├─ Generate editable profiles.json                                 │
│  └─ Save to output/speakers/profiles.json                           │
│  Module: orchestrator.py (_write_speaker_profiles)                  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                            ┌─────────────┐
                            │   COMPLETE  │
                            └─────────────┘
```

## Pipeline Stages

### Stage 1: File Discovery
**Purpose:** Find and parse video files in input directory

**Input:**
- Input directory path
- Filename pattern regex

**Output:**
- List of discovered files with metadata:
  - `full_path`: Absolute path to video file
  - `datetime`: Parsed datetime from filename and folder
  - `camera`: Camera identifier from filename

**Module:** `blink_pipeline/discovery.py`

**Key Functions:**
- `discover_files()` - Main entry point
- `parse_filename()` - Extract timestamp and camera from filename
- `parse_date_folder()` - Extract date from directory name

**Characteristics:**
- Single-threaded (fast, I/O light)
- No external dependencies
- Idempotent (can run multiple times safely)

### Stage 2: Video Grouping
**Purpose:** Group clips into multi-camera events by time overlap

**Input:**
- List of discovered files with metadata

**Output:**
- List of groups, each group containing clips that overlap in time
- Groups may contain single or multiple cameras

**Module:** `blink_pipeline/grouping.py`

**Algorithm:**
1. Sort all clips chronologically
2. For each clip, check if it starts within `max_time_diff_seconds` of the most recent clip in current group
3. If yes, add to current group
4. If no, start a new group

**Configuration:**
```yaml
grouping:
  max_time_diff_seconds: 300  # 5 minutes
```

**Characteristics:**
- Single-threaded (fast, in-memory)
- Deterministic output
- Time-based overlap enables true multi-camera event detection

### Stage 0: Video Validation & Repair
**Purpose:** Ensure all videos are valid and repair damaged ones

**Input:**
- List of all unique video paths from groups

**Output:**
- Path mapping: `{original_path: repaired_or_original_path}`
- Updated groups with paths pointing to repaired videos

**Module:** `blink_pipeline/media_validation.py`

**Process:**
1. Probe each video for A/V sync issues
2. If sync difference > 100ms or `always_repair=true`, repair:
   - Fill missing video frames (last frame duplication)
   - Pad audio with silence if shorter than video
   - Re-encode with consistent settings
3. Cache repaired videos to `repair_cache_dir`
4. Return mapping of original → repaired paths

**Configuration:**
```yaml
transcription:
  always_repair: false  # Only repair when needed
  repair_cache_dir: output/repaired_cache
  repair_strategy: fill  # or remove_blank
```

**Parallelization:**
- ProcessPoolExecutor with `validation_workers` workers
- Each worker processes videos independently
- Progress reported via shared dictionary

**Hardware Acceleration:**
- FFmpeg hardware decoding (automatic when available)
- I/O bound, benefits from fast SSD and parallel workers

### Stage 3: Transcription & Diarization
**Purpose:** Convert speech to text and identify speakers

**Input:**
- Group of video paths
- Configuration for Whisper and pyannote

**Output:**
- Diarization result dictionary:
  - `segments`: List of {speaker, start, end, text}
  - `timeline`: List of {path, offset, duration} for each clip

**Module:** `blink_pipeline/transcription.py`

**Process:**
1. Check cache for existing diarization
2. Extract audio from each video clip
3. Run Whisper transcription on each clip
4. Run pyannote diarization on concatenated audio
5. Merge segments using timeline offsets
6. Cache result for future runs

**Worker Function:** `_transcribe_group_job()` in `orchestrator.py`

**Parallelization:**
- ProcessPoolExecutor with `transcription_workers` workers
- Each worker processes one group independently
- Each worker loads its own model instances (memory intensive)

**Configuration:**
```yaml
transcription:
  whisper:
    device: coreml  # or metal, cuda, cpu
    ggml_model_path: /path/to/model
  diarization:
    model_id: pyannote/speaker-diarization-3.1

concurrency:
  transcription_workers: 2  # Limit due to memory
```

**Hardware Acceleration:**
- Whisper: Core ML (Apple Neural Engine), Metal, CUDA
- Pyannote: MPS (Apple Silicon), CUDA
- See [GPU_ACCELERATION_GUIDE.md](GPU_ACCELERATION_GUIDE.md)

**Caching:**
- Results cached in `output/.diarization_cache/`
- Cache key: group name
- Invalidate by deleting cache directory

### Stage 4: Speaker Identification
**Purpose:** Match speakers across events and assign persistent IDs

**Input:**
- Diarization result from Stage 3
- Existing speaker database (if any)

**Output:**
- Updated speaker database
- Transcripts with speaker IDs/names
- Voice samples for new speakers

**Module:** `blink_pipeline/identify_speaker.py`

**Process:**
1. For each diarized speech segment:
   - Extract audio window (with context padding)
   - Generate embedding vector via pyannote model
   - Compare to existing speakers via cosine similarity
   - If similarity > threshold, match to existing speaker
   - If similarity < threshold, register as new speaker
2. Save voice sample for new speakers
3. Substitute speaker IDs/names in transcript

**Characteristics:**
- **Serial execution only** (no parallelization)
- Reason: Maintains consistent speaker database across events
- Updates shared state (speaker_profiles.json, voice samples)

**Configuration:**
```yaml
speaker_identification:
  device: mps  # or cuda, cpu
  similarity_threshold: 0.68
  embedding_model_id: pyannote/wespeaker-voxceleb-resnet34-LM
```

**Hardware Acceleration:**
- MPS (Apple Silicon) or CUDA for embedding generation
- ~3-5x faster than CPU

### Stage 5: Video Composition/Merging
**Purpose:** Combine multi-camera footage into intelligent composite

**Input:**
- List of video clips for a group
- Diarization result (optional, for speech-aware switching)
- Configuration for composition

**Output:**
- Single merged/composed video file

**Module:** `blink_pipeline/multi_camera_composer.py`, `blink_pipeline/video.py`

**Process (Multi-Camera):**
1. Analyze audio quality for each clip
2. Analyze video quality (optional)
3. Detect people in frames (optional, for `speech_people` strategy)
4. Align clips via GCC-PHAT cross-correlation
5. Generate timeline based on switching strategy
6. Apply camera control rules
7. Render composite video via FFmpeg

**Process (Single-Camera):**
1. Simple sequential merge with crossfades

**Worker Function:** `_merge_group_job()` in `orchestrator.py`

**Parallelization:**
- ProcessPoolExecutor with `merge_workers` workers
- Each worker composes one group independently
- FFmpeg invocations per worker

**Configuration:**
```yaml
multi_camera_composition:
  switching_strategy: speech_people  # or time_based, round_robin, audio_quality
  audio_source: best_quality
  enable_composition: true
  
  encoding:
    use_hw_encode: true
    hw_codec: h264_videotoolbox  # or h264_nvenc, h264_qsv
    
  camera_control:
    priority_cameras: []
    exclude_cameras: []
    forced_segments: []
    
concurrency:
  merge_workers: 4
```

**Hardware Acceleration:**
- VideoToolbox (macOS) - Hardware H.264/H.265 encoding
- NVENC (NVIDIA) - GPU-based encoding
- QSV (Intel) - Quick Sync Video hardware encoding
- FFmpeg filter_complex - GPU filters where available
- See [GPU_ACCELERATION_GUIDE.md](GPU_ACCELERATION_GUIDE.md)

**Camera Control:**
- Priority system - prefer specific cameras
- Exclusion - hide cameras from video (audio only)
- Forced segments - override at specific times
- See [ALIGNMENT_ALGORITHM.md](../ALIGNMENT_ALGORITHM.md#camera-control-system)

### Stage 6: Final Transcription
**Purpose:** Generate final human-readable transcripts from merged videos

**Input:**
- Merged video files from Stage 5

**Output:**
- Formatted transcript files in `output/transcripts/final/`

**Module:** `blink_pipeline/transcription.py`

**Process:**
1. Run Whisper + Diarization on merged video
2. Match speakers to profiles (load names from profiles.json)
3. Format as script-style transcript with timestamps
4. Include wall-clock time if available

**Characteristics:**
- Same as Stage 3 (uses same modules)
- One transcription per merged video
- Includes speaker names from profiles

### Stage 7: Speaker Profiles Export
**Purpose:** Create editable speaker profiles for user review

**Input:**
- Voice samples from `output/speakers/`
- Existing names from config.yaml and profiles.json

**Output:**
- `output/speakers/profiles.json` with all speakers

**Module:** `orchestrator.py` (`_write_speaker_profiles()`)

**Format:**
```json
{
  "version": 1,
  "generated_at": "2025-10-23T21:00:00",
  "speakers": {
    "spk_001": {
      "name": "Alice",
      "samples": ["spk_001.wav"],
      "notes": "Edit 'name' with a friendly label"
    }
  }
}
```

**User Workflow:**
1. Pipeline generates profiles.json
2. User edits "name" fields manually
3. Re-run pipeline or Stage 6 to apply names

## Module Boundaries

### Core Modules

```
blink_pipeline/
├── orchestrator.py          # Main pipeline coordinator
├── stages.py                # Stage key definitions
├── discovery.py             # File discovery logic
├── grouping.py              # Time-based grouping
├── media_validation.py      # Video repair and validation
├── transcription.py         # Whisper + pyannote integration
├── identify_speaker.py      # Speaker matching and tracking
├── multi_camera_composer.py # Multi-camera composition
├── video.py                 # Simple video merging
├── av_alignment.py          # Audio alignment (GCC-PHAT)
├── people_detection.py      # People counting (Vision/HF)
├── audio_cache.py           # Audio segment caching
├── media_utils.py           # FFmpeg utilities
├── logging_config.py        # Logging setup
├── pipeline_dashboard.py    # Progress display
└── progress.py              # Progress tracking
```

### Modular Composition (Feature Flag)

```
blink_pipeline/composition/
├── __init__.py
├── config.py                # Configuration models
├── models.py                # Data models (CameraClip, etc.)
├── quality.py               # Audio quality analysis
├── alignment.py             # Alignment engine with caching
├── timeline.py              # Timeline generation strategies
├── audio.py                 # Audio processing
├── rendering.py             # Video rendering (single/multi pass)
├── overlay.py               # Timestamp overlays
└── composer.py              # Main modular composer
```

**Feature Flag:** `use_modular_composition: true`

When enabled, uses new modular architecture with:
- Cached quality analysis
- Cached alignment results
- Pluggable timeline strategies
- Cleaner separation of concerns

### Interface Contracts

**discovery.py → grouping.py:**
```python
# Output: List[Dict[str, Any]] with keys:
# - full_path: str
# - datetime: datetime.datetime
# - camera: str
```

**grouping.py → orchestrator.py:**
```python
# Output: List[List[Dict[str, Any]]]
# Each inner list is a group of clips that overlap in time
```

**transcription.py → orchestrator.py:**
```python
# Output: Dict[str, Any]
# {
#   'segments': List[{speaker, start, end, text}],
#   'timeline': List[{path, offset, duration}]
# }
```

**multi_camera_composer.py → orchestrator.py:**
```python
# Input: video_clips (List[Dict]), output_path (str), speech_segments, config
# Output: bool (success)
```

## Data Flow

```
Input Videos → Discovery → Grouping → Validation
                                          ↓
                                   Repaired Videos
                                          ↓
                                   Transcription ←─┐
                                          ↓         │
                                    Diarization    │
                                          ↓         │
                               Speaker Identification
                                          ↓
                                  Composition ←─────┤
                                      ↓             │
                                 Merged Video       │
                                      ↓             │
                            Final Transcription ────┘
                                      ↓
                               Speaker Profiles
```

## Concurrency Model

### Parallel Stages (ProcessPoolExecutor)

**Stage 0: Validation**
- Worker function: `preprocess_videos()` internal workers
- Concurrency: `concurrency.validation_workers` (default: 3-6)
- Shared state: Path mapping dictionary (return value)
- Progress: Via callback function

**Stage 3: Transcription**
- Worker function: `_transcribe_group_job()`
- Concurrency: `concurrency.transcription_workers` (default: 2)
- Shared state: Progress dictionary (multiprocessing.Manager)
- Isolated: Each worker has own model instances

**Stage 5: Composition**
- Worker function: `_merge_group_job()`
- Concurrency: `concurrency.merge_workers` (default: 3-4)
- Shared state: Progress dictionary (multiprocessing.Manager)
- Isolated: Each worker invokes separate FFmpeg processes

### Serial Stages

**Stage 1: Discovery** - Fast, I/O light
**Stage 2: Grouping** - Fast, in-memory
**Stage 4: Speaker ID** - Must maintain shared speaker database
**Stage 6: Final Transcription** - Can be parallelized (future work)
**Stage 7: Profiles** - Fast, file-based

### Progress Tracking

All stages report progress via `PipelineDashboard`:

```python
dashboard.start_stage(StageKey.VALIDATION, total_items)
dashboard.update_stage(StageKey.VALIDATION, completed, "Processing...")
dashboard.complete_stage(StageKey.VALIDATION, "Done!")
```

Workers update progress via shared dictionary:
```python
progress_dict[task_id] = {"progress": completed, "total": total, "visible": True}
```

Dashboard polls progress dict and updates display.

## Hardware Acceleration Integration

See [GPU_ACCELERATION_GUIDE.md](GPU_ACCELERATION_GUIDE.md) for comprehensive details.

### Summary by Stage

| Stage | Acceleration | Hardware | Speedup |
|-------|-------------|----------|---------|
| 0: Validation | FFmpeg decode | Auto | 1.3x |
| 3: Transcription | Whisper | Core ML, CUDA | 5-10x |
| 3: Diarization | Pyannote | MPS, CUDA | 3-5x |
| 4: Speaker ID | Embeddings | MPS, CUDA | 3-5x |
| 5: Composition | Encoding | VideoToolbox, NVENC | 5-15x |
| 5: People Detection | Vision/DETR | Neural Engine, MPS | 10-20x |
| 6: Final Trans. | Same as Stage 3 | - | 5-10x |

### Configuration Pattern

Each accelerated component follows this pattern:

```yaml
module:
  device: auto  # auto, cuda, mps, cpu, coreml
  # or specific:
  # device: coreml (Whisper)
  # device: mps (Speaker ID)
  
  # Hardware encoding:
  encoding:
    use_hw_encode: true
    hw_codec: h264_videotoolbox
```

### Fallback Strategy

All GPU-accelerated components have CPU fallbacks:

1. Try hardware acceleration
2. On error, log warning and fall back to CPU
3. Continue processing (slower but functional)

Example:
```
WARNING: Core ML model not found, falling back to CPU
INFO: Using CPU for Whisper transcription (slower)
```

## Extension Points

### Adding a New Pipeline Stage

1. Create module in `blink_pipeline/`
2. Add stage key to `stages.py`:
   ```python
   class StageKey(str, Enum):
       NEW_STAGE = "new_stage"
   ```
3. Add stage definition to `pipeline_dashboard.py`:
   ```python
   STAGE_DEFINITIONS = {
       StageKey.NEW_STAGE: {...}
   }
   ```
4. Add stage execution to `orchestrator.py`:
   ```python
   dashboard.start_stage(StageKey.NEW_STAGE, total)
   # ... process ...
   dashboard.complete_stage(StageKey.NEW_STAGE, "Done!")
   ```

### Adding a New Camera Switching Strategy

1. Add strategy to `multi_camera_composer.py`:
   ```python
   def _timeline_new_strategy(self, camera_clips):
       # ... generate timeline ...
       return segments
   ```
2. Update `_generate_composition_timeline()`:
   ```python
   elif self.switching_strategy == 'new_strategy':
       return self._timeline_new_strategy(camera_clips)
   ```
3. Document in config.yaml:
   ```yaml
   multi_camera_composition:
     switching_strategy: new_strategy  # Description
   ```

### Adding a New Quality Analyzer

If using modular composition:

1. Create analyzer in `blink_pipeline/composition/quality.py`:
   ```python
   class NewQualityAnalyzer(AudioQualityAnalyzer):
       def analyze(self, video_path, has_audio):
           # ... return metrics ...
   ```
2. Use in composer initialization:
   ```python
   self._quality_analyzer = NewQualityAnalyzer()
   ```

### Adding a New People Detection Backend

1. Create detector in `blink_pipeline/people_detection.py`:
   ```python
   class NewPeopleDetector:
       def count_people(self, image):
           # ... return count ...
   ```
2. Update backend selection:
   ```python
   if backend == 'new_backend':
       self._detector = NewPeopleDetector()
   ```
3. Document in config.yaml:
   ```yaml
   people_detection:
     backend: new_backend  # Description
   ```

## Troubleshooting

### Pipeline Stalls

**Symptom:** Pipeline stops progressing

**Debug:**
1. Check logs: `tail -f logs/pipeline_session.log`
2. Check worker processes: `ps aux | grep python`
3. Check GPU usage: `nvidia-smi` or `sudo powermetrics --samplers gpu_power`

**Common Causes:**
- Worker crash (check logs for exceptions)
- GPU out of memory (reduce workers)
- Deadlock in progress tracking (restart pipeline)

### Inconsistent Results

**Symptom:** Running pipeline multiple times gives different outputs

**Debug:**
1. Check cache directories: `.diarization_cache/`, `repaired_cache/`
2. Delete caches to force re-processing
3. Check for race conditions in parallel stages

**Common Causes:**
- Cached results from previous run
- Non-deterministic people detection (sampling)
- Parallel worker race conditions

### Performance Issues

**Symptom:** Pipeline is slower than expected

**Debug:**
1. Enable debug logging: `log_level: DEBUG`
2. Check stage timings in logs
3. Check hardware utilization

**Common Causes:**
- CPU-only mode (no GPU acceleration)
- Too many workers (memory thrashing)
- Slow disk I/O (mechanical HDD)

**Solutions:**
- See [GPU_ACCELERATION_GUIDE.md](GPU_ACCELERATION_GUIDE.md)
- Tune worker counts in config.yaml
- Use SSD for input/output directories

## Future Architecture Improvements

1. **Event-driven architecture:** Replace polling with async events
2. **Streaming pipeline:** Process clips as they arrive (live mode)
3. **Distributed execution:** Run workers on multiple machines
4. **Web UI:** Real-time monitoring and control
5. **Plugin system:** Load custom stages/strategies at runtime
6. **Checkpoint/resume:** Save pipeline state, resume after interruption
7. **Quality metrics:** Track and report quality scores over time
8. **A/B testing:** Compare different strategies/settings side-by-side
