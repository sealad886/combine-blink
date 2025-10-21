# **Blink Video Processing Pipeline**

This project provides a modular pipeline to process and consolidate Blink security camera footage. It is designed to take a directory of short video clips, group them into events, create multi-camera composite videos from different angles, and generate detailed, diarized transcripts with unique speaker identification.

## **Features**

* **Modular Pipeline Stages:** Each step of the process is handled by a separate module for clarity and maintainability.
* **File Discovery:** Recursively scans an input directory to find all video files.
* **Multi-Camera Composition:** When multiple cameras capture the same event from different angles, the pipeline intelligently combines them into a single composite video, automatically switching between camera angles and selecting the best audio source.
* **Intelligent Time-Based Grouping:** Groups clips by overlapping timestamps, detecting when multiple cameras recorded the same event simultaneously.
* **Automatic Video Repair:** Detects and repairs damaged Blink clips with missing frames or desynchronized audio/video streams, filling gaps with the last known frame while maintaining audio continuity.
* **Advanced Audio Quality Analysis:** Analyzes audio quality across all camera sources and selects the best audio for the final composite.
* **Flexible Camera Switching:** Multiple strategies for switching between camera angles: time-based intervals, round-robin cycling, or audio-quality-based selection.
* **Advanced Audio Processing:** Extracts audio via ffmpeg, performs Whisper-based transcription, and uses pyannote diarization to assign speaker labels with precise timestamps.
* **Robust Speaker Identification:** Generates voice embeddings for every diarized segment, reuses the closest match across events, and archives representative WAV samples for downstream tooling.
* **Speaker Management:** Assigns unique IDs to each detected speaker and allows for naming them in a configuration file.
* **Voice Cloning Prep:** Extracts audio samples for each identified speaker, preparing them for use with voice cloning software.
* **Configuration Driven:** All major settings are controlled via a config.yaml file.
* **Concurrent Processing:** Transcription/diarization and video composition run in parallel across groups with configurable worker counts; speaker identification stays serial to maintain a consistent voiceprint database.

## **Project Structure**

.
├── input\_videos/         \# Place your raw Blink video clips here
│   ├── 2025-10-19/        \# Date folder (YYYY-MM-DD or other supported formats)
│   │   ├── 08-37-43_CornerG8T1K0013255014P_081.mp4
│   │   ├── 08-38-15_FrontDoorG9876543210XYZ_082.mp4
│   │   └── 14-22-30_BackyardG1234567890ABC_083.mp4
│   └── 2025-10-20/
│       └── 09-15-00_CornerG5678901234DEF_001.mp4
├── output/                 \# Processed videos, transcripts, and voice samples appear here
├── config.yaml             \# Main configuration file for the pipeline
├── main.py                 \# The main script to run the pipeline
├── requirements.txt        \# Python dependencies
└── src/
   ├── \_\_init\_\_.py
   ├── discovery.py         \# Stage 1: Finds video files
   ├── grouping.py          \# Stage 2: Groups related video clips
   ├── transcription.py     \# Stage 3: Handles transcription and diarization
   ├── identify\_speaker.py \# Stage 4: Manages speaker identification and voice samples
   └── video.py             \# Stage 5: Merges and processes the video files


## **Filename Format**

Blink video files must follow this naming convention:

```
HH-MM-SS_CameraNameG<suffix>.mp4
```

Where:
* **HH-MM-SS**: Hour-Minute-Second timestamp (e.g., `08-37-43`)
* **CameraName**: Name of the camera, ending right before the 'G' character (e.g., `Corner`, `FrontDoor`, `Backyard`)
* **G<suffix>**: Serial number or identifier starting with 'G' (e.g., `G8T1K0013255014P_081`)

**Example**: `08-37-43_CornerG8T1K0013255014P_081.mp4`
* Time: 08:37:43
* Camera: Corner

**Date from Directory**: The date is parsed from the parent directory name. Supported formats:
* `YYYY-MM-DD` (e.g., `2025-10-19`)
* `YYYYMMDD` (e.g., `20251019`)
* `YYYY_MM_DD` (e.g., `2025_10_19`)
* `MM-DD-YYYY` (e.g., `10-19-2025`)
* `DD-MM-YYYY` (e.g., `19-10-2025`)

## **Setup**

1. Install Dependencies:
   It is highly recommended to use a virtual environment.
   pip install \-r requirements.txt

