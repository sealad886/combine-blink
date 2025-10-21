# Configuration Reference (`config.yaml`)

The pipeline reads `config.yaml` at startup (`load_config()` in
`src/orchestrator.py`). This document explains every top-level section and the
most important keys.

```yaml
paths:
  input_dir: 25-10-15
  output_dir: output
  videos_dir: merged_videos
  transcripts_dir: transcripts
  speakers_dir: speaker_voice_samples
```

| Key | Description |
|-----|-------------|
| `input_dir` | Root directory for raw Blink clips (subdirectories usually grouped by date). |
| `output_dir` | Root directory for generated artefacts (videos, transcripts, speakers, cache). |
| `videos_dir` | Subdirectory under `output_dir` for merged/composited videos. |
| `transcripts_dir` | Subdirectory holding `{group_name}_transcript.txt`. |
| `speakers_dir` | Subdirectory storing per-speaker WAV samples. |

---

```yaml
discovery:
  filename_pattern: (\d{2}-\d{2}-\d{2})_([a-zA-Z0-9]+)G.+\.mp4
  date_folder_patterns:
    - '%y-%m-%d'
    - '%y%m%d'
    - '%y_%m_%d'
    - '%m-%d-%y'
    - '%d-%m-%y'
```

- `filename_pattern`: regex with two capture groups (time `HH-MM-SS`, camera label).
- `date_folder_patterns`: ordered list of `strptime` formats used to parse parent
  directory names. You can mix two-digit (`%y`) and four-digit (`%Y`) year formats;
  any mismatch falls back to today’s date with a warning.

**Filename & directory expectations**

```
25-10-15/
  08-37-43_CornerG8T1K0013255014P_081.mp4
```

| Component | Example | Notes |
|-----------|---------|-------|
| `HH-MM-SS` | `08-37-43` | 24‑hour time extracted by the regex. |
| `CameraName` | `Corner` | Parsed up to the `G` prefix. |
| `G…` suffix | `G8T1K0013255014P_081` | Not parsed further but retained in filenames. |
| Parent folder | `25-10-15` | Parsed via `date_folder_patterns`; supports `%y` or `%Y` years. |

---

```yaml
grouping:
  max_time_diff_seconds: 300
```

- Maximum time delta between successive clips within a group. Higher values
  produce longer multi-camera events; lower values split events more eagerly.

---

```yaml
multi_camera_composition:
  enable_composition: true
  switching_strategy: audio_quality   # time_based | round_robin | audio_quality
  switching_interval: 5.0
  transition_style: crossfade         # cut | crossfade
  transition_duration: 0.28
  audio_source: best_quality          # best_quality | first | longest
  audio_crossfade_seconds: 0.06       # crossfade between audio segments
  audio_alignment:
    enabled: true
    max_shift_seconds: 1.0
    analysis_window_seconds: 12.0
    hop_seconds: 6.0
    sample_rate: 16000
    bandpass: true
    highpass_hz: 300
    lowpass_hz: 3000
    estimate_drift: true
  timestamp_overlay:
    enabled: true
    font: Arial
    font_size: 24
    margin_v: 20
    margin_r: 20
    dst_offset_hours: 1
```

- `switching_strategy`: how to choose which camera is visible (`audio_quality`
  prefers the best audio score).
- `transition_style` + `transition_duration`: control video transitions.
- `audio_alignment`: per-camera fine alignment using multi-window GCC‑PHAT with optional drift.
- `audio_crossfade_seconds`: triangular crossfade between consecutive audio segments.
- `timestamp_overlay`: burn-in overlay with DST correction (requires system fonts).

---

```yaml
video_processing:
  crossfade_duration: 0.5
```

- Crossfade length in seconds for sequential merges (single camera or fallback).

---

```yaml
transcription:
  always_repair: false
  repair_cache_dir: output/repaired_cache
  repair_strategy: fill
  whisper:
    language: en
    ggml_model_path: /path/to/model
    whisper_cpp_binary: /path/to/whisper-cli
    device: coreml         # auto | cpu | cuda | metal | coreml
    beam_size: 5
    temperature: 0.0
  diarization:
    model_id: pyannote/speaker-diarization-3.1
    auth_token_env:
      - HF_TOKEN
      - HUGGINGFACE_TOKEN
    min_overlap_ratio: 0.6
```

- `always_repair`: force repairs even when no sync issues detected.
- `repair_cache_dir`: Stage 0 cache location.
- `repair_strategy`: `fill` or `remove_blank` (ffmpeg filter path).
- `whisper`:
  - Set `model_name` (implicit default `small`) when using openai-whisper.
  - Set `ggml_model_path` for whisper.cpp (supports `.bin`, `.mlpackage`, or `.mlmodelc`).
  - `device` `coreml` leverages Apple Neural Engine when using the Core ML path.
  - `whisper_cpp_binary` is optional if the CLI is on `PATH`.
- `diarization`:
  - `auth_token_env` lists env vars checked for Hugging Face tokens.
  - `min_overlap_ratio` merges diarization with transcript segments.

---

```yaml
speaker_identification:
  embedding_model_id: pyannote/wespeaker-voxceleb-resnet34-LM
  auth_token_env:
    - HF_TOKEN
    - HUGGINGFACE_TOKEN
  device: GPU
  similarity_threshold: 0.68

speakers:
  known_speakers: {}
```

- `embedding_model_id`: pyannote embedding model.
- `similarity_threshold`: cosine similarity required to reuse an existing speaker.
- `known_speakers`: optional mapping (`speaker_uuid: "Friendly Name"`) applied during transcript export.

---

```yaml
concurrency:
  validation_workers: 2
  transcription_workers: 2
  merge_workers: 3
```

- Tune per hardware. The orchestrator clamps fallback values to `max(1, min(default, cpu_count-1))`.
- Stage 4 (speaker identification) stays serial to avoid race conditions.

---

```yaml
logging:
  log_dir: logs
  log_level: INFO
```

- See [`components/logging.md`](../components/logging.md) for handler details.

---

## Adding New Options

- Place new keys under the most relevant section to keep `config.yaml` navigable.
- Update this document and `README.md` so users discover the change.
- Default to backward-compatible values when the key is absent; update
  `load_config()` if defaults require dynamic calculation.
