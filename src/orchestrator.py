import os
import sys
import yaml
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time
from rich.progress import Progress, TaskID
from .discovery import discover_files
from .grouping import group_videos
from .media_validation import preprocess_videos, get_validation_stats
from .transcription import process_audio_for_transcription
from .identify_speaker import SpeakerIdentifier
from .video import merge_video_clips
from .multi_camera_composer import MultiCameraComposer
from .pipeline_dashboard import PipelineDashboard
from .logging_config import setup_pipeline_logging, configure_worker_logging

def load_config():
    """Loads the YAML configuration file."""
    try:
        with open('config.yaml', 'r') as f:
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


def _generate_group_name(group: List[Dict[str, Any]]) -> str:
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


def _transcribe_group_job(args: Tuple[str, List[str], Dict[str, Any], Any, Any]) -> Tuple[str, List[str], Optional[Dict[str, Any]]]:
    """Worker: run Stage 3 for a single group and return processed paths and diarization.

    Progress is tracked per-clip within the group, so progress bar shows:
    - Total: number of clips in the group
    - Progress: number of clips completed so far
    """
    group_name, video_paths, config, progress_dict, task_id = args

    # Configure worker logging (file-based, not console)
    log_dir = config.get('logging', {}).get('log_dir', 'logs')
    configure_worker_logging(log_dir)

    logger = logging.getLogger("pipeline.transcription")
    logger.info(f"Starting transcription for group: {group_name} ({len(video_paths)} clips)")

    # Initialize progress with actual number of clips to process
    total_clips = len(video_paths)
    progress_dict[task_id] = {"progress": 0, "total": total_clips, "visible": True}

    # Create a progress callback that updates the shared dict
    def progress_callback(completed_clips: int):
        progress_dict[task_id] = {"progress": completed_clips, "total": total_clips, "visible": True}

    # Pass progress callback to transcription
    try:
        diarization_result = process_audio_for_transcription(video_paths, config, progress_callback=progress_callback)
        logger.info(f"Transcription completed for group: {group_name}")
    except Exception as exc:
        logger.error(f"Transcription failed for group: {group_name}", exc_info=True)
        diarization_result = None

    # Derive processed (repaired/original) paths for later merging
    if diarization_result and 'timeline' in diarization_result:
        processed_video_paths: List[str] = [
            (entry.get('used_path') or entry.get('path') or entry.get('original_path'))
            for entry in diarization_result['timeline']
            if (entry.get('used_path') or entry.get('path') or entry.get('original_path'))
        ]
    else:
        processed_video_paths = list(video_paths)

    # Mark as complete
    progress_dict[task_id] = {"progress": total_clips, "total": total_clips, "visible": False}

    return group_name, processed_video_paths, diarization_result