### Hugging Face access token (required for diarization/embeddings)

Some pyannote models require an authenticated Hugging Face token and model access acceptance:

- Accept the user conditions for the models you use (at minimum):
   - https://huggingface.co/pyannote/segmentation
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM
- Create an access token: https://huggingface.co/settings/tokens
- Provide the token via one of these environment variables (preferred):

   export HF_TOKEN="<your_token>"
   export HUGGINGFACE_TOKEN="<your_token>"

The application will also accept `speaker_identification.auth_token` in `config.yaml`, but environment variables are recommended.

Note on versions: pyannote.audio 3.x expects `use_auth_token=...` when loading; 4.x uses `token=...`. The code handles both automatically.
   *Note:* ffmpeg must be available on your `PATH` because the pipeline shells out for audio extraction and video operations. Whisper and pyannote models download on the first run, so ensure you have adequate disk space and network access.


### Using Custom GGML Models (whisper.cpp) and Core ML (Apple Silicon)

#### Core ML Acceleration for Apple Silicon

The pipeline supports Core ML acceleration for Whisper models on Apple Silicon (M1/M2/M3) via whisper.cpp and pywhispercpp. This enables the encoder to run on the Apple Neural Engine for significant speedup.

**Setup Instructions:**

1. **Install pywhispercpp with Core ML support:**
   ```bash
   WHISPER_COREML=1 pip install git+https://github.com/absadiki/pywhispercpp
   ```

2. **Convert GGML model to Core ML format:**
   - Download or convert your GGML model as above.
   - Use whisper.cpp's conversion script:
     ```bash
     # From whisper.cpp/models directory
     ./generate-coreml-model.sh base.en
     # This creates models/coreml-encoder-base.en.mlpackage
     # The pipeline will auto-compile .mlpackage to .mlmodelc on first use
     ```
   - Repeat for other models as needed (tiny, small, medium, large-v1, etc.).

3. **Configure in config.yaml:**
   ```yaml
   transcription:
     whisper:
       device: "coreml"  # Enables Core ML acceleration
       ggml_model_path: "/path/to/coreml-encoder-base.en.mlmodelc"  # .mlmodelc (compiled) or .mlpackage (uncompiled)
       whisper_cpp_binary: "/path/to/whisper.cpp/build/bin/whisper-cli"  # Optional, auto-detected if omitted
   ```

**Notes:**
- When `device: coreml` is set, the pipeline will use the Core ML backend for Apple Silicon.
- The GGML model path can point to either:
  - `.mlmodelc` directory (compiled Core ML model, ready to use)
  - `.mlpackage` directory (uncompiled Core ML model, will be auto-compiled to `.mlmodelc` on first use)
- Auto-compilation requires Xcode command-line tools (`xcode-select --install`).
- If Core ML support is not installed, or the model path is not set correctly, the pipeline will raise an error.
- Fallback to CPU/GPU/Metal is automatic if `device: auto` is used.

**Troubleshooting:**
- **Core ML not available:** Ensure you installed pywhispercpp with `WHISPER_COREML=1` and have Xcode command-line tools installed.
- **Model not loading:** Verify the `.mlmodelc` or `.mlpackage` directory exists and is valid.
- **Compilation errors:** Ensure Xcode command-line tools are installed: `xcode-select --install`
- **Performance:** Core ML is fastest for encoder inference on Apple Silicon; use Metal or CPU for other platforms.

For more information on Core ML support and model conversion, see:
- whisper.cpp documentation: https://github.com/ggerganov/whisper.cpp
- Core ML conversion guide: https://panjas.com/blog/2024-11-26/coreml-models-for-whisper-cpp

The pipeline supports custom Whisper models in GGML format (.bin files) via whisper.cpp integration. This is useful for:
- Faster inference (whisper.cpp is highly optimized C++)
- Custom fine-tuned models
- Running on resource-constrained systems

**Setup Instructions:**

1. **Install whisper.cpp**:
   ```bash
   # Clone whisper.cpp repository
   git clone https://github.com/ggerganov/whisper.cpp.git
   cd whisper.cpp

   # Build the project
   cmake -B build
   cmake --build build -j --config Release
   ```

   The compiled binary will be at `build/bin/whisper-cli` (or just `whisper` on some systems).

