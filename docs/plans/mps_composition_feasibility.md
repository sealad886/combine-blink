# MPS Feasibility Plan for Stage 5 Composition

## Current pipeline summary
- **Sequential merge path:** `blink_pipeline/video.py` (`merge_video_clips`, `_crossfade_pair`, `_concat_pair`) shells out to `ffmpeg`. Hardware encoding is available only when `CB_USE_HW=1`, mapping to `-c:v h264_videotoolbox`, but decode/filters still run on CPU.
- **Multi-camera path:** `blink_pipeline/multi_camera_composer.py` orchestrates a mix of `ffmpeg` commands:
  - Segment extraction (`ffmpeg … -c:v libx264`) — always software encoded.
  - Filter graphs for switching/overlay (`_create_composite_video_single_pass`) — relies on CPU filter implementations.
  - Audio stitching and final mux — also CPU-bound, though some steps copy streams.
- None of these touch PyTorch/Tensor APIs, so the Apple MPS (Metal Performance Shaders) stack is currently unused. The only GPU acceleration is via VideoToolbox encoders/decoders.

## Constraints & unknowns
- FFmpeg does not expose MPS kernels; it supports VideoToolbox/Metal for encode/decode but filter graphs still run on CPU.
- Rewriting the compositor in PyTorch (to leverage MPS) would require reproducing FFmpeg’s timeline trims, transitions, overlays, and audio pipelines manually — a large scope.
- Any GPU solution must remain deterministic and headless (no display server). We also need parity across macOS Apple Silicon and Linux/Nvidia environments used in CI.
- Existing people-detection/speaker stages already use MPS when available (`identify_speaker.py`, `people_detection.py`), so resource contention with a new GPU path must be evaluated.

## Investigation plan
1. **Hotspot profiling**
   - Instrument Stage 5 (`orchestrator.py:540-650`) with timing hooks to log per-group wall time split between segment extraction, filter graph build, and final mux.
   - Capture `ffmpeg -benchmark -stats` output under representative workloads to quantify CPU usage.
   - Output: report in `TEST_RESULTS.md` summarising CPU-bound segments.

2. **Catalogue FFmpeg hardware paths**
   - Verify current VideoToolbox usage: audit each `ffmpeg` invocation in `video.py` and `multi_camera_composer.py` to confirm whether `-hwaccel videotoolbox`, `hwaccel_output_format`, and VideoToolbox encoders are already enabled.
   - Identify filter stages that can switch to Metal-friendly counterparts (e.g. `scale_vt`, `overlay_metal`, `transpose_vt`) without changing pipeline semantics.
   - Output: update `docs/components/multi-camera-composer.md` (new file) with a table of CPU vs. GPU-capable steps.

3. **Prototype VideoToolbox-first command sets**
   - Sequential merge path:
     - Test `ffmpeg` invocations that pull both decode and encode through VideoToolbox (`-hwaccel videotoolbox -hwaccel_output_format videotoolbox`) while preserving existing crossfade graphs.
     - When filters are incompatible with hardware frames, measure the cost of inserting `hwdownload`/`hwupload` pairs versus falling back to CPU decode.
     - Tune defaults (`-b:v`, `-realtime`, `-allow_sw 1`) to balance quality and throughput; document presets for 1080p and 4K.
   - Multi-camera composition:
     - For the single-pass pipeline, experiment with a hybrid graph: keep timeline trims/crossfades on CPU where mandatory, but push scaling, stacking, and overlays to `_vt`/Metal variants.
     - Ensure command sequences gracefully degrade to CPU filters when FFmpeg lacks the Metal filters (Linux, Intel Macs).
   - Output: scripts/notebook under `experiments/mps-composer` showing the VideoToolbox-enabled commands and benchmark deltas.

4. **CPU-path optimisation (no PyTorch rewrite)**
   - For filters that cannot move off CPU, profile and adjust settings:
     - Use `-threads` tuning, `-filter_complex_threads` (FFmpeg >= 6), and `-x264-params`/`-preset fast` to minimise CPU time when forced into software encode.
     - Evaluate `-af aresample=async=1:min_hard_comp=0.1:first_pts=0` to cut audio drift corrections without extra passes.
     - Investigate caching intermediate segments when composition repeats identical trimming (saves disk IO).
   - Capture recommended CPU presets alongside GPU presets so operators can toggle via config.

5. **Integration considerations**
   - Extend configuration (`config.yaml` schema) with a guarded flag `pipeline.enable_gpu_composition`.
   - Update `PipelineDashboard` to display GPU utilisation status (if available via `psutil` or `powermetrics` on macOS).
   - Define validation and regression tests:
     - Add sample fixtures to `tests/integration/test_av_alignment.py` validating both CPU and GPU paths produce byte-identical audio and near-identical video (allowing for encoder variance).
     - Include a CLI smoke test that forces CPU mode (`CB_FORCE_CPU=1`) to guarantee fallback safety.

6. **Decision gate**
   - After prototypes, deliver a go/no-go recommendation summarising:
     - Performance gains vs. baseline (per stage).
     - Maintenance cost and platform support risks.
     - Dependencies (FFmpeg ≥ 6 with `--enable-videotoolbox`/`--enable-metal`, macOS SDK requirements, config toggles).
   - Capture the decision in a new ADR (`docs/history/adr-mps-composition.md`).

## Risks & mitigations
- **Limited FFmpeg GPU filter coverage:** keep CPU pipeline as default, add feature flag and runtime capability detection.
- **CI portability:** only enable MPS path on macOS/Apple Silicon; ensure Linux remains unaffected.
- **Developer tooling:** document prerequisites (macOS 13+, Xcode CLT, FFmpeg build with `--enable-videotoolbox` and optional `--enable-metal`). Provide scripts for automated setup.
