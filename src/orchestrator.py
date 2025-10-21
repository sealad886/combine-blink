import os
import yaml
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from rich.progress import Progress, TaskID
from .discovery import discover_files
from .grouping import group_videos
from .media_validation import preprocess_videos, get_validation_stats
from .transcription import process_audio_for_transcription
from .identify_speaker import SpeakerIdentifier
from .video import merge_video_clips
from .multi_camera_composer import MultiCameraComposer
from .progress import ProgressTracker

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    """Loads the YAML configuration file."""
    try:
        with open('config.yaml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error("Configuration file 'config.yaml' not found. Please create one.")
        exit(1)
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file: {e}")
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
    # Suppress verbose logging in workers
    logging.getLogger().setLevel(logging.ERROR)

    # Initialize progress with actual number of clips to process
    total_clips = len(video_paths)
    progress_dict[task_id] = {"progress": 0, "total": total_clips, "visible": True}

    # Create a progress callback that updates the shared dict
    def progress_callback(completed_clips: int):
        progress_dict[task_id] = {"progress": completed_clips, "total": total_clips, "visible": True}

    # Pass progress callback to transcription
    diarization_result = process_audio_for_transcription(video_paths, config, progress_callback=progress_callback)

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


def _merge_group_job(args: Tuple[str, List[Dict[str, Any]], str, Dict[str, Any], Any, Any]) -> Tuple[str, bool, str]:
    """Worker: run Stage 5 merge/composition for a single group."""
    group_name, video_clips, output_video_path, config, progress_dict, task_id = args
    # Suppress verbose logging in workers
    logging.getLogger().setLevel(logging.ERROR)

    # Update progress via shared dict
    progress_dict[task_id] = {"progress": 0, "total": 1, "visible": True}

    # Use multi-camera composer if enabled and multiple cameras detected
    cameras = set(clip['camera'] for clip in video_clips)
    use_composer = (
        len(cameras) > 1 and
        config.get('multi_camera_composition', {}).get('enable_composition', True)
    )

    if use_composer:
        # Multi-camera composition
        composer = MultiCameraComposer(config)
        ok = composer.compose_multi_camera_event(video_clips, output_video_path)
    else:
        # Fallback to sequential merge (single camera or composition disabled)
        # Extract processed paths in chronological order
        sorted_clips = sorted(video_clips, key=lambda x: x['datetime'])
        processed_video_paths = [clip['path'] for clip in sorted_clips]
        crossfade = config['video_processing']['crossfade_duration']
        ok = merge_video_clips(processed_video_paths, output_video_path, crossfade)

    # Mark as complete
    progress_dict[task_id] = {"progress": 1, "total": 1, "visible": False}

    return group_name, ok, output_video_path


def main():
    """Main function to orchestrate the video processing pipeline."""
    config = load_config()
    setup_directories(config)

    # --- STAGE 1: File Discovery ---
    print(f"\n{'='*80}")
    print("🎬 BLINK VIDEO PROCESSING PIPELINE")
    print(f"{'='*80}\n")

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
        return

    # --- STAGE 2: Video Grouping ---
    video_groups = group_videos(video_files, config['grouping']['max_time_diff_seconds'])

    # Calculate total clips
    total_clips = sum(len(group) for group in video_groups)

    print(f"📁 Found {len(video_files)} video files")
    print(f"📊 Grouped into {len(video_groups)} events")
    print(f"🎞  Total clips to process: {total_clips}\n")

    # --- STAGE 0: Video Validation & Repair (Preprocessing) ---
    print(f"{'='*80}")
    print("🔍 STAGE 0: Video Validation & Repair")
    print(f"{'='*80}\n")

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

    # Preprocess all videos with progress tracking
    from rich.progress import Progress as RichProgress, BarColumn, TextColumn, TimeRemainingColumn

    with RichProgress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("{task.completed}/{task.total} videos"),
        TimeRemainingColumn(),
    ) as rich_progress:
        validation_task = rich_progress.add_task("Validating videos", total=len(all_video_paths))

        def update_progress(completed, total):
            rich_progress.update(validation_task, completed=completed)

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
    print(f"\n✓ Validation complete:")
    print(f"  • {total_validated} videos processed")
    print(f"  • {repaired_count} repaired/cached")
    print(f"  • {original_count} used as-is")
    print(f"\n{'='*80}\n")

    # Apply path mapping to all video groups
    for group in video_groups:
        for clip in group:
            original_path = clip['full_path']
            if original_path in path_mapping:
                clip['full_path'] = path_mapping[original_path]

    # Initialize progress tracker
    progress = ProgressTracker(total_groups=len(video_groups), total_clips=total_clips)

    # Build group jobs
    group_jobs: List[Tuple[str, List[str], Dict[str, Any]]] = []
    group_outputs_dir = os.path.join(config['paths']['output_dir'], config['paths']['videos_dir'])
    transcripts_dir = os.path.join(config['paths']['output_dir'], config['paths']['transcripts_dir'])
    os.makedirs(group_outputs_dir, exist_ok=True)
    os.makedirs(transcripts_dir, exist_ok=True)

    for group in video_groups:
        group_name = _generate_group_name(group)
        video_paths = [v['full_path'] for v in group]
        progress.log_group_queued(group_name, len(video_paths))
        group_jobs.append((group_name, video_paths, config))

    # Concurrency settings
    conc = (config.get('concurrency') or {})
    default_cpu = max(1, (os.cpu_count() or 2) - 1)
    transcribe_workers = int(conc.get('transcription_workers', max(1, min(2, default_cpu))))
    merge_workers = int(conc.get('merge_workers', max(1, min(3, default_cpu))))

    # --- STAGE 3: Transcription & Diarization (concurrent per group) ---
    progress.start_stage(3, len(group_jobs))
    stage3_results: Dict[str, Tuple[List[str], Optional[Dict[str, Any]]]] = {}
    completed_count = 0

    # Check for existing transcripts to enable resume functionality
    existing_transcripts = set()
    if os.path.exists(transcripts_dir):
        existing_transcripts = {f.replace('_transcript.txt', '') for f in os.listdir(transcripts_dir) if f.endswith('_transcript.txt')}

    # Filter out groups that already have transcripts
    jobs_to_process = []
    for job in group_jobs:
        group_name = job[0]
        if group_name in existing_transcripts:
            progress.log_info(f"Skipping {group_name} - transcript already exists")
            # For skipped groups, we still need processed paths for Stage 5
            # We'll derive them from the original video paths
            video_paths = job[1]
            stage3_results[group_name] = (video_paths, None)
            completed_count += 1
        else:
            jobs_to_process.append(job)

    if jobs_to_process:
        progress.log_info(f"Processing {len(jobs_to_process)} groups (skipped {len(group_jobs) - len(jobs_to_process)} existing)")
    else:
        progress.log_info("All groups already transcribed - skipping Stage 3")
        progress.complete_stage(3, completed_count)

    if jobs_to_process:
        try:
            with multiprocessing.Manager() as manager:
                _progress = manager.dict()

                with progress.create_progress() as rich_progress:
                    overall_task = rich_progress.add_task(
                        "[cyan]Overall transcription progress",
                        total=len(jobs_to_process)
                    )

                    with ProcessPoolExecutor(max_workers=transcribe_workers) as executor:
                        # Submit all jobs with progress tracking
                        futures = {}
                        for job_idx, job in enumerate(jobs_to_process):
                            group_name = job[0]
                            task_id = rich_progress.add_task(
                                f"[green]{group_name}",
                                total=1,
                                visible=False
                            )
                            job_with_progress = (job[0], job[1], job[2], _progress, task_id)
                            futures[executor.submit(_transcribe_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while (n_finished := sum([future.done() for future in futures])) < len(futures):
                            rich_progress.update(overall_task, completed=n_finished)

                            # Update individual task progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict):
                                    latest = update_data.get("progress", 0)
                                    total = update_data.get("total", 1)
                                    visible = update_data.get("visible", False)
                                    rich_progress.update(
                                        task_id,
                                        completed=latest,
                                        total=total,
                                        visible=visible
                                    )

                        # Final update
                        rich_progress.update(overall_task, completed=len(futures))

                        # Collect results
                        for fut, (group_name, task_id) in futures.items():
                            try:
                                gname, processed_video_paths, diarization_result = fut.result()
                                stage3_results[gname] = (processed_video_paths, diarization_result)
                                completed_count += 1
                            except Exception as exc:
                                stage3_results[group_name] = ([], None)
                                completed_count += 1
                                progress.log_error(f"Transcription failed for {group_name}: {exc}")

            progress.complete_stage(3, completed_count)

        except KeyboardInterrupt:
            progress.log_warning("SIGINT received: cancelling transcription workers...")
            raise

    # --- STAGE 4: Speaker Identification (serial; shared state) ---
    # Count groups with speech for progress tracking
    groups_with_speech = sum(1 for _, diar_result in stage3_results.values() if diar_result and diar_result.get('segments'))

    progress.start_stage(4, groups_with_speech if groups_with_speech > 0 else len(video_groups))
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
                    f.write(f"[{_format_hms(entry['start'])}-{_format_hms(entry['end'])}] {entry['speaker']}: {entry['text']}\n")
            speaker_id_completed += 1
            progress.update_stage_progress(4, speaker_id_completed, f"Processed: {group_name}")
        else:
            speaker_id_completed += 1
            progress.update_stage_progress(4, speaker_id_completed, f"Skipped (no speech): {group_name}")

    progress.complete_stage(4, speaker_id_completed)

    # --- STAGE 5: Video Merging/Composition (concurrent per group) ---
    merge_jobs: List[Tuple[str, List[Dict[str, Any]], str, Dict[str, Any]]] = []

    # Check for existing merged videos to enable resume functionality
    existing_videos = set()
    if os.path.exists(group_outputs_dir):
        existing_videos = {f.replace('_merged.mp4', '') for f in os.listdir(group_outputs_dir) if f.endswith('_merged.mp4')}

    for group in video_groups:
        group_name = _generate_group_name(group)
        processed_video_paths, _ = stage3_results.get(group_name, ([], None))

        # Skip if merged video already exists
        if group_name in existing_videos:
            progress.log_info(f"Skipping {group_name} - merged video already exists")
            continue

        # Create enriched clip dictionaries for composition
        # If we have processed paths from stage 3 (repaired videos), use those
        # Otherwise use original paths from the group
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
        merge_jobs.append((group_name, video_clips_for_merge, output_video_path, config))

    progress.start_stage(5, len(merge_jobs) + len(existing_videos))
    merge_success_count = len(existing_videos)  # Count existing videos as successes
    merge_completed = len(existing_videos)

    if merge_jobs:
        progress.log_info(f"Processing {len(merge_jobs)} groups (skipped {len(existing_videos)} existing)")
    else:
        progress.log_info("All videos already merged - skipping Stage 5")
        progress.complete_stage(5, merge_success_count)

    if merge_jobs:
        try:
            with multiprocessing.Manager() as manager:
                _progress = manager.dict()

                with progress.create_progress() as rich_progress:
                    overall_task = rich_progress.add_task(
                        "[cyan]Overall merge progress",
                        total=len(merge_jobs)
                    )

                    with ProcessPoolExecutor(max_workers=merge_workers) as executor:
                        # Submit all jobs with progress tracking
                        futures = {}
                        for job in merge_jobs:
                            group_name = job[0]
                            task_id = rich_progress.add_task(
                                f"[magenta]{group_name}",
                                total=1,
                                visible=False
                            )
                            job_with_progress = (job[0], job[1], job[2], job[3], _progress, task_id)
                            futures[executor.submit(_merge_group_job, job_with_progress)] = (group_name, task_id)

                        # Monitor progress
                        while (n_finished := sum([future.done() for future in futures])) < len(futures):
                            rich_progress.update(overall_task, completed=n_finished)

                            # Update individual task progress from shared dict
                            for task_id, update_data in _progress.items():
                                if isinstance(update_data, dict):
                                    latest = update_data.get("progress", 0)
                                    total = update_data.get("total", 1)
                                    visible = update_data.get("visible", False)
                                    rich_progress.update(
                                        task_id,
                                        completed=latest,
                                        total=total,
                                        visible=visible
                                    )

                        # Final update
                        rich_progress.update(overall_task, completed=len(futures))

                        # Collect results
                        for fut, (group_name, task_id) in futures.items():
                            try:
                                gname, ok, out_path = fut.result()
                                merge_completed += 1
                                if ok:
                                    merge_success_count += 1
                                else:
                                    progress.log_warning(f"Merge failed for {gname}")
                            except Exception as exc:
                                merge_completed += 1
                                progress.log_error(f"Merge error for {group_name}: {exc}")

            progress.complete_stage(5, merge_success_count)

        except KeyboardInterrupt:
            progress.log_warning("SIGINT received: cancelling merge workers...")
            raise

    # --- FINAL SUMMARY ---
    output_dir = config['paths']['output_dir']
    transcripts_dir = os.path.join(output_dir, config['paths']['transcripts_dir'])
    videos_dir = os.path.join(output_dir, config['paths']['videos_dir'])
    speakers_dir = os.path.join(output_dir, config['paths']['speakers_dir'])

    transcript_files = [f for f in os.listdir(transcripts_dir) if f.endswith('.txt')] if os.path.exists(transcripts_dir) else []
    video_files = [f for f in os.listdir(videos_dir) if f.endswith('.mp4')] if os.path.exists(videos_dir) else []
    speaker_files = [f for f in os.listdir(speakers_dir) if f.endswith('.wav')] if os.path.exists(speakers_dir) else []

    progress.print_summary(len(transcript_files), len(video_files), len(speaker_files))

    print(f"📂 Output locations:")
    print(f"   • Transcripts: {transcripts_dir}")
    print(f"   • Videos: {videos_dir}")
    print(f"   • Speaker samples: {speakers_dir}")
    print(f"\n{'='*80}\n")

if __name__ == '__main__':
    main()