2. **Download or Convert a GGML Model**:

   Option A - Download pre-converted models:
   ```bash
   # Download from Hugging Face
   ./models/download-ggml-model.sh base.en
   ```

   Option B - Convert your custom PyTorch model:
   ```bash
   # Install conversion dependencies
   pip install torch transformers

   # Convert custom model to GGML
   python models/convert-pt-to-ggml.py /path/to/custom-model.pt
   ```

3. **Configure in config.yaml** (GGML/CPU/GPU/Metal):
   ```yaml
   transcription:
     whisper:
       # Comment out or remove model_name when using GGML
       # model_name: "small"

       # Specify path to your GGML model
       ggml_model_path: "/path/to/ggml-custom-model.bin"

       # Optional: Specify whisper.cpp binary location
       # (auto-detected if in PATH or standard locations)
       whisper_cpp_binary: "/path/to/whisper.cpp/build/bin/whisper-cli"

       device: "auto"
   ```

**Notes:**
- When `ggml_model_path` is set, the `model_name` parameter is ignored
- whisper.cpp supports GPU acceleration via CUDA, Metal (macOS), and other backends
- The output format is automatically converted to match openai-whisper for seamless integration
- whisper.cpp binary is auto-detected in common locations (PATH, ./build/bin/, etc.)

**Troubleshooting:**
- **Binary not found**: Ensure whisper.cpp is compiled and the binary is in your PATH, or specify `whisper_cpp_binary` explicitly
- **Model not loading**: Verify the GGML model file exists and is a valid .bin file
- **Slow performance**: Try building whisper.cpp with GPU support (CUDA/Metal)
- **JSON parsing errors**: Ensure you're using a recent version of whisper.cpp (v1.5.0+)

For more information on whisper.cpp models and optimization, see:
- whisper.cpp documentation: https://github.com/ggerganov/whisper.cpp
- Pre-converted GGML models: https://huggingface.co/ggerganov/whisper.cpp


2. Configure the Pipeline:
   Open the config.yaml file and edit the settings to match your environment.
   * paths: Set your input and output directories.
   * grouping: Adjust the max\_time\_diff\_seconds to control how far apart clips can be to be considered part of the same event.
   * **transcription.whisper.language**: Set to force a specific language (e.g., `"en"` for English, `"es"` for Spanish) to prevent auto-detection errors. Set to `null` or omit for auto-detection.
   * video\_processing: Set the crossfade duration.
   * transcription: Choose the Whisper model/device and point pyannote to a valid Hugging Face token (set `auth_token` directly or via `auth_token_env`—the pipeline checks `HF_TOKEN` first, then `HUGGINGFACE_TOKEN`).
   * speaker_identification: Configure the embedding model, similarity threshold, and token used to power cross-event speaker recognition (also falls back to the `HF_TOKEN` environment variable by default).
   * speakers: After a first run, you can map the generated speaker\_uuids to real names.
3. Add Video Files:
    Organize your Blink .mp4 files into date-named folders within the directory specified by input\_dir in your config.yaml.

    Example structure:
    ```
    input_videos/
       2025-10-19/
          08-37-43_CornerG8T1K0013255014P_081.mp4
          08-38-15_FrontDoorG9876543210XYZ_082.mp4
       2025-10-20/
          09-15-00_CornerG5678901234DEF_001.mp4
    ```

## **Multi-Camera Composition**

When multiple cameras capture the same event from different angles (e.g., all cameras in the same room triggered by motion), the pipeline can intelligently combine them into a single composite video with:

- **Automatic angle switching** between cameras
- **Best audio source selection** across all cameras
- **Smooth transitions** between angles

### How Multi-Camera Grouping Works

Unlike traditional camera-by-camera grouping, the pipeline uses **time-based overlap detection**:

1. **All clips are sorted chronologically** regardless of camera
2. **Clips within the grouping window are combined** into a single multi-camera event
3. **The window extends dynamically** - each new clip can extend the window from the most recent clip

**Example:**
```
Camera A triggers at 10:00:00
Camera B triggers at 10:00:05  (5 seconds later, within window)
Camera C triggers at 10:01:00  (60 seconds after A, 55 seconds after B)

With max_time_diff_seconds = 60:
→ All three clips are grouped together into one multi-camera event
```

### Composition Strategies

The pipeline offers three camera switching strategies:

#### 1. Time-Based Switching (Default)
```yaml
multi_camera_composition:
  switching_strategy: time_based
  switching_interval: 5.0  # Switch cameras every 5 seconds
```
- Switches to the next available camera at regular intervals
- Predictable, rhythmic switching pattern
- Good for events where all angles are equally important

