# Diarization Bug Fix

## Problem

Cached diarization results contained `null` for the `diarization_result` field, causing Stage 3 to fail silently and Stage 4 to report "0 groups with speech".

## Root Cause

The `_PyannoteDiarizer.diarize_file()` method was attempting to access `.speaker_diarization` attribute on the pipeline output:

```python
diarization_output = self.pipeline(audio_path)
return diarization_output.speaker_diarization  # AttributeError!
```

This code was written for pyannote.audio 2.x API, but we're using pyannote.audio 3.4.0, which returns an `Annotation` object directly from `pipeline(audio_path)`, not a wrapper object.

## Error Message

```
AttributeError: 'Annotation' object has no attribute 'speaker_diarization'
```

## Solution

Changed `blink_pipeline/transcription.py` line 420 to return the `Annotation` object directly:

```python
def diarize_file(self, audio_path: str) -> Any:
    """Run diarization and return Annotation object."""
    if self.pipeline is None:
        raise RuntimeError(
            "pyannote.audio Pipeline is not initialized. Ensure dependencies are installed."
        )
    # In pyannote 3.x, pipeline() returns Annotation directly
    diarization_output = self.pipeline(audio_path)
    return diarization_output
```

## Verification

Tested with `test_diarization_fix.py` on 2 clips:
- ✓ Transcription completed successfully
- ✓ Diarization completed successfully
- ✓ 40 segments with speaker labels extracted
- ✓ Timeline properly constructed

## Impact

- All 14 groups that were failing with null diarization results will now process correctly
- Stage 3 cache will be properly populated with valid diarization data
- Stage 4 speaker identification will receive valid input
- Stage 6 transcripts will include speaker labels

## Cache Cleanup

Deleted all cached files in `output/.diarization_cache/` since they contained null diarization results from failed runs. The pipeline will regenerate valid cache files on the next run.
