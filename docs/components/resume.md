# Resume Behaviour

The pipeline resumes work based on the presence of completed artefacts on disk.
No explicit checkpoint files are required; rerunning `python main.py` is safe
and idempotent.

## Detection Rules

- **Transcripts**: Stage 3 skips groups if
  `{group_name}_transcript.txt` exists under
  `{output_dir}/{paths.transcripts_dir}`.
- **Merged videos**: Stage 5 skips groups if
  `{group_name}_merged.mp4` exists under
  `{output_dir}/{paths.videos_dir}`.
- **Speaker samples**: Created on demand; existing WAVs are left untouched.
- **Repair cache**: Stage 0 reuses any cached files regardless of resume state.

The orchestrator inspects these directories immediately after discovery and
grouping to populate `existing_transcripts` and `existing_videos`. These counts
are surfaced in the dashboard (details column) and included in success counts so
the final summary reflects total completed groups (new + resumed).

## File Naming

- Group names are generated via `_generate_group_name`: `YYYYMMDD_HHMMSS_camera`
  for single-camera events or `YYYYMMDD_HHMMSS_camA+camB[+Nmore]` for multi-camera.
- Transcript filename: `{group_name}_transcript.txt`.
- Merged video filename: `{group_name}_merged.mp4`.
- Speaker samples follow `{speaker_uuid}_{index}.wav` (created by
  `SpeakerIdentifier`).

## Typical Resume Flow

1. Run pipeline, interrupt during Stage 3 or Stage 5.
2. Rerun `python main.py`.
3. Console banner shows counts of transcripts/videos already present.
4. Dashboard stages display `"Resuming: N already complete"` and progress bars
   start at `N`.
5. Only missing groups are processed; summary counts include resumed work.

## Forcing a Fresh Run

Delete or archive existing outputs:

```bash
rm -rf output/transcripts output/merged_videos output/speaker_voice_samples
rm -rf output/repaired_cache  # optional, forces Stage 0 to re-validate
```

Alternatively, move the entire `output/` directory aside.

## Edge Cases & Notes

- If a transcript exists but the merge failed, Stage 3 is skipped yet Stage 5
  will re-run for that group because the merged video is missing.
- Partial transcripts/merges created during a crash are overwritten on resume.
- Stage 0 progress file (`.preprocessing_progress.json`) is removed automatically
  once validation completes, ensuring stale progress does not persist.
- Speaker identification deliberately stays serial so interruptions do not
  corrupt the in-memory voiceprint registry.

## Related Tests

- `test_resume_capability.py`: high-level smoke test of resume detection.
- `test_resume_integration.py`: ensures orchestrator propagates resumed groups.
- `test_logging.py`: verifies resume signals are logged consistently.

Use these tests when modifying resume logic or output naming.
