import json
import logging
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import yaml

from .discovery import discover_files
from .grouping import group_videos
from .identify_speaker import SpeakerIdentifier
from .logging_config import configure_worker_logging, setup_pipeline_logging
from .media_validation import get_validation_stats, preprocess_videos
from .multi_camera_composer import MultiCameraComposer
from .pipeline_dashboard import PipelineDashboard
from .stages import StageKey
from .transcription import process_audio_for_transcription
from .video import merge_video_clips


def load_config():
    """Loads the YAML configuration file."""
    try:
        with open('config.yaml') as f:
            config = yaml.safe_load(f)

        # Add default logging configuration if not present
        if 'logging' not in config:
            config['logging'] = {
                'log_dir': 'logs',
                'log_level': 'INFO'
            }

        return config
    except FileNotFoundError:
        # Use basic logging since our logging system isn't set up yet
        print("ERROR: Configuration file 'config.yaml' not found. Please create one.", file=sys.stderr)
        exit(1)
    except yaml.YAMLError as e:
        print(f"ERROR: Error parsing configuration file: {e}", file=sys.stderr)
        exit(1)

def setup_directories(config):
    """Creates necessary output directories if they don't exist."""
    output_dir = config['paths']['output_dir']
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, config['paths']['videos_dir']), exist_ok=True)
    os.makedirs(os.path.join(output_dir, config['paths']['transcripts_dir']), exist_ok=True)
    os.makedirs(os.path.join(output_dir, config['paths']['speakers_dir']), exist_ok=True)

def _format_hms(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def _generate_group_name(group: list[dict[str, Any]]) -> str:
    """
    Generate a unique name for a video group.

    For multi-camera groups, uses the earliest timestamp and lists all cameras.
    For single-camera groups, uses timestamp and camera name.

    Args:
        group: List of video clip dictionaries

    Returns:
        str: Unique group name
    """
    if not group:
        return "unknown"

    # Get earliest timestamp
    earliest = min(clip['datetime'] for clip in group)
    timestamp_str = earliest.strftime('%Y%m%d_%H%M%S')

    # Get all unique cameras, sorted for consistency
    cameras = sorted(set(clip['camera'] for clip in group))

    if len(cameras) == 1:
        # Single camera group
        return f"{timestamp_str}_{cameras[0]}"
    else:
        # Multi-camera group - use abbreviated camera list
        camera_str = '+'.join(cameras[:3])  # Limit to first 3 cameras to keep name reasonable
        if len(cameras) > 3:
            camera_str += f'+{len(cameras)-3}more'
        return f"{timestamp_str}_{camera_str}"


def _get_profiles_path(config: dict[str, Any]) -> str:
    """Return path to the editable speaker profiles JSON."""
    output_dir = config['paths']['output_dir']
    speakers_dir = os.path.join(output_dir, config['paths']['speakers_dir'])
    os.makedirs(speakers_dir, exist_ok=True)
    return os.path.join(speakers_dir, 'profiles.json')


def _load_profile_name_map(config: dict[str, Any]) -> dict[str, str]:
    """Load a mapping of speaker_id -> friendly name from profiles.json if present."""
    path = _get_profiles_path(config)
    names: dict[str, str] = {}
    try:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f) or {}
            speakers = (data.get('speakers') or {})
            for sid, meta in speakers.items():
                nm = (meta or {}).get('name')
                if isinstance(nm, str) and nm.strip():
                    names[sid] = nm.strip()
    except Exception:
        # Non-fatal; proceed without names
        pass
    # Merge with config-known names (config takes precedence)
    cfg_names = ((config.get('speakers') or {}).get('known_speakers') or {})
    if isinstance(cfg_names, dict):
        names.update({k: v for k, v in cfg_names.items() if isinstance(v, str) and v.strip()})
    return names


def _write_speaker_profiles(config: dict[str, Any]) -> tuple[int, str]:
    """Create/update speakers/profiles.json summarizing discovered speakers and samples.

    Returns (count, path)
    """
    output_dir = config['paths']['output_dir']
    speakers_dir = os.path.join(output_dir, config['paths']['speakers_dir'])
    os.makedirs(speakers_dir, exist_ok=True)
    profiles_path = _get_profiles_path(config)

    # Gather samples by speaker id
    samples_by_id: dict[str, list[str]] = {}
    for entry in os.listdir(speakers_dir):
        if not entry.lower().endswith('.wav'):
            continue
        sid = os.path.splitext(entry)[0]
        samples_by_id.setdefault(sid, []).append(entry)

    # Load existing names if any
    existing_names: dict[str, str] = {}
    try:
        if os.path.exists(profiles_path):
            with open(profiles_path, encoding='utf-8') as f:
                payload = json.load(f) or {}
            for sid, meta in (payload.get('speakers') or {}).items():
                nm = (meta or {}).get('name')
                if isinstance(nm, str) and nm.strip():
                    existing_names[sid] = nm.strip()
    except Exception:
        existing_names = {}

    # Merge config-known names
    cfg_names = ((config.get('speakers') or {}).get('known_speakers') or {})
    if isinstance(cfg_names, dict):
        for k, v in cfg_names.items():
            if isinstance(v, str) and v.strip():
                existing_names[k] = v.strip()

    # Build document
    speakers_doc: dict[str, Any] = {}
    for sid, files in sorted(samples_by_id.items()):
        speakers_doc[sid] = {
            "name": existing_names.get(sid),
            "samples": sorted(files),
            "notes": "Edit 'name' with a friendly label. Names here are used in final transcripts.",
        }

    doc = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec='seconds'),
        "speakers": speakers_doc,
    }

    # Write atomically
    try:
        tmp_path = profiles_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp_path, profiles_path)
    except Exception as exc:
        logging.getLogger("pipeline").warning("Failed to write profiles.json: %s", exc)
    return len(speakers_doc), profiles_path


