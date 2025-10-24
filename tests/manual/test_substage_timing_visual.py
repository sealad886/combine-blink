#!/usr/bin/env python3
"""
Visual test of substage timing with overlapping work.

This test shows multiple substages running concurrently to demonstrate
that each substage's timer starts independently when work begins on it.
"""

import time
import threading
from blink_pipeline.pipeline_dashboard import PipelineDashboard

def process_group(dashboard, group_name, num_clips, delay_per_clip):
    """Simulate processing a group with specified delay."""
    for i in range(1, num_clips + 1):
        dashboard.update_substage('transcription', group_name, i)
        time.sleep(delay_per_clip)
    # Don't remove - let them show in final display
    # dashboard.remove_substage('transcription', group_name)

def simulate_concurrent_work():
    """Simulate multiple groups being processed concurrently."""
    dashboard = PipelineDashboard(
        total_videos=15,
        total_groups=6,
        total_clips=30
    )

    with dashboard:
        # Start transcription stage
        dashboard.start_stage('transcription', 6)

        print("\n⏱️  Adding 6 groups to queue...")
        dashboard.add_substage('transcription', 'Office_3clips', 3)
        dashboard.add_substage('transcription', 'Kitchen_5clips', 5)
        dashboard.add_substage('transcription', 'Entry_2clips', 2)
        dashboard.add_substage('transcription', 'Garage_4clips', 4)
        dashboard.add_substage('transcription', 'Backyard_6clips', 6)
        dashboard.add_substage('transcription', 'Driveway_3clips', 3)

        print("\n⏳ Waiting 3 seconds before starting work (timers should NOT count this)...")
        time.sleep(3)

        print("\n▶️  Starting concurrent processing of groups...")
        print("    (Watch the dashboard - each timer starts when work begins)\n")

        # Process groups concurrently with different start times
        threads = []

        # Start first 3 groups immediately
        threads.append(threading.Thread(target=process_group, args=(dashboard, 'Office_3clips', 3, 0.5)))
        threads.append(threading.Thread(target=process_group, args=(dashboard, 'Kitchen_5clips', 5, 0.4)))
        threads.append(threading.Thread(target=process_group, args=(dashboard, 'Entry_2clips', 2, 0.6)))

        for t in threads[:3]:
            t.start()

        time.sleep(2)  # Let first batch run for 2 seconds

        # Start next 2 groups (delayed start)
        t4 = threading.Thread(target=process_group, args=(dashboard, 'Garage_4clips', 4, 0.5))
        t5 = threading.Thread(target=process_group, args=(dashboard, 'Backyard_6clips', 6, 0.3))
        threads.append(t4)
        threads.append(t5)
        t4.start()
        t5.start()

        time.sleep(1)  # Let them run for 1 second

        # Start last group (most delayed)
        t6 = threading.Thread(target=process_group, args=(dashboard, 'Driveway_3clips', 3, 0.6))
        threads.append(t6)
        t6.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        print("\n✅ All groups processed!")
        print("\nLook at the dashboard above:")
        print("  • Each substage shows its own elapsed time")
        print("  • Elapsed time = actual processing time (not queue time)")
        print("  • Groups that started later show less elapsed time")
        print("  • Groups that started earlier show more elapsed time")

        # Keep display visible for review
        time.sleep(5)

        dashboard.complete_stage('transcription', "6 groups processed")

if __name__ == '__main__':
    simulate_concurrent_work()
