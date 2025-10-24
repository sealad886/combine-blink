
"""
Pipeline Dashboard - Unified Rich display for entire video processing pipeline.
IMPORTANT:
Use STAGE_DEFINITIONS as the single source of stage keys/names in orchestrator.py and elsewhere.
All progress, status, and timing for display should be managed via PipelineDashboard methods.
Do not duplicate stage keys/names or progress logic in orchestrator.py.
Provides a live-updating dashboard that shows:
Overall pipeline progress
Current stage with detailed progress
Statistics for each stage
Real-time status updates
"""

import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text

from .stages import StageKey, validate_stage_key


class StageStatus(Enum):
    """Status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    ERROR = "error"

@dataclass
class StageInfo:
    """Information about a pipeline stage."""
    name: str
    status: StageStatus = StageStatus.PENDING
    total: int = 0
    completed: int = 0
    start_time: float | None = None
    end_time: float | None = None
    details: str = ""
    substages: dict[str, dict[str, Any]] = field(default_factory=dict)


STAGE_DEFINITIONS = [
    (StageKey.VALIDATION, "Video Validation & Repair"),
    (StageKey.TRANSCRIPTION, "Transcription & Diarization"),
    (StageKey.SPEAKER_ID, "Speaker Identification"),
    (StageKey.MERGE, "Video Merging/Composition"),
    (StageKey.FINAL_TRANSCRIPTION, "Final Video Transcription"),
    (StageKey.SPEAKER_PROFILES, "Speaker Profiles Export"),
]


class PipelineDashboard:
    """
    Unified dashboard for the entire video processing pipeline.

    Manages Rich Live display with real-time updates for all stages.
    """

    def __init__(self, total_videos: int, total_groups: int, total_clips: int):
        """
        Initialize the pipeline dashboard.

        Args:
            total_videos: Total number of unique video files
            total_groups: Total number of video groups/events
            total_clips: Total number of clips across all groups
        """
        self.console = Console()
        self.total_videos = total_videos
        self.total_groups = total_groups
        self.total_clips = total_clips

        # Pipeline start time
        self.start_time = time.time()

        # Stage tracking (single source of truth from STAGE_DEFINITIONS)
        self.stages: dict[str, StageInfo] = {}
        for key, name in STAGE_DEFINITIONS:
            if key == StageKey.VALIDATION:
                total = total_videos
            elif key in (StageKey.TRANSCRIPTION, StageKey.SPEAKER_ID, StageKey.MERGE, StageKey.FINAL_TRANSCRIPTION):
                total = total_groups
            elif key == StageKey.SPEAKER_PROFILES:
                total = 0
            else:
                total = 0
            self.stages[key] = StageInfo(name, total=total)

        # Current stage
        self.current_stage: str | None = None

        # Live display
        self.live: Live | None = None
        self.layout: Layout | None = None

        # Progress bars
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
        )
        self.progress_tasks: dict[str, Any] = {}

    def set_stage_total(self, stage_key: str, total: int):
        """
        Set the total count for a stage (if it changes after initialization).

        Args:
            stage_key: Key of the stage
            total: New total count

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            self.stages[stage_key].total = total
            if stage_key in self.progress_tasks:
                self.progress.update(self.progress_tasks[stage_key], total=total)
            self.update()

    def error_stage(self, stage_key: str, details: str = ""):
        """
        Mark a stage as errored.

        Args:
            stage_key: Key of the stage
            details: Optional error details

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            stage = self.stages[stage_key]
            stage.status = StageStatus.ERROR
            stage.end_time = time.time()
            if details:
                stage.details = details
            self.update()

    def get_stage_timings(self) -> dict[str, tuple[float, float, float]]:
        """
        Get timing info for each stage.
        Returns a dict: {stage_key: (start_time, end_time, duration)}
        """
        timings = {}
        for key, stage in self.stages.items():
            start = stage.start_time or 0
            end = stage.end_time or 0
            duration = (end - start) if (end and start) else 0
            timings[key] = (start, end, duration)
        return timings

    def get_total_pipeline_time(self) -> float:
        """
        Get total pipeline elapsed time (seconds).
        """
        return time.time() - self.start_time

    def start(self):
        """Start the live dashboard display."""
        self.layout = Layout()

        # Create layout structure
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=7)
        )

        # Start live display
        self.live = Live(
            self.layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,
            auto_refresh=True,
        )
        self.live.start()

    def stop(self):
        """Stop the live dashboard display."""
        if self.live:
            self.live.stop()

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()

    def _make_header(self) -> Panel:
        """Create the dashboard header."""
        elapsed = time.time() - self.start_time
        elapsed_str = str(timedelta(seconds=int(elapsed)))

        # Calculate overall ETA based on completed stages
        completed_stages = sum(1 for s in self.stages.values() if s.status == StageStatus.COMPLETE)
        total_stages = len(self.stages)

        if completed_stages > 0 and completed_stages < total_stages:
            # Estimate based on average time per completed stage
            avg_time_per_stage = elapsed / completed_stages
            remaining_stages = total_stages - completed_stages
            estimated_remaining = avg_time_per_stage * remaining_stages
            remaining_str = str(timedelta(seconds=int(estimated_remaining)))
            time_info = f"Elapsed: {elapsed_str}  •  ETA: {remaining_str}"
        else:
            time_info = f"Elapsed: {elapsed_str}"

        header_text = Text()
        header_text.append("🎬 ", style="bold")
        header_text.append("BLINK VIDEO PROCESSING PIPELINE", style="bold cyan")
        header_text.append(f"  •  {time_info}", style="dim")

        return Panel(
            header_text,
            box=box.ROUNDED,
            style="cyan"
        )

    def _make_stages_table(self) -> Table:
        """Create the stages overview table."""
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")

        table.add_column("Stage", style="cyan", width=30)
        table.add_column("Status", width=12)
        table.add_column("Progress", width=40)
        table.add_column("Time", style="dim")

        for _stage_key, stage in self.stages.items():
            # Status indicator
            if stage.status == StageStatus.COMPLETE:
                status = Text("✓ Complete", style="green")
            elif stage.status == StageStatus.RUNNING:
                status = Text("⚙ Running", style="yellow")
            elif stage.status == StageStatus.SKIPPED:
                status = Text("⊘ Skipped", style="dim")
            elif stage.status == StageStatus.ERROR:
                status = Text("✗ Error", style="red")
            else:
                status = Text("○ Pending", style="dim")

            # Progress bar
            if stage.total > 0:
                bar_width = 30
                filled = int((stage.completed / stage.total) * bar_width)
                bar = "█" * filled + "░" * (bar_width - filled)
                progress_text = f"{bar} {stage.completed}/{stage.total}"
            else:
                progress_text = "—"

            # Time info with ETA
            if stage.end_time:
                # Stage completed
                duration = stage.end_time - (stage.start_time or 0)
                time_text = f"✓ {int(duration)}s"
            elif stage.start_time and stage.status == StageStatus.RUNNING:
                # Stage running - calculate ETA
                elapsed = time.time() - stage.start_time
                if stage.completed > 0 and stage.total > 0:
                    rate = stage.completed / elapsed
                    remaining_items = stage.total - stage.completed
                    eta_seconds = remaining_items / rate if rate > 0 else 0
                    time_text = f"{int(elapsed)}s • ETA {int(eta_seconds)}s"
                else:
                    time_text = f"{int(elapsed)}s elapsed"
            else:
                time_text = "—"

            # Add details if present
            if stage.details:
                time_text = f"{time_text} • {stage.details}"

            table.add_row(stage.name, status, progress_text, time_text)

        return table

    def _make_progress_panel(self) -> Panel:
        """Create the detailed progress panel for current stage."""
        if not self.current_stage:
            return Panel("No active stage", title="Current Progress", box=box.ROUNDED)

        stage = self.stages.get(self.current_stage)
        if not stage:
            return Panel("Unknown stage", title="Current Progress", box=box.ROUNDED)

        # Calculate ETA for title
        title = f"[bold cyan]{stage.name}[/bold cyan]"
        if stage.start_time and stage.status == StageStatus.RUNNING and stage.completed > 0 and stage.total > 0:
            elapsed = time.time() - stage.start_time
            rate = stage.completed / elapsed
            remaining_items = stage.total - stage.completed
            eta_seconds = remaining_items / rate if rate > 0 else 0
            title += f" • [dim]ETA: {str(timedelta(seconds=int(eta_seconds)))}[/dim]"
        if stage.details:
            title += f" - {stage.details}"

        # Create content based on stage type
        if stage.substages:
            # Show substage progress (e.g., multiple groups processing)
            table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
            table.add_column("Item", style="cyan", width=26)
            table.add_column("Progress", width=17)
            table.add_column("Time", width=10, style="dim", no_wrap=True)

            completed_table: list[tuple] = []

            for name, info in list(stage.substages.items())[:20]:  # Show up to 20
                if info.get('visible', True):
                    completed = info.get('progress', 0)
                    total = info.get('total', 1)

                    # Mini progress bar (compact)
                    bar_width = 10
                    filled = int((completed / total) * bar_width) if total > 0 else 0
                    bar = "█" * filled + "░" * (bar_width - filled)

                    # Calculate elapsed time (only if work has started)
                    start_time = info.get('start_time')
                    end_time = info.get('end_time')
                    if start_time is not None:
                        if end_time is not None:
                            # Completed - show final elapsed time
                            elapsed = int(end_time - start_time)
                            completed_table.append((
                                name[:40],
                                f"{bar} {completed}/{total}",
                                f"✓ {elapsed}s"
                            ))
                            continue
                        else:
                            # Still running - show current elapsed time
                            elapsed = int(time.time() - start_time)
                        time_text = f"{elapsed}s"
                    else:
                        time_text = "—"

                    table.add_row(
                        name[:40],
                        f"{bar} {completed}/{total}",
                        time_text
                    )
            if len(completed_table) > 0:
                table.add_section()
                for row in completed_table:
                    table.add_row(*row)
            if len(stage.substages) > 20:
                table.add_row(
                    f"... and {len(stage.substages) - 20} more",
                    "",
                    style="dim"
                )

            content = table
        else:
            # Show simple progress
            content = self.progress

        return Panel(content, title=title, box=box.ROUNDED)

    def _make_stats_panel(self) -> Panel:
        """Create the statistics panel."""
        stats = Table(box=None, show_header=False, padding=(0, 2))
        stats.add_column("Label", style="cyan")
        stats.add_column("Value", style="bold")

        stats.add_row("Total Videos:", str(self.total_videos))
        stats.add_row("Total Groups:", str(self.total_groups))
        stats.add_row("Total Clips:", str(self.total_clips))

        # Add stage completion counts
        completed_stages = sum(1 for s in self.stages.values() if s.status == StageStatus.COMPLETE)
        stats.add_row("Completed Stages:", f"{completed_stages}/{len(self.stages)}")

        return Panel(stats, title="Statistics", box=box.ROUNDED, padding=(0, 1))

    def update(self):
        """Update the dashboard display."""
        if not self.layout:
            return

        # Update header
        self.layout["header"].update(self._make_header())

        # Update main area - split between stages table and current progress
        main_layout = Layout()
        main_layout.split_row(
            Layout(self._make_stages_table(), name="stages", ratio=2),
            Layout(self._make_progress_panel(), name="current", ratio=1)
        )
        self.layout["main"].update(main_layout)

        # Update footer
        self.layout["footer"].update(self._make_stats_panel())

    def start_stage(self, stage_key: str, total: int | None = None):
        """
        Start a pipeline stage.

        Args:
            stage_key: Key of the stage (e.g., 'validation', 'transcription')
            total: Total items for this stage (optional, overrides initial value)

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            stage = self.stages[stage_key]
            stage.status = StageStatus.RUNNING
            stage.start_time = time.time()
            if total is not None:
                stage.total = total
            stage.completed = 0
            self.current_stage = stage_key

            # Create progress task
            if stage_key not in self.progress_tasks:
                self.progress_tasks[stage_key] = self.progress.add_task(
                    stage.name,
                    total=stage.total
                )

            self.update()

    def update_stage(self, stage_key: str, completed: int, details: str = ""):
        """
        Update stage progress.

        Args:
            stage_key: Key of the stage
            completed: Number of items completed
            details: Optional details text

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            stage = self.stages[stage_key]
            stage.completed = completed
            stage.details = details

            # Update progress task
            if stage_key in self.progress_tasks:
                self.progress.update(self.progress_tasks[stage_key], completed=completed)

            self.update()

    def complete_stage(self, stage_key: str, details: str = ""):
        """
        Mark a stage as complete.

        Args:
            stage_key: Key of the stage
            details: Optional completion details

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            stage = self.stages[stage_key]
            stage.status = StageStatus.COMPLETE
            stage.end_time = time.time()
            stage.completed = stage.total
            if details:
                stage.details = details

            self.update()

    def skip_stage(self, stage_key: str, reason: str = ""):
        """
        Mark a stage as skipped.

        Args:
            stage_key: Key of the stage
            reason: Reason for skipping

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            stage = self.stages[stage_key]
            stage.status = StageStatus.SKIPPED
            stage.details = reason
            self.update()

    def add_substage(self, stage_key: str, substage_name: str, total: int):
        """
        Add a substage for tracking individual items within a stage.

        Args:
            stage_key: Key of the parent stage
            substage_name: Name of the substage (e.g., group name)
            total: Total items in this substage

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            self.stages[stage_key].substages[substage_name] = {
                'progress': 0,
                'total': total,
                'visible': True,
                'start_time': None,  # Will be set on first progress update
                'end_time': None     # Will be set when completed
            }
            self.update()

    def update_substage(self, stage_key: str, substage_name: str, progress: int):
        """
        Update progress of a substage.

        Args:
            stage_key: Key of the parent stage
            substage_name: Name of the substage
            progress: Current progress

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            if substage_name in self.stages[stage_key].substages:
                substage = self.stages[stage_key].substages[substage_name]
                substage['progress'] = progress

                # Start timer on first progress update (when work actually begins)
                if substage['start_time'] is None and progress > 0:
                    substage['start_time'] = time.time()

                # Stop timer when completed
                if progress >= substage['total'] and substage['end_time'] is None:
                    substage['end_time'] = time.time()

                self.update()

    def remove_substage(self, stage_key: str, substage_name: str):
        """
        Remove a completed substage.

        Args:
            stage_key: Key of the parent stage
            substage_name: Name of the substage

        Raises:
            ValueError: If stage_key is not valid
        """
        validate_stage_key(stage_key)
        if stage_key in self.stages:
            if substage_name in self.stages[stage_key].substages:
                self.stages[stage_key].substages[substage_name]['visible'] = False
                self.update()

    def print_summary(self):
        """Print final pipeline summary."""
        total_time = time.time() - self.start_time

        self.console.print()
        self.console.print(Panel.fit(
            "[bold green]✓ Pipeline Complete![/bold green]",
            box=box.DOUBLE,
            border_style="green"
        ))

        summary_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        summary_table.add_column("Stage", style="cyan")
        summary_table.add_column("Duration", justify="right")
        summary_table.add_column("Items", justify="right")
        summary_table.add_column("Status", justify="center")

        for stage in self.stages.values():
            if stage.status == StageStatus.COMPLETE:
                duration = stage.end_time - stage.start_time if stage.end_time and stage.start_time else 0
                duration_str = str(timedelta(seconds=int(duration)))
                status = Text("✓", style="green")
            elif stage.status == StageStatus.SKIPPED:
                duration_str = "—"
                status = Text("⊘", style="dim")
            else:
                duration_str = "—"
                status = Text("○", style="dim")

            summary_table.add_row(
                stage.name,
                duration_str,
                f"{stage.completed}/{stage.total}",
                status
            )

        summary_table.add_row(
            "[bold]Total Pipeline Time[/bold]",
            f"[bold]{str(timedelta(seconds=int(total_time)))}[/bold]",
            "",
            ""
        )

        self.console.print(summary_table)
        self.console.print()