#### 2. Audio Quality-Based Switching
```yaml
multi_camera_composition:
  switching_strategy: audio_quality
  switching_interval: 5.0  # Minimum duration before switching
```
- Analyzes RMS audio levels for each camera
- Prefers cameras with better audio quality (speech range: -30dB to -15dB)
- Ideal when audio clarity is paramount

#### 3. Round-Robin Switching
```yaml
multi_camera_composition:
  switching_strategy: round_robin
  switching_interval: 5.0  # Time per camera
```
- Cycles through all available cameras equally
- Ensures every camera gets equal screen time
- Useful for balanced coverage of the scene

### Audio Source Selection

The pipeline analyzes audio quality across all cameras and can select the best source:

```yaml
multi_camera_composition:
  audio_source: best_quality  # Options: 'best_quality', 'first', 'longest'
```

- **`best_quality`** (recommended): Uses ffmpeg `astats` filter to analyze RMS levels and selects the camera with the clearest audio
- **`first`**: Uses audio from the first camera that triggered
- **`longest`**: Uses audio from the camera with the longest recording duration

### Fine Audio Alignment (per-camera)

Different Blink cameras can have slight clock drift or per-file A/V offsets. The composer estimates a small per-camera offset using audio cross-correlation and applies it uniformly to all clips of that camera within the event. This reduces lip-sync and inter-camera misalignment.

```yaml
multi_camera_composition:
   audio_alignment:
      enabled: true
      max_shift_seconds: 1.5           # clamp estimated offset to avoid overcorrection
      analysis_window_seconds: 12.0     # window length used for correlation
      sample_rate: 16000                # resample rate for analysis
      bandpass: true                    # focus on speech band
      highpass_hz: 300
      lowpass_hz: 3000
```

Notes:
- The reference camera is chosen by best audio quality; other cameras are aligned to it.
- If overlap between cameras is < 5s, alignment falls back to 0 for that camera.
- Set `enabled: false` to turn off.

### Timestamp Overlay (with DST correction)

Optionally burn a wall-clock timestamp (bottom-right) throughout the composite. Useful for audits and quick verification. Blink often timestamps files one hour off due to DST; you can add a fixed offset.

```yaml
multi_camera_composition:
   timestamp_overlay:
      enabled: true
      font: Arial
      font_size: 24
      margin_v: 20
      margin_r: 20
      dst_offset_hours: 1    # add 1h to the parsed wall clock to correct DST
```

Notes:
- The overlay is rendered using ASS subtitles via ffmpeg/libass.
- If applying the overlay fails (e.g., font not available), composition continues without it.

### Configuration Options

Add these settings to your `config.yaml`:

```yaml
multi_camera_composition:
  # Enable multi-camera composition (set to false to use simple sequential merge)
  enable_composition: true

  # Switching strategy: 'time_based', 'round_robin', or 'audio_quality'
  switching_strategy: time_based

  # How often to switch cameras (in seconds)
  switching_interval: 5.0

  # Transition style: 'cut' (instant) or 'crossfade' (smooth but slower)
  transition_style: cut

  # Crossfade duration in seconds (only used if transition_style is 'crossfade')
  transition_duration: 0.5

  # Audio source selection: 'best_quality', 'first', or 'longest'
  audio_source: best_quality
```

### Grouping Configuration

Control how clips are grouped into multi-camera events:

```yaml
grouping:
  # Maximum time difference (in seconds) between clips to group them together
  # Larger values group more clips together (useful if cameras trigger with delays)
  # Smaller values create separate events more easily
  max_time_diff_seconds: 60  # 1 minute window
```

**Recommendations:**
- **Tight synchronization** (cameras trigger within seconds): Use 30-60 seconds
- **Loose synchronization** (cameras trigger with delays): Use 120-300 seconds
- **Sequential events** (one camera, multiple clips): Use 60-120 seconds

### When Multi-Camera Composition is Used

- **Multiple cameras detected**: When a group contains clips from 2+ different cameras
- **Composition enabled**: When `enable_composition: true` in config
- **Automatic fallback**: If only one camera is in the group, falls back to sequential merge

### Example Output

For a multi-camera event with 3 cameras (FrontDoor, Corner, Backyard):

