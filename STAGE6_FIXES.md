# Stage 6 Transcription Fixes - Summary

## Issues Fixed

### 1. **whisper.cpp Model Path (config.yaml)**
- **Problem**: Config had double "models/" in path and was pointing to encoder-only Core ML file
- **Fix**: Changed `ggml_model_path` to use full GGML model: `ggml-whisper-large-v3-turbo.bin`
- **Changed**: device from `coreml` to `auto` (whisper.cpp will use Metal acceleration automatically)

### 2. **whisper-cli Command Flags (whisper_cpp_wrapper.py)**
- **Problem**: Using invalid flags `--print-timestamps` (doesn't exist) and `--print-progress false` (should be boolean)
- **Fix**: Removed both invalid flags, simplified command to just: `-m <model> -f <audio> --output-json -l <lang>`

### 3. **JSON Output Path Detection (whisper_cpp_wrapper.py)**
- **Problem**: Code expected `audio.json` but whisper-cli creates `audio.wav.json` (appends .json)
- **Fix**: Changed from `Path(audio_path).with_suffix(".json")` to `Path(str(audio_path) + ".json")`

### 4. **JSON Timestamp Parsing (whisper_cpp_wrapper.py)**
- **Problem**: Code tried to use timestamp strings, but whisper.cpp JSON has offsets in milliseconds
- **Fix**: Use `offsets.from` and `offsets.to` fields, convert from milliseconds to seconds (float)

### 5. **Transcript Format (orchestrator.py Stage 6)**
- **Problem**: Transcripts were just plain text with speaker labels, no timestamps or context
- **Fix**: Completely rewrote transcript formatting to include:
  - Header with recording title and wall-clock start time
  - Each line formatted as: `[HH:MM:SS AM/PM] SPEAKER_XX: text`
  - Parse video start time from filename (YYYYMMDD_HHMMSS format)
  - Calculate actual wall-clock time for each segment using `start_time + segment_offset`

## New Transcript Format Example

```
=== TRANSCRIPT: 20251015_215513_Entry+Frontdoor ===
Recording started: October 15, 2025 at 09:55:13 PM

[09:55:13 PM] SPEAKER_00: Oh, there it is.
[09:55:17 PM] SPEAKER_01: And so we're going to go with six worth to take it off the top.
[09:55:22 PM] SPEAKER_00: And if it's too long with Danny, he was like 12.
[09:55:26 PM] SPEAKER_01: And so I was very sad and he was going to work.
[09:55:30 PM] SPEAKER_00: And like numbers called all of them? Yeah.
```

## Benefits

1. **Readable**: Transcripts now read like a script with clear speaker attribution
2. **Contextual**: Wall-clock timestamps help orient the reader to when things were said
3. **Professional**: Format matches standard interview/deposition transcript conventions
4. **Editable**: Speaker labels (SPEAKER_00, SPEAKER_01) can be replaced with real names via profiles.json

## Files Modified

1. `config.yaml` - Fixed model path and device setting
2. `blink_pipeline/whisper_cpp_wrapper.py` - Fixed command flags, JSON path detection, timestamp parsing
3. `blink_pipeline/orchestrator.py` - Rewrote Stage 6 transcript formatting with timestamps and headers

## Next Steps

- Stage 6 is currently regenerating all 12 final transcripts with the new format (background process)
- Stage 7 (speaker profiles) will allow users to edit speaker names in `profiles.json`
- Re-running Stage 6 after editing profiles will substitute real names for SPEAKER_XX labels
