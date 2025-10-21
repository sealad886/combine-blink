#!/usr/bin/env python3
"""Quick test to demonstrate the Rich progress tracker with multiprocessing."""

import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from src.progress import ProgressTracker


def simulate_work(args):
    """Simulate work for a single task."""
    task_name, duration, progress_dict, task_id = args

    # Update progress incrementally
    for i in range(10):
        time.sleep(duration / 10)
        progress_dict[task_id] = {
            "progress": i + 1,
            "total": 10,
            "visible": True
        }

    # Mark complete and hide
    progress_dict[task_id] = {
        "progress": 10,
        "total": 10,
        "visible": False
    }

    return f"Completed: {task_name}"


def test_progress():
    """Simulate pipeline progress with Rich."""
    # Simulate processing 5 groups with 20 total clips
    progress = ProgressTracker(total_groups=5, total_clips=20)

    progress.console.print("\n[bold magenta]Testing Rich Progress Tracker[/bold magenta]\n")

    # Stage 3: Transcription (concurrent with multiprocessing)
    progress.start_stage(3, 5)

    with multiprocessing.Manager() as manager:
        _progress = manager.dict()

        with progress.create_progress() as rich_progress:
            overall_task = rich_progress.add_task(
                "[cyan]Overall transcription progress",
                total=5
            )

            tasks = []
            with ProcessPoolExecutor(max_workers=2) as executor:
                futures = {}
                for i in range(5):
                    task_name = f"Group_{i+1}"
                    task_id = rich_progress.add_task(
                        f"[green]{task_name}",
                        total=10,
                        visible=False
                    )
                    job = (task_name, 0.5, _progress, task_id)
                    futures[executor.submit(simulate_work, job)] = task_id

                # Monitor progress
                while (n_finished := sum([f.done() for f in futures])) < len(futures):
                    rich_progress.update(overall_task, completed=n_finished)

                    # Update from shared dict
                    for tid, update_data in _progress.items():
                        if isinstance(update_data, dict):
                            rich_progress.update(
                                tid,
                                completed=update_data.get("progress", 0),
                                total=update_data.get("total", 10),
                                visible=update_data.get("visible", False)
                            )
                    time.sleep(0.1)

                # Final update
                rich_progress.update(overall_task, completed=5)

    progress.complete_stage(3, 5)

    # Stage 4: Speaker ID (serial - simple progress)
    progress.start_stage(4, 5)
    with progress.create_progress() as rich_progress:
        speaker_task = rich_progress.add_task("[yellow]Processing speaker identification", total=5)
        for i in range(5):
            time.sleep(0.3)
            rich_progress.update(speaker_task, advance=1)
    progress.complete_stage(4, 5)

    # Stage 5: Merging (concurrent)
    progress.start_stage(5, 5)

    with multiprocessing.Manager() as manager:
        _progress = manager.dict()

        with progress.create_progress() as rich_progress:
            overall_task = rich_progress.add_task(
                "[cyan]Overall merge progress",
                total=5
            )

            with ProcessPoolExecutor(max_workers=3) as executor:
                futures = {}
                for i in range(5):
                    task_name = f"Video_{i+1}"
                    task_id = rich_progress.add_task(
                        f"[magenta]{task_name}",
                        total=10,
                        visible=False
                    )
                    job = (task_name, 0.4, _progress, task_id)
                    futures[executor.submit(simulate_work, job)] = task_id

                # Monitor progress
                while (n_finished := sum([f.done() for f in futures])) < len(futures):
                    rich_progress.update(overall_task, completed=n_finished)

                    # Update from shared dict
                    for tid, update_data in _progress.items():
                        if isinstance(update_data, dict):
                            rich_progress.update(
                                tid,
                                completed=update_data.get("progress", 0),
                                total=update_data.get("total", 10),
                                visible=update_data.get("visible", False)
                            )
                    time.sleep(0.1)

                # Final update
                rich_progress.update(overall_task, completed=5)

    progress.complete_stage(5, 5)

    # Final summary
    progress.print_summary(
        transcript_count=5,
        video_count=5,
        speaker_count=3
    )


if __name__ == "__main__":
    test_progress()