```
Input:
  - 08-37-43_FrontDoor.mp4 (60 seconds)
  - 08-37-48_Corner.mp4 (60 seconds)
  - 08-37-52_Backyard.mp4 (60 seconds)

Output:
  - 20251019_083743_FrontDoor+Corner+Backyard_merged.mp4
    → Composite video with automatic angle switching
    → Audio from the camera with best quality
    → Duration: ~60 seconds (covering the full event span)
```

### Disabling Multi-Camera Composition

If you prefer the old behavior (sequential merge per camera), disable composition:

```yaml
multi_camera_composition:
  enable_composition: false
```

This will process each camera's clips separately using simple sequential merging with crossfades.

## **Video Repair for Damaged Clips**

Blink cameras sometimes save damaged video clips with missing frames or desynchronized audio/video streams due to connectivity issues. The pipeline includes automatic repair functionality to handle these cases gracefully.

### How Video Repair Works

The repair system:
1. **Detects Issues**: Checks for audio/video stream length mismatches (>100ms difference)
2. **Fills Missing Frames**: Uses the last known good frame to fill gaps in the video stream
3. **Synchronizes Streams**: Trims excess video or pads audio to ensure perfect sync
4. **Maintains Audio**: Keeps audio stream continuous and uninterrupted
5. **Caches Results**: Saves repaired videos to avoid re-processing

### Configuration

Edit `config.yaml` to control repair behavior:

```yaml
transcription:
  # Repair damaged videos automatically
  always_repair: false  # true = repair all videos, false = only when sync issues detected

  # Cache repaired videos to avoid re-processing
  repair_cache_dir: "output/repaired_cache"  # or null to disable caching
```

### When Repair Happens

- **Automatic Detection**: When audio/video streams differ by more than 100ms
- **Always On**: Set `always_repair: true` to repair all clips regardless
- **On Errors**: When h264 decoder errors indicate corrupted frames

### What Gets Repaired

- **Missing Frames**: Gaps in video stream are filled with last known frame
- **Audio/Video Sync**: Streams are synchronized to the same duration
- **Corrupted Frames**: Damaged h264 frames are handled gracefully
- **Stream Gaps**: Video or audio gaps are filled to maintain continuity

### Performance

- **First Run**: Repairs are performed and cached (adds processing time)
- **Subsequent Runs**: Cached repairs are reused (no additional time)
- **Cache Location**: `repair_cache_dir` in config (default: `output/repaired_cache`)

### Technical Details

The repair process uses ffmpeg with:
- `fps=25`: Maintains consistent frame rate
- `trim`: Removes excess video beyond audio duration
- `apad`: Pads audio with silence if shorter than video
- `err_detect=ignore_err`: Handles corrupted frames gracefully
- `libx264`: Re-encodes video for consistency

## **Running the Pipeline**

To run the entire pipeline, simply execute the main.py script:

```bash
python main.py
```

The pipeline will display a comprehensive progress interface showing:
- Overall pipeline status with stage indicators
- Real-time progress bars for each stage
- Time elapsed and estimated time remaining
- Current group being processed
- Final summary with output counts and locations

### Progress Display Features
- **Visual Progress Bars**: See completion percentage with animated bars
- **Time Estimates**: Know exactly how long each stage will take
- **Concurrent Updates**: Track multiple workers processing groups simultaneously
- **Clean Output**: Professional emoji-based indicators and in-place updates
- **SIGINT Handling**: Press Ctrl+C to cleanly stop all workers

Once complete, you will find the processed videos, transcripts, and speaker audio samples in the output/ directory (or your configured output path).

## **Resume Functionality**

The pipeline is fully **idempotent** and will automatically resume from where it left off if interrupted. This makes it safe to run multiple times without re-processing already completed groups.

### How Resume Works

The pipeline detects existing output files and skips groups that have already been processed:

- **Stage 3 (Transcription)**: Checks for existing `{group_name}_transcript.txt` files
- **Stage 5 (Video Merging)**: Checks for existing `{group_name}_merged.mp4` files

When you run the pipeline, it will:
1. Scan existing output directories at startup
2. Display a banner showing what will be resumed (if anything)
3. Skip already-completed groups during processing
4. Log skipped groups with clear messages
5. Include both new and existing groups in success counts

### Example Scenarios

**First Run (Interrupted)**:
```bash
$ python main.py
# Processes 5 groups, interrupted after completing 2 transcripts and 1 video
^C  # User presses Ctrl+C
```