def _transcribe_group_job(args: tuple[str, list[str], dict[str, Any], Any, Any]) -> tuple[str, list[str], dict[str, Any] | None]:
    """Worker: run Stage 3 for a single group and return processed paths and diarization.

    Progress is tracked per-clip within the group, so progress bar shows:
    - Total: number of clips in the group
    - Progress: number of clips completed so far
    """
    group_name, video_paths, config, progress_dict, task_id = args

    # Configure worker logging (file-based, not console)
    log_dir = config.get('logging', {}).get('log_dir', 'logs')
    configure_worker_logging(log_dir)

    # Use named logger directly for transcription

    # Check for cached diarization result
    output_dir = config['paths']['output_dir']
    cache_dir = os.path.join(output_dir, '.diarization_cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{group_name}_diarization.json")

    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding='utf-8') as f:
                cached_data = json.load(f)
            logging.getLogger("pipeline.transcription").info(f"Using cached diarization for group: {group_name}")

            # Extract processed paths and diarization result
            processed_video_paths = cached_data.get('processed_paths', video_paths)
            diarization_result = cached_data.get('diarization_result')

            # Mark progress as complete immediately
            total_clips = len(video_paths)
            progress_dict[task_id] = {"progress": total_clips, "total": total_clips, "visible": False}

            return group_name, processed_video_paths, diarization_result
        except Exception as e:
            logging.getLogger("pipeline.transcription").warning(f"Failed to load cached diarization for {group_name}: {e}, re-processing")

    logging.getLogger("pipeline.transcription").info(f"Starting transcription for group: {group_name} ({len(video_paths)} clips)")

    # Initialize progress with actual number of clips to process
    total_clips = len(video_paths)
    progress_dict[task_id] = {"progress": 0, "total": total_clips, "visible": True}

    # Create a progress callback that updates the shared dict
    def progress_callback(completed_clips: int):
        progress_dict[task_id] = {"progress": completed_clips, "total": total_clips, "visible": True}

    # Pass progress callback to transcription
    try:
        diarization_result = process_audio_for_transcription(video_paths, config, progress_callback=progress_callback)
        logging.getLogger("pipeline.transcription").info(f"Transcription completed for group: {group_name}")
    except Exception:
        logging.getLogger("pipeline.transcription").error(f"Transcription failed for group: {group_name}", exc_info=True)
        diarization_result = None

    # Derive processed (repaired/original) paths for later merging
    if diarization_result and 'timeline' in diarization_result:
        processed_video_paths: list[str] = [
            (entry.get('used_path') or entry.get('path') or entry.get('original_path'))
            for entry in diarization_result['timeline']
            if (entry.get('used_path') or entry.get('path') or entry.get('original_path'))
        ]
    else:
        processed_video_paths = list(video_paths)

    # Mark as complete
    progress_dict[task_id] = {"progress": total_clips, "total": total_clips, "visible": False}

    # Cache the diarization result for future runs
    try:
        cache_data = {
            'group_name': group_name,
            'processed_paths': processed_video_paths,
            'diarization_result': diarization_result,
            'timestamp': datetime.now().isoformat()
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        logging.getLogger("pipeline.transcription").info(f"Cached diarization result for group: {group_name}")
    except Exception as e:
        logging.getLogger("pipeline.transcription").warning(f"Failed to cache diarization for {group_name}: {e}")

    return group_name, processed_video_paths, diarization_result


def _merge_group_job(args: tuple[str, list[dict[str, Any]], str, dict[str, Any], dict[str, Any] | None, Any, Any]) -> tuple[str, bool, str]:
    """Worker: run Stage 5 merge/composition for a single group."""
    group_name, video_clips, output_video_path, config, diarization_result, progress_dict, task_id = args

    # Configure worker logging (file-based, not console)
    log_dir = config.get('logging', {}).get('log_dir', 'logs')
    configure_worker_logging(log_dir)

    # Use named logger directly for merging
    logging.getLogger("pipeline.merge").info(f"Starting merge for group: {group_name} ({len(video_clips)} clips)")

    # Update progress via shared dict - show total clips being merged
    total_clips = len(video_clips)

    # Initialize progress entry with start_time
    progress_dict[task_id] = {
        "progress": 0,
        "total": total_clips,
        "visible": True,
        "start_time": time.time()
    }

    # Progress callback to update shared dict
    # NOTE: This must be defined in the worker process (not passed as a closure)
    # because closures cannot be pickled for multiprocessing
    def update_progress(completed: int, total: int):
        """Update progress in shared dict for dashboard."""
        try:
            progress_dict[task_id] = {
                "progress": completed,
                "total": total,
                "visible": True,
                "start_time": progress_dict[task_id].get("start_time", time.time())
            }
            logging.getLogger("pipeline.merge").info(f"[PROGRESS] {group_name}: {completed}/{total}")
        except Exception as e:
            logging.getLogger("pipeline.merge").warning(f"Failed to update progress: {e}")

    # Use multi-camera composer if enabled and multiple cameras detected
    cameras = set(clip['camera'] for clip in video_clips)
    use_composer = (
        len(cameras) > 1 and
        config.get('multi_camera_composition', {}).get('enable_composition', True)
    )

    try:
        if use_composer:
            # Multi-camera composition
            logging.getLogger("pipeline.merge").info(f"Using multi-camera composition for {group_name} ({len(cameras)} cameras)")
            composer = MultiCameraComposer(config)
            speech_segments = None
            speech_timeline = None
            if diarization_result:
                speech_segments = diarization_result.get('segments')
                speech_timeline = diarization_result.get('timeline')
            ok = composer.compose_multi_camera_event(
                video_clips,
                output_video_path,
                speech_segments=speech_segments,
                speech_timeline=speech_timeline,
                progress_callback=update_progress,
            )
        else:
            # Fallback to sequential merge (single camera or composition disabled)
            logging.getLogger("pipeline.merge").info(f"Using sequential merge for {group_name}")
            # Extract processed paths in chronological order
            sorted_clips = sorted(video_clips, key=lambda x: x['datetime'])
            processed_video_paths = [clip['path'] for clip in sorted_clips]
            crossfade = config.get('video_processing', {}).get('crossfade_duration', 0.5)
            ok = merge_video_clips(processed_video_paths, output_video_path, crossfade)

        if ok:
            logging.getLogger("pipeline.merge").info(f"Merge completed successfully for group: {group_name}")
        else:
            logging.getLogger("pipeline.merge").error(f"Merge failed for group: {group_name}")

    except Exception:
        logging.getLogger("pipeline.merge").error(f"Merge error for group: {group_name}", exc_info=True)
        ok = False

    # Mark as complete - all clips merged
    progress_dict[task_id] = {"progress": total_clips, "total": total_clips, "visible": False}

    return group_name, ok, output_video_path


def main():
    """Main function to orchestrate the video processing pipeline."""
    config = load_config()
    setup_directories(config)

    # Set up comprehensive file-based logging
    pipeline_logger = setup_pipeline_logging(config)

    # Stage keys are defined in STAGE_DEFINITIONS (imported from pipeline_dashboard)
    # All progress, status, and timing updates go through the dashboard instance

    # Optional standalone modes
    if len(sys.argv) > 1:
        mode = sys.argv[1].strip().lower()
        if mode in {"final-transcribe-only", "build-speaker-profiles-only"}:
            # Minimal dashboard context
            output_dir = config['paths']['output_dir']
            group_outputs_dir = os.path.join(output_dir, config['paths']['videos_dir'])
            transcripts_dir = os.path.join(output_dir, config['paths']['transcripts_dir'])
            transcripts_final_dir = os.path.join(transcripts_dir, 'final')
            os.makedirs(transcripts_final_dir, exist_ok=True)

            # Set up comprehensive file-based logging
            pipeline_logger = setup_pipeline_logging(config)

            if mode == "final-transcribe-only":
                merged = []
                if os.path.exists(group_outputs_dir):
                    for f in os.listdir(group_outputs_dir):
                        if f.endswith("_merged.mp4"):
                            gname = f[:-len("_merged.mp4")]
                            merged.append((gname, os.path.join(group_outputs_dir, f)))
                dashboard = PipelineDashboard(total_videos=0, total_groups=len(merged), total_clips=0)
                with dashboard:
                    dashboard.start_stage('final_transcription', len(merged))
                    # Prepare SpeakerIdentifier and merge in profile names
                    try:
                        speaker_identifier = SpeakerIdentifier(config)
                        name_map = _load_profile_name_map(config)
                        if name_map:
                            speaker_identifier.known_speakers_map.update(name_map)
                    except Exception as exc:
                        speaker_identifier = None
                        logging.getLogger("pipeline").warning("SpeakerIdentifier unavailable; proceeding without naming: %s", exc)

                    completed = 0
                    for group_name, video_path in merged:
                        final_txt = os.path.join(transcripts_final_dir, f"{group_name}_final_transcript.txt")
                        if os.path.exists(final_txt):
                            completed += 1
                            dashboard.update_stage('final_transcription', completed, f"Skip (exists): {group_name}")
                            continue
                        diarization_result = None
                        try:
                            diarization_result = process_audio_for_transcription([video_path], config)
                        except Exception as exc:
                            logging.getLogger("pipeline").warning("Final transcription diarization failed for %s: %s", group_name, exc)

                        lines: list[str] = []
                        if diarization_result and diarization_result.get('segments'):
                            # Optionally resolve and substitute names
                            if speaker_identifier is not None:
                                try:
                                    speaker_identifier.process_transcript(
                                        diarization_result['segments'], diarization_result.get('timeline', [])
                                    )
                                    final_segments = speaker_identifier.substitute_names_in_transcript(
                                        diarization_result['segments']
                                    )
                                except Exception as exc:
                                    logging.getLogger("pipeline").warning("Speaker resolution failed for %s: %s", group_name, exc)
                                    final_segments = diarization_result['segments']
                            else:
                                final_segments = diarization_result['segments']
                            for entry in final_segments:
                                spk = entry.get('speaker', 'Unknown')
                                text = entry.get('text', '')
                                lines.append(f"{spk}: {text}")
                        else:
                            # Fallback: plain whisper.cpp transcription without diarization
                            try:
                                from blink_pipeline.media_utils import extract_audio_segment
                                from blink_pipeline.whisper_cpp_wrapper import WhisperCppWrapper
                                whisper_cfg = (config.get('transcription') or {}).get('whisper', {})
                                ggml = whisper_cfg.get('ggml_model_path')
                                binary = whisper_cfg.get('whisper_cpp_binary')
                                device = whisper_cfg.get('device', 'auto')
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix='.wav', delete=True) as tmp:
                                    if not extract_audio_segment(video_path, tmp.name):
                                        raise RuntimeError("Audio extraction failed")
                                    wrapper = WhisperCppWrapper(model_path=ggml, whisper_cpp_binary=binary, device=device)
                                    res = wrapper.transcribe(tmp.name, language=whisper_cfg.get('language'))
                                    text = (res or {}).get('text') or ''
                                    if text:
                                        lines.append(text)
                            except Exception as exc:
                                logging.getLogger("pipeline").error("Plain transcription failed for %s: %s", group_name, exc)
                                lines.append("<transcription unavailable>")

                        with open(final_txt, 'w', encoding='utf-8') as fh:
                            fh.write("\n".join(lines) + ("\n" if lines else ""))
                        completed += 1
                        dashboard.update_stage('final_transcription', completed, f"Done: {group_name}")
                    dashboard.complete_stage('final_transcription', f"{completed} groups transcribed")
                print(f"\nFinal transcripts saved to: {transcripts_final_dir}\n")
                pipeline_logger.log_session_end(success=True)
                return

            if mode == "build-speaker-profiles-only":
                dashboard = PipelineDashboard(total_videos=0, total_groups=0, total_clips=0)
                with dashboard:
                    dashboard.start_stage('speaker_profiles', 1)
                    count, path = _write_speaker_profiles(config)
                    dashboard.update_stage('speaker_profiles', 1, f"{count} speakers")
                    dashboard.complete_stage('speaker_profiles', f"Profiles at {path}")
                print(f"\nSpeaker profiles: {path}\n")
                pipeline_logger.log_session_end(success=True)
                return

    # --- STAGE 1: File Discovery ---
    print(f"\n{'='*80}")
    print("🎬 BLINK VIDEO PROCESSING PIPELINE")
    print(f"{'='*80}\n")

    logging.getLogger("pipeline").info("Starting pipeline execution")
    pipeline_logger.log_stage_start("File Discovery", 1)

    # Check for existing output to inform user about resume capability
    transcripts_dir_check = os.path.join(config['paths']['output_dir'], config['paths']['transcripts_dir'])
    videos_dir_check = os.path.join(config['paths']['output_dir'], config['paths']['videos_dir'])
    has_existing_output = (
        (os.path.exists(transcripts_dir_check) and any(f.endswith('.txt') for f in os.listdir(transcripts_dir_check))) or
        (os.path.exists(videos_dir_check) and any(f.endswith('.mp4') for f in os.listdir(videos_dir_check)))
    )

    if has_existing_output:
        print("📁 Existing output detected - pipeline will resume from where it left off")
        print("   (Already completed groups will be skipped)\n")

    video_files = discover_files(
        config['paths']['input_dir'],
        config['discovery']['filename_pattern'],
        config
    )

    if not video_files:
        print("⚠️  No video files found. Exiting.")
        logging.getLogger("pipeline").warning("No video files found in input directory")
        pipeline_logger.log_session_end(success=False)
        return

    logging.getLogger("pipeline").info(f"Discovered {len(video_files)} video files")
    pipeline_logger.log_stage_end("File Discovery", 1, success=True, details=f"{len(video_files)} files found")

    # --- STAGE 2: Video Grouping ---
    pipeline_logger.log_stage_start("Video Grouping", 2)
    video_groups = group_videos(video_files, config['grouping']['max_time_diff_seconds'])

    # Calculate total clips
    total_clips = sum(len(group) for group in video_groups)

    print(f"📁 Found {len(video_files)} video files")
    print(f"📊 Grouped into {len(video_groups)} events")
    print(f"🎞  Total clips to process: {total_clips}\n")

    logging.getLogger("pipeline").info(f"Grouped {len(video_files)} files into {len(video_groups)} events")
    logging.getLogger("pipeline").info(f"Total clips to process: {total_clips}")
    pipeline_logger.log_stage_end("Video Grouping", 2, success=True,
                                  details=f"{len(video_groups)} groups, {total_clips} total clips")

    # --- STAGE 0: Video Validation & Repair (Preprocessing) ---
    print(f"{'='*80}")
    print("🔍 STAGE 0: Video Validation & Repair")
    print(f"{'='*80}\n")

    pipeline_logger.log_stage_start("Video Validation & Repair", 0)

    # Get repair configuration
    repair_config = config.get('transcription', {})
    repair_cache_dir = repair_config.get('repair_cache_dir', 'output/repaired_cache')
    always_repair = repair_config.get('always_repair', False)
    repair_strategy = repair_config.get('repair_strategy', 'fill')

    # Get all unique video paths from all groups
    all_video_paths = []
    for group in video_groups:
        all_video_paths.extend([v['full_path'] for v in group])
    all_video_paths = list(set(all_video_paths))  # Remove duplicates

    print(f"Validating {len(all_video_paths)} unique video files...")
    print(f"Cache directory: {repair_cache_dir}")
    print(f"Repair strategy: {repair_strategy}")
    print(f"Always repair: {'Yes' if always_repair else 'No (only when needed)'}\n")

    logging.getLogger("pipeline").info(f"Starting validation of {len(all_video_paths)} unique video files")
    logging.getLogger("pipeline").info(f"Repair cache: {repair_cache_dir}")
    logging.getLogger("pipeline").info(f"Repair strategy: {repair_strategy}")
    logging.getLogger("pipeline").info(f"Always repair: {always_repair}")

    # Initialize dashboard early to show validation progress
    dashboard = PipelineDashboard(
        total_videos=len(all_video_paths),
        total_groups=len(video_groups),
        total_clips=total_clips
    )

    # Start dashboard
    with dashboard:
        # Start validation stage
        dashboard.start_stage(StageKey.VALIDATION, len(all_video_paths))

        def update_progress(completed, total):
            dashboard.update_stage(StageKey.VALIDATION, completed, f"{completed}/{total} videos")

        # Preprocess all videos
        conc = (config.get('concurrency') or {})
        default_cpu = max(1, (os.cpu_count() or 2) - 1)
        validation_workers = int(conc.get('validation_workers', max(1, min(2, default_cpu))))

        path_mapping = preprocess_videos(
            all_video_paths,
            repair_cache_dir,
            strategy=repair_strategy,
            always_repair=always_repair,
            max_workers=validation_workers,
            progress_callback=update_progress
        )

        # Get and display statistics
        total_validated, repaired_count, original_count = get_validation_stats(path_mapping)
        dashboard.complete_stage(StageKey.VALIDATION, f"{repaired_count} repaired, {original_count} original")

    print("\n✓ Validation complete:")
    print(f"  • {total_validated} videos processed")
    print(f"  • {repaired_count} repaired/cached")
    print(f"  • {original_count} used as-is")
    print(f"\n{'='*80}\n")

    logging.getLogger("pipeline").info(f"Validation complete: {total_validated} processed, {repaired_count} repaired, {original_count} original")
    pipeline_logger.log_stage_end("Video Validation & Repair", 0, success=True,
                                  details=f"{repaired_count} repaired, {original_count} original")

    # Apply path mapping to all video groups
    for group in video_groups:
        for clip in group:
            original_path = clip['full_path']
            if original_path in path_mapping:
                clip['full_path'] = path_mapping[original_path]

    # Build group jobs
    group_jobs: list[tuple[str, list[str], dict[str, Any]]] = []
    group_outputs_dir = os.path.join(config['paths']['output_dir'], config['paths']['videos_dir'])
    transcripts_dir = os.path.join(config['paths']['output_dir'], config['paths']['transcripts_dir'])
    os.makedirs(group_outputs_dir, exist_ok=True)
    os.makedirs(transcripts_dir, exist_ok=True)

    for group in video_groups:
        group_name = _generate_group_name(group)
        video_paths = [v['full_path'] for v in group]
        group_jobs.append((group_name, video_paths, config))

    # Concurrency settings
    conc = (config.get('concurrency') or {})
    default_cpu = max(1, (os.cpu_count() or 2) - 1)
    transcribe_workers = int(conc.get('transcription_workers', max(1, min(2, default_cpu))))
    merge_workers = int(conc.get('merge_workers', max(1, min(3, default_cpu))))

    # Continue with full pipeline using dashboard
    with dashboard:
        # --- STAGE 3: Transcription & Diarization (concurrent per group) ---
        pipeline_logger.log_stage_start("Transcription & Diarization", 3,
                                       f"{len(group_jobs)} groups, {transcribe_workers} workers")
        stage3_results: dict[str, tuple[list[str], dict[str, Any] | None]] = {}
        completed_count = 0

        # Check for existing cached diarization results
        cache_dir = os.path.join(config['paths']['output_dir'], '.diarization_cache')
        cached_groups = set()
        if os.path.exists(cache_dir):
            cached_groups = {f.replace('_diarization.json', '') for f in os.listdir(cache_dir) if f.endswith('_diarization.json')}

        if cached_groups:
            logging.getLogger("pipeline").info(f"Found {len(cached_groups)} cached diarization results")

        # All groups will be processed (cache check happens in worker)
        jobs_to_process = group_jobs

        if cached_groups:
            dashboard.stages[StageKey.TRANSCRIPTION].details = f"Found {len(cached_groups)} cached results"

        dashboard.start_stage(StageKey.TRANSCRIPTION, len(group_jobs))

        if not jobs_to_process:
            dashboard.skip_stage(StageKey.TRANSCRIPTION, "All groups already transcribed")
        else:
            try:
                with multiprocessing.Manager() as manager:
                    _progress = manager.dict()

                    with ProcessPoolExecutor(max_workers=transcribe_workers) as executor:
                        # Submit all jobs with progress tracking
                        futures = {}
                        for _job_idx, job in enumerate(jobs_to_process):
                            group_name = job[0]
                            video_paths = job[1]

                            # Add substage for each group
                            dashboard.add_substage(StageKey.TRANSCRIPTION, group_name, len(video_paths))

                            task_id = f"transcription_{group_name}"
                            job_with_progress = (job[0], job[1], job[2], _progress, task_id)
                            futures[executor.submit(_transcribe_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while True:
                            n_finished = sum([future.done() for future in futures])
                            dashboard.update_stage(StageKey.TRANSCRIPTION, completed_count + n_finished,
                                                 f"Processing {n_finished}/{len(jobs_to_process)} groups")

                            # Update individual group progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict) and task_id.startswith('transcription_'):
                                    group_name = task_id.replace('transcription_', '')
                                    latest = update_data.get("progress", 0)
                                    dashboard.update_substage(StageKey.TRANSCRIPTION, group_name, latest)

                            if n_finished >= len(futures):
                                break

                            time.sleep(0.1)

                        # Collect results
                        for fut, (group_name, _task_id) in futures.items():
                            try:
                                gname, processed_video_paths, diarization_result = fut.result()
                                stage3_results[gname] = (processed_video_paths, diarization_result)
                                completed_count += 1
                                dashboard.remove_substage(StageKey.TRANSCRIPTION, gname)
                            except Exception as exc:
                                stage3_results[group_name] = ([], None)
                                completed_count += 1
                                dashboard.remove_substage(StageKey.TRANSCRIPTION, group_name)
                                logging.getLogger("pipeline").error(f"Transcription failed for {group_name}: {exc}")

                dashboard.complete_stage(StageKey.TRANSCRIPTION, f"{completed_count} groups processed")
                pipeline_logger.log_stage_end("Transcription & Diarization", 3, success=True,
                                            details=f"{completed_count} groups processed")

            except KeyboardInterrupt:
                logging.getLogger("pipeline").warning("SIGINT received: cancelling transcription workers...")
                pipeline_logger.log_stage_end("Transcription & Diarization", 3, success=False,
                                            details="Interrupted by user")
                raise

        # --- STAGE 4: Speaker Identification (serial; shared state) ---
        # Count groups with speech for progress tracking
        groups_with_speech = sum(1 for _, diar_result in stage3_results.values() if diar_result and diar_result.get('segments'))

        pipeline_logger.log_stage_start("Speaker Identification", 4,
                                       f"{groups_with_speech} groups with speech")

        dashboard.start_stage(StageKey.SPEAKER_ID, groups_with_speech if groups_with_speech > 0 else len(video_groups))
        speaker_identifier = SpeakerIdentifier(config)
        speaker_id_completed = 0

        for group in video_groups:
            group_name = _generate_group_name(group)
            processed_video_paths, diarization_result = stage3_results.get(group_name, ([], None))
            if diarization_result and diarization_result.get('segments'):
                speaker_identifier.process_transcript(
                    diarization_result['segments'], diarization_result.get('timeline', [])
                )
                final_transcript = speaker_identifier.substitute_names_in_transcript(
                    diarization_result['segments']
                )
                transcript_filename = f"{group_name}_transcript.txt"
                transcript_path = os.path.join(transcripts_dir, transcript_filename)
                with open(transcript_path, 'w') as f:
                    for entry in final_transcript:
                        speaker = entry.get('speaker', 'Unknown')
                        text = entry.get('text', '')
                        f.write(f"{speaker}: {text}\n")
                speaker_id_completed += 1
                dashboard.update_stage(StageKey.SPEAKER_ID, speaker_id_completed, f"Processed: {group_name}")
            else:
                speaker_id_completed += 1
                dashboard.update_stage(StageKey.SPEAKER_ID, speaker_id_completed, f"Skipped (no speech): {group_name}")

        dashboard.complete_stage(StageKey.SPEAKER_ID, f"{speaker_id_completed} groups processed")
        logging.getLogger("pipeline").info(f"Speaker identification complete: {speaker_id_completed} groups processed")
        pipeline_logger.log_stage_end("Speaker Identification", 4, success=True,
                                     details=f"{speaker_id_completed} groups processed")

        # --- STAGE 5: Video Merging/Composition (concurrent per group) ---
        merge_jobs: list[tuple[str, list[dict[str, Any]], str, dict[str, Any], dict[str, Any] | None]] = []

        # Check for existing merged videos to enable resume functionality
        existing_videos = set()
        if os.path.exists(group_outputs_dir):
            existing_videos = {f.replace('_merged.mp4', '') for f in os.listdir(group_outputs_dir) if f.endswith('_merged.mp4')}

        for group in video_groups:
            group_name = _generate_group_name(group)
            processed_video_paths, diarization_result = stage3_results.get(group_name, ([], None))

            # Skip if merged video already exists
            if group_name in existing_videos:
                continue

            # Create enriched clip dictionaries for composition
            video_clips_for_merge = []
            if processed_video_paths:
                # Map processed paths back to original clips to preserve metadata
                for i, clip in enumerate(group):
                    clip_dict = dict(clip)  # Create a copy
                    # Use processed path if available, otherwise use original
                    if i < len(processed_video_paths):
                        clip_dict['path'] = processed_video_paths[i]
                    video_clips_for_merge.append(clip_dict)
            else:
                # No processed paths, use original group clips
                video_clips_for_merge = [dict(clip) for clip in group]

            if not video_clips_for_merge:
                continue

            output_video_filename = f"{group_name}_merged.mp4"
            output_video_path = os.path.join(group_outputs_dir, output_video_filename)
            merge_jobs.append((group_name, video_clips_for_merge, output_video_path, config, diarization_result))

        pipeline_logger.log_stage_start("Video Merging/Composition", 5,
                                       f"{len(merge_jobs)} groups to merge, {merge_workers} workers")

        dashboard.start_stage(StageKey.MERGE, len(merge_jobs) + len(existing_videos))
        merge_success_count = len(existing_videos)  # Count existing videos as successes
        merge_completed = len(existing_videos)

        if len(existing_videos) > 0:
            dashboard.stages[StageKey.MERGE].details = f"Resuming: {len(existing_videos)} already complete"
            logging.getLogger("pipeline").info(f"Resuming merge: {len(existing_videos)} groups already merged")

        if not merge_jobs:
            dashboard.skip_stage(StageKey.MERGE, "All videos already merged")
        else:
            try:
                with multiprocessing.Manager() as manager:
                    _progress = manager.dict()

                    with ProcessPoolExecutor(max_workers=merge_workers) as executor:
                        # Submit all jobs with progress tracking
                        futures = {}
                        for job in merge_jobs:
                            group_name = job[0]
                            video_clips = job[1]  # List of clip dicts

                            # Add substage showing number of clips in this group
                            dashboard.add_substage(StageKey.MERGE, group_name, len(video_clips))

                            task_id = f"merge_{group_name}"
                            job_with_progress = (job[0], job[1], job[2], job[3], job[4], _progress, task_id)
                            futures[executor.submit(_merge_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while True:
                            n_finished = sum([future.done() for future in futures])
                            dashboard.update_stage(StageKey.MERGE, merge_completed + n_finished,
                                                 f"Merging {n_finished}/{len(merge_jobs)} groups")

                            # Update individual group progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict) and task_id.startswith('merge_'):
                                    group_name = task_id.replace('merge_', '')
                                    latest = update_data.get("progress", 0)
                                    total = update_data.get("total", 0)
                                    logging.getLogger("pipeline").debug(f"[MONITOR] Reading progress for {group_name}: {latest}/{total}")
                                    dashboard.update_substage(StageKey.MERGE, group_name, latest)

                            if n_finished >= len(futures):
                                break

                            time.sleep(0.1)

                        # Collect results
                        for fut, (group_name, _task_id) in futures.items():
                            try:
                                gname, ok, out_path = fut.result()
                                if ok:
                                    merge_success_count += 1
                                else:
                                    logging.getLogger("pipeline").warning(f"Merge failed for {gname}")
                                merge_completed += 1
                                dashboard.remove_substage(StageKey.MERGE, gname)
                            except Exception as exc:
                                merge_completed += 1
                                dashboard.remove_substage(StageKey.MERGE, group_name)
                                logging.getLogger("pipeline").error(f"Merge error for {group_name}: {exc}")

                dashboard.complete_stage(StageKey.MERGE, f"{merge_success_count} groups merged")
                logging.getLogger("pipeline").info(f"Merge complete: {merge_success_count}/{merge_completed} groups successful")
                pipeline_logger.log_stage_end("Video Merging/Composition", 5, success=True,
                                            details=f"{merge_success_count} groups merged")

            except KeyboardInterrupt:
                logging.getLogger("pipeline").warning("SIGINT received: cancelling merge workers...")
                pipeline_logger.log_stage_end("Video Merging/Composition", 5, success=False,
                                            details="Interrupted by user")
                raise

        # --- STAGE 6: Final Transcription of Merged Videos (whisper.cpp) ---
        # Discover merged videos (including those that already existed)
        merged_videos: list[tuple[str, str]] = []
        if os.path.exists(group_outputs_dir):
            for f in os.listdir(group_outputs_dir):
                if f.endswith('_merged.mp4'):
                    gname = f[:-len('_merged.mp4')]
                    merged_videos.append((gname, os.path.join(group_outputs_dir, f)))

        transcripts_final_dir = os.path.join(transcripts_dir, 'final')
        os.makedirs(transcripts_final_dir, exist_ok=True)

        pipeline_logger.log_stage_start("Final Video Transcription", 6,
                                       f"{len(merged_videos)} merged videos")

        dashboard.start_stage(StageKey.FINAL_TRANSCRIPTION, len(merged_videos))

        # Prepare SpeakerIdentifier and merge in profile names
        try:
            final_spk_identifier = SpeakerIdentifier(config)
            profile_name_map = _load_profile_name_map(config)
            if profile_name_map:
                final_spk_identifier.known_speakers_map.update(profile_name_map)
        except Exception as exc:
            final_spk_identifier = None
            logging.getLogger("pipeline").warning("SpeakerIdentifier unavailable for final transcripts; proceeding without naming: %s", exc)

        ft_completed = 0
        for group_name, video_path in merged_videos:
            # Add substage for this group
            dashboard.add_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 3)  # 3 steps: load, transcribe, write

            out_txt = os.path.join(transcripts_final_dir, f"{group_name}_final_transcript.txt")
            if os.path.exists(out_txt):
                ft_completed += 1
                dashboard.update_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 3)
                dashboard.update_stage(StageKey.FINAL_TRANSCRIPTION, ft_completed, f"Skip (exists): {group_name}")
                dashboard.remove_substage(StageKey.FINAL_TRANSCRIPTION, group_name)
                continue

            # Step 1: Extract start time from group_name (format: YYYYMMDD_HHMMSS_Cameras)
            # Example: 20251015_215513_Entry+Frontdoor
            dashboard.update_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 1)
            video_start_time = None
            try:
                parts = group_name.split('_')
                if len(parts) >= 2:
                    date_str = parts[0]  # YYYYMMDD
                    time_str = parts[1]  # HHMMSS
                    from datetime import datetime
                    video_start_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except Exception as e:
                logging.getLogger("pipeline").warning(f"Could not parse timestamp from group name {group_name}: {e}")

            # Step 2: Transcribe and diarize
            diarization_result = None
            try:
                diarization_result = process_audio_for_transcription([video_path], config)
                dashboard.update_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 2)
            except Exception as exc:
                logging.getLogger("pipeline").warning("Final transcription diarization failed for %s: %s", group_name, exc)
                dashboard.update_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 2)

            # Step 3: Format and write transcript
            lines: list[str] = []
            if diarization_result and diarization_result.get('segments'):
                segments_to_write = diarization_result['segments']
                if final_spk_identifier is not None:
                    try:
                        final_spk_identifier.process_transcript(segments_to_write, diarization_result.get('timeline', []))
                        segments_to_write = final_spk_identifier.substitute_names_in_transcript(segments_to_write)
                    except Exception as exc:
                        logging.getLogger("pipeline").warning("Speaker resolution failed for final transcript %s: %s", group_name, exc)

                # Format transcript like a script with timestamps
                lines.append(f"=== TRANSCRIPT: {group_name} ===")
                if video_start_time:
                    lines.append(f"Recording started: {video_start_time.strftime('%B %d, %Y at %I:%M:%S %p')}")
                lines.append("")

                for entry in segments_to_write:
                    spk = entry.get('speaker', 'Unknown')
                    text = entry.get('text', '')
                    start_seconds = entry.get('start', 0.0)

                    # Calculate wall-clock time if we have video start time
                    timestamp_str = ""
                    if video_start_time:
                        from datetime import timedelta
                        actual_time = video_start_time + timedelta(seconds=start_seconds)
                        timestamp_str = actual_time.strftime("%I:%M:%S %p")
                    else:
                        # Fallback: just show clip offset
                        mins = int(start_seconds // 60)
                        secs = int(start_seconds % 60)
                        timestamp_str = f"+{mins:02d}:{secs:02d}"

                    lines.append(f"[{timestamp_str}] {spk}: {text}")
            else:
                # Fallback plain whisper.cpp only (no diarization)
                lines.append(f"=== TRANSCRIPT: {group_name} ===")
                if video_start_time:
                    lines.append(f"Recording started: {video_start_time.strftime('%B %d, %Y at %I:%M:%S %p')}")
                lines.append("(No speaker diarization available)")
                lines.append("")

                try:
                    from blink_pipeline.media_utils import extract_audio_segment
                    from blink_pipeline.whisper_cpp_wrapper import WhisperCppWrapper
                    whisper_cfg = (config.get('transcription') or {}).get('whisper', {})
                    ggml = whisper_cfg.get('ggml_model_path')
                    binary = whisper_cfg.get('whisper_cpp_binary')
                    device = whisper_cfg.get('device', 'auto')
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=True) as tmp:
                        if not extract_audio_segment(video_path, tmp.name):
                            raise RuntimeError("Audio extraction failed")
                        wrapper = WhisperCppWrapper(model_path=ggml, whisper_cpp_binary=binary, device=device)
                        res = wrapper.transcribe(tmp.name, language=whisper_cfg.get('language'))

                        # Use segments with timestamps if available
                        segments = (res or {}).get('segments', [])
                        if segments:
                            for seg in segments:
                                start_seconds = seg.get('start', 0.0)
                                text = seg.get('text', '').strip()
                                if not text:
                                    continue

                                # Calculate wall-clock time
                                timestamp_str = ""
                                if video_start_time:
                                    from datetime import timedelta
                                    actual_time = video_start_time + timedelta(seconds=start_seconds)
                                    timestamp_str = actual_time.strftime("%I:%M:%S %p")
                                else:
                                    mins = int(start_seconds // 60)
                                    secs = int(start_seconds % 60)
                                    timestamp_str = f"+{mins:02d}:{secs:02d}"

                                lines.append(f"[{timestamp_str}] {text}")
                        else:
                            # Ultimate fallback: just the raw text
                            text = (res or {}).get('text', '').strip()
                            if text:
                                lines.append(text)
                            else:
                                lines.append("<transcription unavailable>")
                except Exception as exc:
                    logging.getLogger("pipeline").error("Plain transcription failed for final video %s: %s", group_name, exc)
                    lines.append("<transcription unavailable>")

            with open(out_txt, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
            ft_completed += 1
            dashboard.update_substage(StageKey.FINAL_TRANSCRIPTION, group_name, 3)
            dashboard.update_stage(StageKey.FINAL_TRANSCRIPTION, ft_completed, f"Done: {group_name}")
            dashboard.remove_substage(StageKey.FINAL_TRANSCRIPTION, group_name)

        dashboard.complete_stage(StageKey.FINAL_TRANSCRIPTION, f"{ft_completed} videos transcribed")
        pipeline_logger.log_stage_end("Final Video Transcription", 6, success=True,
                                      details=f"{ft_completed} videos")

        # --- STAGE 7: Speaker Profiles Export (editable) ---
        pipeline_logger.log_stage_start("Speaker Profiles Export", 7)
        dashboard.start_stage('speaker_profiles', 1)
        dashboard.add_substage('speaker_profiles', 'profiles.json', 1)
        spk_count, prof_path = _write_speaker_profiles(config)
        dashboard.update_substage('speaker_profiles', 'profiles.json', 1)
        dashboard.update_stage('speaker_profiles', 1, f"{spk_count} speakers")
        dashboard.remove_substage('speaker_profiles', 'profiles.json')
        dashboard.complete_stage('speaker_profiles', f"Profiles at {prof_path}")
        pipeline_logger.log_stage_end("Speaker Profiles Export", 7, success=True,
                                      details=f"{spk_count} speakers exported")

    # Dashboard context manager closes here, printing final summary
    dashboard.print_summary()

    # --- FINAL OUTPUT LOCATIONS ---
    output_dir = config['paths']['output_dir']
    transcripts_dir = os.path.join(output_dir, config['paths']['transcripts_dir'])
    videos_dir = os.path.join(output_dir, config['paths']['videos_dir'])
    speakers_dir = os.path.join(output_dir, config['paths']['speakers_dir'])

    print("📂 Output locations:")
    print(f"   • Transcripts: {transcripts_dir}")
    print(f"   • Videos: {videos_dir}")
    print(f"   • Speaker samples: {speakers_dir}")
    print(f"\n{'='*80}\n")

    logging.getLogger("pipeline").info("Pipeline execution completed successfully")
    logging.getLogger("pipeline").info(f"Output directories: transcripts={transcripts_dir}, videos={videos_dir}, speakers={speakers_dir}")
    pipeline_logger.log_session_end(success=True)

if __name__ == '__main__':
    main()
