# Pipeline Overview

The Blink pipeline is orchestrated by `blink_pipeline/orchestrator.py` and processes each
run through five logical stages (with Stage 0 inserted after discovery/grouping
so repairs happen exactly once). The Rich dashboard (`PipelineDashboard`) wraps
the whole session and exposes per-stage progress, ETA, and resume metadata; see
[`components/dashboard.md`](components/dashboard.md) for details.

| Order | Stage name                     | Key module(s)                | Parallelism | Resume behaviour |
|-------|--------------------------------|------------------------------|-------------|------------------|
| 1     | File discovery                 | `blink_pipeline/discovery.py`           | serial      | n/a              |
| 2     | Video grouping                 | `blink_pipeline/grouping.py`            | serial      | n/a              |
| 0     | Video validation & repair      | `blink_pipeline/media_validation.py`    | process pool (`validation_workers`) | Cached by hashed filename |
| 3     | Transcription & diarization    | `blink_pipeline/transcription.py`       | process pool (`transcription_workers`) | Skips groups with existing transcripts |
| 4     | Speaker identification         | `blink_pipeline/identify_speaker.py`    | serial      | Uses Stage 3 outputs |
| 5     | Video merging / composition    | `blink_pipeline/multi_camera_composer.py`, `blink_pipeline/video.py` | process pool (`merge_workers`) | Skips groups with existing merged video |

## Stage 1 — File Discovery

- Entry point: `discover_files(input_dir, pattern, config)`.
- Parses datestamps from parent folders using `discovery.date_folder_patterns`
  (accepts both two-digit `%y` and four-digit `%Y` patterns).
- Valid clips are returned as dictionaries containing `full_path`, `camera`,
  `datetime`, `filename`, and `directory`.

## Stage 2 — Video Grouping

- Entry point: `group_videos(video_files, max_time_diff_seconds)`.
- Clips are sorted chronologically, then grouped when successive clips start
  within `grouping.max_time_diff_seconds` of the most recent clip in the current
  group.
- Group metadata is later used to derive human-friendly identifiers via
  `_generate_group_name()` in the orchestrator.

## Stage 0 — Validation & Repair

Implemented in `blink_pipeline/media_validation.py` and initiated right after grouping.

- Collects all unique clip paths across groups, then runs `preprocess_videos`
  inside a `ProcessPoolExecutor`.
- Cache keys are collision-safe: `repaired_{strategy}_{stem}_{hash8}.mp4`.
- Progress is surfaced back to the dashboard through the supplied callback.
- Statistics (`total_validated`, `repaired_count`, `original_count`) are
  computed via `get_validation_stats`.
- Results are applied in place by replacing each clip’s `full_path` with the
  validated (or repaired) path from the returned mapping.
- Cache files are persisted under `transcription.repair_cache_dir` and reused on
  subsequent runs; legacy cache names are auto-migrated.

## Stage 3 — Transcription & Diarization

- `process_audio_for_transcription` handles the entire pipeline for a group:
  - Extracts temporary WAV files per clip (`extract_audio_segment`).
  - Sends them through Whisper (either openai-whisper or whisper.cpp via
    `WhisperCppWrapper`, depending on `transcription.whisper` settings).
  - Runs pyannote diarization with optional Hugging Face token discovery.
  - Emits segments with `start`, `end`, `speaker`, `text`, and a timeline that
    preserves per-clip offsets.
- Worker processes are spawned through `_transcribe_group_job`, which wires a
  progress callback so the dashboard reflects per-clip progress and downtown
  queue time is excluded (see [`components/dashboard.md`](components/dashboard.md)).
- Resume support: groups whose `{group_name}_transcript.txt` already exists in
  `output/transcripts/` are skipped and fed forward with original paths.

## Stage 4 — Speaker Identification

- Serial execution via `SpeakerIdentifier`.
- Reuses diarization segments to attribute speech to persistent speaker IDs,
  writing fully labelled transcripts to `output/transcripts/`.
- Produces voice sample WAVs inside `paths.speakers_dir` for downstream tooling.

## Stage 5 — Merging / Multi-camera Composition

- The orchestrator builds `merge_jobs` enriched with clip metadata and checks
  `output/merged_videos/` for existing `{group_name}_merged.mp4` files to support
  resume.
- With multiple cameras *and* `multi_camera_composition.enable_composition`:
  - `MultiCameraComposer.compose_multi_camera_event` performs quality analysis,
    optional per-camera alignment, switching timeline generation (supports
    `speech_people` using a Hugging Face people detector), timestamp overlay,
    and final ffmpeg synthesis. By default, synthesis uses a single-pass
    `-filter_complex` graph for better performance and falls back to a
    multi-step pipeline if needed. Hardware encoders can be enabled via
    `multi_camera_composition.encoding`.
- Single-camera or disabled composition falls back to `merge_video_clips`
  (sequential merge with configurable crossfades).

## Outputs

Upon successful completion the pipeline prints the canonical output locations:

- Videos: `{output_dir}/{paths.videos_dir}`
- Transcripts: `{output_dir}/{paths.transcripts_dir}`
- Speaker samples: `{output_dir}/{paths.speakers_dir}`

See [`reference/output.md`](reference/output.md) for directory layouts and file
conventions.

## Concurrency & Resource Planning

Concurrency knobs live under `concurrency` in `config.yaml`:

- `validation_workers`: Stage 0 workers (I/O bound due to ffmpeg). Default picks
  max(1, min(2, available_cores-1)).
- `transcription_workers`: Stage 3 workers. Each loads Whisper and pyannote, so
  be mindful of GPU/CPU memory.
- `merge_workers`: Stage 5 workers. Each invokes ffmpeg while reading multiple
  inputs.

Speaker identification remains serial to keep the in-memory voiceprint database
consistent.

## Resume Semantics

Resume awareness is entirely file-based:

- Stage 3 skip condition: transcript file exists.
- Stage 5 skip condition: merged video exists.
- Stage 0 and Stage 3 reuse their respective caches (repair cache, speaker
  embeddings) automatically.

Read [`components/resume.md`](components/resume.md) for deeper guidance, edge
cases, and clean-up procedures.

## Logging & Observability

- The orchestrator sets up `PipelineLogger` (file-based logging with rotation)
  before work begins. Workers call `configure_worker_logging` to attach to the
  same files.
- Important actions are mirrored both in the dashboard and in structured logs,
  enabling retrospective analysis even during Rich live updates.

More detail: [`components/logging.md`](components/logging.md).
