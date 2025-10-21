#!/usr/bin/env python3
"""
Quick test to verify dashboard progress callback mechanism.
"""
import time
import multiprocessing
from src.pipeline_dashboard import PipelineDashboard


def worker_with_progress(progress_dict, task_id):
    """Simulate a worker that reports progress."""
    total = 10
    for i in range(total + 1):
        progress_dict[task_id] = {
            "progress": i,
            "total": total,
            "visible": True,
            "start_time": time.time() if i == 0 else progress_dict[task_id].get("start_time", time.time())
        }
        time.sleep(0.5)


def main():
    """Test dashboard with progress updates."""
    print("Testing dashboard progress callback...")

    dashboard = PipelineDashboard(
        total_videos=10,
        total_groups=2,
        total_clips=20
    )

    with dashboard:
        # Start merge stage
        dashboard.start_stage('merge', 2)

        # Add substages for two groups
        dashboard.add_substage('merge', 'Group1', 10)
        dashboard.add_substage('merge', 'Group2', 10)

        # Start workers
        with multiprocessing.Manager() as manager:
            _progress = manager.dict()

            # Start two worker processes
            p1 = multiprocessing.Process(target=worker_with_progress, args=(_progress, 'merge_Group1'))
            p2 = multiprocessing.Process(target=worker_with_progress, args=(_progress, 'merge_Group2'))

            p1.start()
            time.sleep(1)  # Stagger start
            p2.start()

            # Monitor progress
            while p1.is_alive() or p2.is_alive():
                # Update dashboard from shared dict
                for task_id, update_data in _progress.items():
                    if isinstance(update_data, dict) and task_id.startswith('merge_'):
                        group_name = task_id.replace('merge_', '')
                        latest = update_data.get("progress", 0)
                        dashboard.update_substage('merge', group_name, latest)

                # Update stage overall progress
                completed_jobs = sum(1 for p in [p1, p2] if not p.is_alive())
                dashboard.update_stage('merge', completed_jobs, f"Processing {completed_jobs}/2 groups")

                time.sleep(0.1)

            p1.join()
            p2.join()

        dashboard.complete_stage('merge', "2 groups merged")

    dashboard.print_summary()
    print("\n✓ Test complete - check if progress bars updated correctly!")


if __name__ == '__main__':
    main()
