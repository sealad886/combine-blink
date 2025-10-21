# Output Directory Layout

After a successful run the pipeline prints canonical output locations. This file
summarises what to expect in each directory (relative to `paths.output_dir`).

```
output/
├── merged_videos/          # paths.videos_dir
│   ├── 20251015_104607_Entry_merged.mp4
│   └── ...
├── transcripts/            # paths.transcripts_dir
│   ├── 20251015_104607_Entry_transcript.txt
│   └── ...
├── speaker_voice_samples/  # paths.speakers_dir
│   ├── speaker_3f9cc6e1_clip0.wav
│   └── ...
├── repaired_cache/         # transcription.repair_cache_dir
│   ├── repaired_fill_08-37-43_Corner_eaf14f29.mp4
│   └── .preprocessing_progress.json (temporary, removed on success)
└── logs/ (if log_dir is inside output/)
    ├── pipeline.log
    ├── pipeline_errors.log
    └── pipeline_20251021_104607.log
```

## Merged Videos

- Naming: `{group_name}_merged.mp4`.
- Multi-camera events include a `+`-separated camera list (`FrontDoor+Corner`).
- Encoding determined by `MultiCameraComposer` or `merge_video_clips` (H.264
  video, AAC audio, `faststart` flag).

## Transcripts

- Naming: `{group_name}_transcript.txt`.
- Format: one line per diarized segment, prefixed with resolved speaker name/ID.
- Speakers substituted via `SpeakerIdentifier` using configured `known_speakers`.

## Speaker Samples

- Naming: `{speaker_uuid}_{index}.wav`.
- Source: `SpeakerIdentifier` extracts representative audio segments for each
  detected speaker.
- Useful for downstream speaker labelling or voice cloning workflows.

## Repair Cache

- Contents: validated originals or repaired clips ready for reuse.
- Safe to delete if you want to force Stage 0 to re-run repairs (will be rebuilt).
- Hidden progress file is only present during Stage 0 execution; removal at the
  end signals the stage finished cleanly.

## Logs

- Location depends on `logging.log_dir` (may be outside `output/`).
- See [`components/logging.md`](../components/logging.md) for handler details.

## Additional Artefacts

- `speaker_profiles.json` (if produced by `SpeakerIdentifier`) lives alongside
  the speaker audio samples.
- Temporary directories created during processing (`tempfile`) are cleaned up
  automatically; only configured output paths persist.
