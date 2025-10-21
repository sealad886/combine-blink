"""Progress tracking and display for the video processing pipeline using Rich."""

import time
from datetime import timedelta
from typing import Dict, Optional
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    SpinnerColumn,
)
from rich.console import Console


class ProgressTracker:
    """Track and display pipeline progress with Rich progress bars.

    This class provides a beautiful, multiprocessing-compatible progress display
    using the Rich library. It supports tracking multiple concurrent tasks and
    provides time estimates for completion.
    """

    def __init__(self, total_groups: int, total_clips: int):
        self.total_groups = total_groups
        self.total_clips = total_clips
        self.current_stage = 0
        self.stage_names = [
            "File Discovery",
            "Video Grouping",
            "Transcription & Diarization",
            "Speaker Identification",
            "Video Merging"
        ]

        # Rich console and progress instances
        self.console = Console()
        self.progress: Optional[Progress] = None

        # Task IDs for Rich progress tracking
        self.transcription_task = None
        self.speaker_id_task = None
        self.merge_task = None

        self.pipeline_start_time = time.time()

    def create_progress(self) -> Progress:
        """Create and return a Rich Progress instance with custom columns."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            TimeElapsedColumn(),
            console=self.console,
            refresh_per_second=2,  # Update display twice per second
        )

    def _format_time(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS or MM:SS."""
        if seconds < 0:
            return "calculating..."
        td = timedelta(seconds=int(seconds))
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def start_stage(self, stage_num: int, total_items: Optional[int] = None):
        """Mark the start of a pipeline stage."""
        self.current_stage = stage_num
        stage_name = self.stage_names[stage_num - 1]

        self.console.print(f"\n[bold cyan]{'='*80}")
        self.console.print(f"[bold green]🚀 STAGE {stage_num}/5: {stage_name.upper()}")
        self.console.print(f"[bold cyan]{'='*80}\n")

    def update_stage_progress(self, stage_num: int, completed: int, message: Optional[str] = None):
        """Update progress for the current stage.

        Note: When using multiprocessing, this method is called from the main process
        to update progress based on shared state from worker processes.
        """
        # Rich progress bars update automatically, so this is mostly a no-op
        # The actual updates happen via the shared progress dict in multiprocessing scenarios
        pass

    def complete_stage(self, stage_num: int, success_count: Optional[int] = None):
        """Mark a stage as complete."""
        stage_name = self.stage_names[stage_num - 1]
        self.console.print(f"\n[bold green]✅ {stage_name} completed!")
        if success_count is not None:
            self.console.print(f"[cyan]   Successfully processed: {success_count}")

    def print_summary(self, transcript_count: int, video_count: int, speaker_count: int):
        """Print final pipeline summary."""
        total_time = time.time() - self.pipeline_start_time

        self.console.print(f"\n[bold cyan]{'='*80}")
        self.console.print(f"[bold green]✨ PIPELINE COMPLETED SUCCESSFULLY! ✨")
        self.console.print(f"[bold cyan]{'='*80}\n")
        self.console.print("[bold yellow]📊 SUMMARY:")
        self.console.print(f"  [cyan]• Total time: {self._format_time(total_time)}")
        self.console.print(f"  [cyan]• Groups processed: {self.total_groups}")
        self.console.print(f"  [cyan]• Clips processed: {self.total_clips}")
        self.console.print(f"  [cyan]• Transcripts generated: {transcript_count}")
        self.console.print(f"  [cyan]• Videos merged: {video_count}")
        self.console.print(f"  [cyan]• Unique speakers identified: {speaker_count}")
        self.console.print(f"[bold cyan]{'='*80}\n")

    def log_group_queued(self, group_name: str, clip_count: int):
        """Log when a group is queued for processing."""
        self.console.print(f"  [yellow]📋 Queued: {group_name} ({clip_count} clips)")

    def log_group_completed(self, stage_num: int, group_name: str, success: bool = True):
        """Log when a group completes processing in a stage."""
        # Progress bars show overall progress, so we don't clutter output with individual completions
        pass

    def log_info(self, message: str):
        """Log an informational message."""
        self.console.print(f"  [blue]ℹ️  {message}")

    def log_warning(self, message: str):
        """Log a warning message."""
        self.console.print(f"  [yellow]⚠️  {message}")

    def log_error(self, message: str):
        """Log an error message."""
        self.console.print(f"  [red]❌ {message}")
