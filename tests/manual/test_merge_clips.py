"""
Test script to verify merge substages show correct clip counts.
"""

import time
from src.pipeline_dashboard import PipelineDashboard

def main():
    """Test merge substages with varying clip counts."""
    print("Testing Merge Stage with Multiple Clips per Group...")
    print("=" * 80)

    dashboard = PipelineDashboard(
        total_videos=29,
        total_groups=10,
        total_clips=29
    )

    with dashboard:
        # Skip to merge stage quickly
        dashboard.start_stage('validation', 29)
        dashboard.update_stage('validation', 29)
        dashboard.complete_stage('validation', "Complete")

        dashboard.start_stage('transcription', 10)
        dashboard.update_stage('transcription', 10)
        dashboard.complete_stage('transcription', "Complete")

        dashboard.start_stage('speaker_id', 10)
        dashboard.update_stage('speaker_id', 10)
        dashboard.complete_stage('speaker_id', "Complete")

        # Merge stage with realistic clip counts
        print("\n🎬 Starting merge stage - watch the clip counts!")
        print("Each group should show X/Y where Y = number of clips in that group\n")

        dashboard.start_stage('merge', 10)

        # Groups with varying clip counts (like real video groups)
        groups_with_clips = [
            ('20251015_083743_Corner+Entry+Frontdoor', 3),
            ('20251015_104607_Entry', 2),
            ('20251015_105253_Entry', 4),
            ('20251015_105909_Entry', 1),
            ('20251015_110921_Entry+Frontdoor', 5),
            ('20251015_135502_Corner+Entry+Frontdoor', 2),
            ('20251015_162348_Entry+Frontdoor', 3),
            ('20251015_194929_Entry+Frontdoor', 4),
            ('20251015_215513_Entry+Frontdoor', 2),
            ('20251015_221057_Entry+Frontdoor', 3),
        ]

        for i, (group_name, num_clips) in enumerate(groups_with_clips):
            # Add substage with actual clip count
            dashboard.add_substage('merge', group_name, num_clips)

            # Simulate merging clips - update progress as we go
            for clip_num in range(num_clips):
                time.sleep(0.5)  # Slow enough to see progress
                dashboard.update_substage('merge', group_name, clip_num + 1)

            # Remove substage when done
            dashboard.remove_substage('merge', group_name)
            dashboard.update_stage('merge', i + 1, f"Merged {i + 1}/10 events")

        dashboard.complete_stage('merge', "10 groups merged")

    dashboard.print_summary()

    print("\n" + "=" * 80)
    print("✅ Test complete!")
    print("Did you see clip counts like 3/3, 2/4, 5/5 instead of just 0/1 or 1/1?")

if __name__ == '__main__':
    main()
