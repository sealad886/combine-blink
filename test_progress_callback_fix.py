#!/usr/bin/env python3
"""
Test to verify progress callback works with multiprocessing.
This tests the fix where callback is defined inside the worker.
"""
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor


def worker_with_callback_inside(progress_dict, task_id, total_items):
    """Worker that defines callback inside (should work)."""

    # Define callback inside worker - has access to progress_dict
    def update_progress(completed, total):
        progress_dict[task_id] = {
            "progress": completed,
            "total": total,
            "visible": True
        }
        print(f"[WORKER] Updated progress: {completed}/{total}")

    # Simulate work with progress updates
    for i in range(total_items + 1):
        update_progress(i, total_items)
        time.sleep(0.5)

    return f"Worker {task_id} completed"


def main():
    print("Testing progress callback with multiprocessing...\n")

    with multiprocessing.Manager() as manager:
        progress_dict = manager.dict()

        # Test with ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=2) as executor:
            # Submit two jobs
            future1 = executor.submit(worker_with_callback_inside, progress_dict, "task_1", 5)
            future2 = executor.submit(worker_with_callback_inside, progress_dict, "task_2", 5)

            # Monitor progress
            print("Monitoring progress from main process:\n")
            while not (future1.done() and future2.done()):
                # Read progress dict
                for task_id, data in progress_dict.items():
                    if isinstance(data, dict):
                        prog = data.get("progress", 0)
                        total = data.get("total", 0)
                        print(f"[MAIN] {task_id}: {prog}/{total}")

                time.sleep(0.3)

            # Get results
            result1 = future1.result()
            result2 = future2.result()

            print(f"\n✓ {result1}")
            print(f"✓ {result2}")

            # Final progress
            print("\nFinal progress:")
            for task_id, data in progress_dict.items():
                prog = data.get("progress", 0)
                total = data.get("total", 0)
                print(f"  {task_id}: {prog}/{total}")


if __name__ == '__main__':
    main()