**Resume Run**:
```bash
$ python main.py

📊 Existing output detected:
   - 2 transcript(s) in output/transcripts
   - 1 merged video(s) in output/merged_videos
   ℹ️  Pipeline will resume from existing output

# Stage 3 will skip 2 groups (already transcribed)
# Stage 5 will skip 1 group (already merged)
# Only new groups will be processed
```

### What Is Preserved

- ✅ **Transcripts**: Existing `.txt` files are detected and skipped
- ✅ **Merged Videos**: Existing `.mp4` files are detected and skipped
- ✅ **Speaker Profiles**: `speaker_profiles.json` is continuously updated
- ✅ **Voice Samples**: Once extracted, samples are never re-created

### What Is Not Preserved

- ❌ **Partial Group Progress**: If a group was interrupted mid-processing, it will restart from the beginning
- ❌ **In-Memory State**: The pipeline doesn't use state files; detection is purely file-based

### Testing Resume

To test the resume functionality:

1. Run the pipeline: `python main.py`
2. Interrupt it with `Ctrl+C` during Stage 3 or 5
3. Re-run: `python main.py`
4. Watch for "Skipping {group_name}" messages in the logs
5. Verify that existing files are not re-created

For more details, see [RESUME_FUNCTIONALITY.md](RESUME_FUNCTIONALITY.md).

## **How It Works**

The pipeline executes a series of stages in a specific order:

1. **File Discovery:** Scans the input\_dir for files matching the video\_file\_pattern defined in the config.

2. **Video Grouping:** Parses the camera name and timestamp from each filename, then uses **time-based overlap detection** to group clips:
   - All clips are sorted chronologically regardless of camera
   - Clips that start within `max_time_diff_seconds` of the most recent clip in a group are added to that group
   - This creates multi-camera events when multiple cameras capture the same moment from different angles
   - Each group represents a single "event" (which may be captured by one or multiple cameras)

3. **Processing Loop:** The pipeline iterates through each event group and performs the following steps:

   a. **Audio Extraction & Repair**: Audio for each clip is extracted to short-lived WAV files via ffmpeg. Damaged clips are automatically repaired (filled frames, synchronized streams).

   b. **Transcription & Diarization**: Whisper transcribes each clip, and pyannote diarization labels the speakers. The results are merged using the original clip offsets to produce a single, chronologically accurate transcript.

   c. **Speaker Identification**: For each diarized segment the pipeline extracts an aligned audio window, computes a pyannote embedding, and either reuses the closest existing speaker profile (via cosine similarity) or registers a new persistent speaker ID. The first time a speaker is heard, a sample of their voice is saved to the speakers\_dir for future voice cloning.

   d. **Multi-Camera Composition / Video Merging**:
      - **Multi-Camera Groups**: If the group contains clips from multiple cameras, the multi-camera composer:
        1. Analyzes audio quality for each camera
        2. Selects the best audio source
        3. Generates a switching timeline based on the configured strategy
        4. Creates a composite video with automatic angle switching
      - **Single-Camera Groups**: Uses simple sequential merge with crossfade transitions

   e. **Output Generation**: The final composite/merged video, the diarized transcript (with speaker names substituted from the config), and the speaker voice samples are all saved to the output\_dir.

This modular approach ensures that you can easily swap out the AI/ML models for transcription, diarization, or audio cleaning as new, better technologies become available without having to rewrite the entire pipeline.

## Concurrency

Stages that benefit from parallelism have been parallelized with sensible defaults and can be tuned in `config.yaml`:

```yaml
concurrency:
   transcription_workers: 2  # Stage 3: number of parallel groups to transcribe/diarize
   merge_workers: 3          # Stage 5: number of parallel groups to compose/merge with ffmpeg
```

Notes:
- Stage 3 (Transcription & Diarization) runs per-group in separate worker processes. Each worker loads its own models; keep the worker count modest to avoid high memory usage and long model initialization time.
- Stage 4 (Speaker Identification) remains serial by design because it updates a shared on-disk voiceprint database and global in-memory state for identity resolution.
- Stage 5 (Multi-Camera Composition / Merging) runs per-group in parallel workers. Each worker invokes external `ffmpeg` processes for composition; CPU and I/O usage can be significant. Tune `merge_workers` based on your CPU and disk throughput.
- Defaults aim to be safe on Apple Silicon laptops (using ~1 less than all cores). Increase cautiously on workstations.