def _merge_group_job(args: Tuple[str, List[Dict[str, Any]], str, Dict[str, Any], Optional[Dict[str, Any]], Any, Any]) -> Tuple[str, bool, str]:
    """Worker: run Stage 5 merge/composition for a single group."""
    group_name, video_clips, output_video_path, config, diarization_result, progress_dict, task_id = args

    # Configure worker logging (file-based, not console)
    log_dir = config.get('logging', {}).get('log_dir', 'logs')
    configure_worker_logging(log_dir)

    logger = logging.getLogger("pipeline.merge")
    logger.info(f"Starting merge for group: {group_name} ({len(video_clips)} clips)")

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
    def update_progress(completed: int, total: int):
        """Update progress in shared dict for dashboard."""
        progress_dict[task_id] = {
            "progress": completed, 
            "total": total, 
            "visible": True,
            "start_time": progress_dict[task_id].get("start_time", time.time())
        }
        logger.debug(f"Progress update for {group_name}: {completed}/{total}")

    # Use multi-camera composer if enabled and multiple cameras detected
    cameras = set(clip['camera'] for clip in video_clips)
    use_composer = (
        len(cameras) > 1 and
        config.get('multi_camera_composition', {}).get('enable_composition', True)
    )

    try:
        if use_composer:
            # Multi-camera composition
            logger.info(f"Using multi-camera composition for {group_name} ({len(cameras)} cameras)")
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
            logger.info(f"Using sequential merge for {group_name}")
            # Extract processed paths in chronological order
            sorted_clips = sorted(video_clips, key=lambda x: x['datetime'])
            processed_video_paths = [clip['path'] for clip in sorted_clips]
            crossfade = config.get('video_processing', {}).get('crossfade_duration', 0.5)
            ok = merge_video_clips(processed_video_paths, output_video_path, crossfade)

        if ok:
            logger.info(f"Merge completed successfully for group: {group_name}")
        else:
            logger.error(f"Merge failed for group: {group_name}")

    except Exception as exc:
        logger.error(f"Merge error for group: {group_name}", exc_info=True)
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
    logger = pipeline_logger.get_logger()

    # --- STAGE 1: File Discovery ---
    print(f"\n{'='*80}")
    print("🎬 BLINK VIDEO PROCESSING PIPELINE")
    print(f"{'='*80}\n")

    logger.info("Starting pipeline execution")
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
        logger.warning("No video files found in input directory")
        pipeline_logger.log_session_end(success=False)
        return

    logger.info(f"Discovered {len(video_files)} video files")
    pipeline_logger.log_stage_end("File Discovery", 1, success=True, details=f"{len(video_files)} files found")

    # --- STAGE 2: Video Grouping ---
    pipeline_logger.log_stage_start("Video Grouping", 2)
    video_groups = group_videos(video_files, config['grouping']['max_time_diff_seconds'])

    # Calculate total clips
    total_clips = sum(len(group) for group in video_groups)

    print(f"📁 Found {len(video_files)} video files")
    print(f"📊 Grouped into {len(video_groups)} events")
    print(f"🎞  Total clips to process: {total_clips}\n")

    logger.info(f"Grouped {len(video_files)} files into {len(video_groups)} events")
    logger.info(f"Total clips to process: {total_clips}")
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

    logger.info(f"Starting validation of {len(all_video_paths)} unique video files")
    logger.info(f"Repair cache: {repair_cache_dir}")
    logger.info(f"Repair strategy: {repair_strategy}")
    logger.info(f"Always repair: {always_repair}")

    # Initialize dashboard early to show validation progress
    dashboard = PipelineDashboard(
        total_videos=len(all_video_paths),
        total_groups=len(video_groups),
        total_clips=total_clips
    )

    # Start dashboard
    with dashboard:
        # Start validation stage
        dashboard.start_stage('validation', len(all_video_paths))

        def update_progress(completed, total):
            dashboard.update_stage('validation', completed, f"{completed}/{total} videos")

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
        dashboard.complete_stage('validation', f"{repaired_count} repaired, {original_count} original")

    print(f"\n✓ Validation complete:")
    print(f"  • {total_validated} videos processed")
    print(f"  • {repaired_count} repaired/cached")
    print(f"  • {original_count} used as-is")
    print(f"\n{'='*80}\n")

    logger.info(f"Validation complete: {total_validated} processed, {repaired_count} repaired, {original_count} original")
    pipeline_logger.log_stage_end("Video Validation & Repair", 0, success=True,
                                  details=f"{repaired_count} repaired, {original_count} original")

    # Apply path mapping to all video groups
    for group in video_groups:
        for clip in group:
            original_path = clip['full_path']
            if original_path in path_mapping:
                clip['full_path'] = path_mapping[original_path]

    # Build group jobs
    group_jobs: List[Tuple[str, List[str], Dict[str, Any]]] = []
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
        stage3_results: Dict[str, Tuple[List[str], Optional[Dict[str, Any]]]] = {}
        completed_count = 0

        # Check for existing transcripts to enable resume functionality
        existing_transcripts = set()
        if os.path.exists(transcripts_dir):
            existing_transcripts = {f.replace('_transcript.txt', '') for f in os.listdir(transcripts_dir) if f.endswith('_transcript.txt')}

        if existing_transcripts:
            logger.info(f"Resuming: {len(existing_transcripts)} groups already transcribed")

        # Filter out groups that already have transcripts
        jobs_to_process = []
        for job in group_jobs:
            group_name = job[0]
            if group_name in existing_transcripts:
                # For skipped groups, we still need processed paths for Stage 5
                video_paths = job[1]
                stage3_results[group_name] = (video_paths, None)
                completed_count += 1
            else:
                jobs_to_process.append(job)

        if len(existing_transcripts) > 0:
            dashboard.stages['transcription'].details = f"Resuming: {len(existing_transcripts)} already complete"

        dashboard.start_stage('transcription', len(group_jobs))

        if not jobs_to_process:
            dashboard.skip_stage('transcription', "All groups already transcribed")
        else:
            try:
                with multiprocessing.Manager() as manager:
                    _progress = manager.dict()

                    with ProcessPoolExecutor(max_workers=transcribe_workers) as executor:
                        # Submit all jobs with progress tracking
                        futures = {}
                        for job_idx, job in enumerate(jobs_to_process):
                            group_name = job[0]
                            video_paths = job[1]

                            # Add substage for each group
                            dashboard.add_substage('transcription', group_name, len(video_paths))

                            task_id = f"transcription_{group_name}"
                            job_with_progress = (job[0], job[1], job[2], _progress, task_id)
                            futures[executor.submit(_transcribe_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while True:
                            n_finished = sum([future.done() for future in futures])
                            dashboard.update_stage('transcription', completed_count + n_finished,
                                                 f"Processing {n_finished}/{len(jobs_to_process)} groups")

                            # Update individual group progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict) and task_id.startswith('transcription_'):
                                    group_name = task_id.replace('transcription_', '')
                                    latest = update_data.get("progress", 0)
                                    dashboard.update_substage('transcription', group_name, latest)

                            if n_finished >= len(futures):
                                break

                            time.sleep(0.1)

                        # Collect results
                        for fut, (group_name, task_id) in futures.items():
                            try:
                                gname, processed_video_paths, diarization_result = fut.result()
                                stage3_results[gname] = (processed_video_paths, diarization_result)
                                completed_count += 1
                                dashboard.remove_substage('transcription', gname)
                            except Exception as exc:
                                stage3_results[group_name] = ([], None)
                                completed_count += 1
                                dashboard.remove_substage('transcription', group_name)
                                logger.error(f"Transcription failed for {group_name}: {exc}")

                dashboard.complete_stage('transcription', f"{completed_count} groups processed")
                pipeline_logger.log_stage_end("Transcription & Diarization", 3, success=True,
                                            details=f"{completed_count} groups processed")

            except KeyboardInterrupt:
                logger.warning("SIGINT received: cancelling transcription workers...")
                pipeline_logger.log_stage_end("Transcription & Diarization", 3, success=False,
                                            details="Interrupted by user")
                raise

        # --- STAGE 4: Speaker Identification (serial; shared state) ---
        # Count groups with speech for progress tracking
        groups_with_speech = sum(1 for _, diar_result in stage3_results.values() if diar_result and diar_result.get('segments'))

        pipeline_logger.log_stage_start("Speaker Identification", 4,
                                       f"{groups_with_speech} groups with speech")

        dashboard.start_stage('speaker_id', groups_with_speech if groups_with_speech > 0 else len(video_groups))
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
                dashboard.update_stage('speaker_id', speaker_id_completed, f"Processed: {group_name}")
            else:
                speaker_id_completed += 1
                dashboard.update_stage('speaker_id', speaker_id_completed, f"Skipped (no speech): {group_name}")

        dashboard.complete_stage('speaker_id', f"{speaker_id_completed} groups processed")
        logger.info(f"Speaker identification complete: {speaker_id_completed} groups processed")
        pipeline_logger.log_stage_end("Speaker Identification", 4, success=True,
                                     details=f"{speaker_id_completed} groups processed")

        # --- STAGE 5: Video Merging/Composition (concurrent per group) ---
        merge_jobs: List[Tuple[str, List[Dict[str, Any]], str, Dict[str, Any], Optional[Dict[str, Any]]]] = []

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

        dashboard.start_stage('merge', len(merge_jobs) + len(existing_videos))
        merge_success_count = len(existing_videos)  # Count existing videos as successes
        merge_completed = len(existing_videos)

        if len(existing_videos) > 0:
            dashboard.stages['merge'].details = f"Resuming: {len(existing_videos)} already complete"
            logger.info(f"Resuming merge: {len(existing_videos)} groups already merged")

        if not merge_jobs:
            dashboard.skip_stage('merge', "All videos already merged")
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
                            dashboard.add_substage('merge', group_name, len(video_clips))

                            task_id = f"merge_{group_name}"
                            job_with_progress = (job[0], job[1], job[2], job[3], job[4], _progress, task_id)
                            futures[executor.submit(_merge_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while True:
                            n_finished = sum([future.done() for future in futures])
                            dashboard.update_stage('merge', merge_completed + n_finished,
                                                 f"Merging {n_finished}/{len(merge_jobs)} groups")

                            # Update individual group progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict) and task_id.startswith('merge_'):
                                    group_name = task_id.replace('merge_', '')
                                    latest = update_data.get("progress", 0)
                                    dashboard.update_substage('merge', group_name, latest)

                            if n_finished >= len(futures):
                                break

                            time.sleep(0.1)

                        # Collect results
                        for fut, (group_name, task_id) in futures.items():
                            try:
                                gname, ok, out_path = fut.result()
                                if ok:
                                    merge_success_count += 1
                                else:
                                    logger.warning(f"Merge failed for {gname}")
                                merge_completed += 1
                                dashboard.remove_substage('merge', gname)
                            except Exception as exc:
                                merge_completed += 1
                                dashboard.remove_substage('merge', group_name)
                                logger.error(f"Merge error for {group_name}: {exc}")

                dashboard.complete_stage('merge', f"{merge_success_count} groups merged")
                logger.info(f"Merge complete: {merge_success_count}/{merge_completed} groups successful")
                pipeline_logger.log_stage_end("Video Merging/Composition", 5, success=True,
                                            details=f"{merge_success_count} groups merged")

            except KeyboardInterrupt:
                logger.warning("SIGINT received: cancelling merge workers...")
                pipeline_logger.log_stage_end("Video Merging/Composition", 5, success=False,
                                            details="Interrupted by user")
                raise

    # Dashboard context manager closes here, printing final summary
    dashboard.print_summary()

    # --- FINAL OUTPUT LOCATIONS ---
    output_dir = config['paths']['output_dir']
    transcripts_dir = os.path.join(output_dir, config['paths']['transcripts_dir'])
    videos_dir = os.path.join(output_dir, config['paths']['videos_dir'])
    speakers_dir = os.path.join(output_dir, config['paths']['speakers_dir'])

    print(f"📂 Output locations:")
    print(f"   • Transcripts: {transcripts_dir}")
    print(f"   • Videos: {videos_dir}")
    print(f"   • Speaker samples: {speakers_dir}")
    print(f"\n{'='*80}\n")

    logger.info("Pipeline execution completed successfully")
    logger.info(f"Output directories: transcripts={transcripts_dir}, videos={videos_dir}, speakers={speakers_dir}")
    pipeline_logger.log_session_end(success=True)

if __name__ == '__main__':
    main()
