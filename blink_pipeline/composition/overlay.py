"""
Overlay Generation Module

Timestamp overlays and review indicators for video composition.

This module centralizes overlay generation so both the legacy
`multi_camera_composer.py` and the modular renderers can use the
same implementation. It generates ASS subtitle files and returns
subtitles filter strings for ffmpeg.

Classes:
- OverlayGenerator: Main overlay generator

Author: Phase 4 implementation
Status: Production-ready for timestamp/review overlays
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import TimestampOverlayConfig
from .models import CompositionSegment


class OverlayGenerator:
    """Generate overlays (timestamps, review markers) as ASS subtitles.

    Notes
    - We prefer ASS subtitles over drawtext for precise, per-second timestamp
        rendering and easier styling/positioning.
    - By default, generated files are written to `output/overlays`.
    """

    def __init__(self, config: TimestampOverlayConfig, output_dir: str | Path | None = None):
            """Initialize generator with configuration.

            Parameters
            - config: TimestampOverlayConfig with font/margins/DST settings
            - output_dir: Directory to place generated ASS files (default: output/overlays)
            """
            self.config = config
            self.output_dir = Path(output_dir) if output_dir else Path('output/overlays')
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_timestamp_filter(self, base_time: datetime, duration: float) -> str:
        """Build ffmpeg subtitles filter for per-second timestamps.

        This generates an ASS file covering [0, duration) seconds with a
        per-second timestamp derived from `base_time` plus optional DST offset.

        Returns
        - A filter string like: "subtitles='path/to/generated.ass'"
        """
        ass_path = self.generate_ass_file(
            total_duration=duration,
            event_start=base_time,
            dst_offset_hours=self.config.dst_offset_hours,
            include_timestamp=self.config.enabled,
            review_segments=None,
        )
        return f"subtitles='{self._escape_path(ass_path)}'"

    def build_review_indicator_filter(self, segment: CompositionSegment) -> Optional[str]:
        """Build ffmpeg filter for review indicator if needed.

        For now, review indicators are emitted inside the same ASS file that
        contains timestamps, so this method returns None. Kept for API
        completeness and future expansion if we want separate overlays.
        """
        return None

    def format_timestamp(
        self,
        time: datetime,
        dst_offset_hours: int = 0
    ) -> str:
        """Format timestamp with DST offset."""
        adjusted_time = time + timedelta(hours=dst_offset_hours)
        return adjusted_time.strftime('%Y-%m-%d %H:%M:%S')

    # --- Public API used by composers ---
    def generate_ass_file(
        self,
        total_duration: float,
        event_start: Optional[datetime],
        dst_offset_hours: Optional[int] = None,
        include_timestamp: bool = True,
        review_segments: Iterable[Tuple[float, float]] | None = None,
        tmpdir: str | Path | None = None,
    ) -> str:
        """Generate an ASS subtitle file for timestamps and review indicators.

        Parameters
        - total_duration: Composition duration in seconds
        - event_start: Wall-clock base time for timestamps; if None or
                       include_timestamp is False, timestamp lines are omitted
        - dst_offset_hours: Optional override for DST hours (defaults to config)
        - include_timestamp: Whether to include per-second timestamp lines
        - review_segments: Iterable of (start, end) seconds for review banners
        - tmpdir: Optional directory to write file; default is `output/overlays`

        Returns
        - Absolute path to the generated .ass file
        """
        dst = self.config.dst_offset_hours if dst_offset_hours is None else int(dst_offset_hours)
        has_timestamp = bool(include_timestamp and event_start is not None and self.config.enabled)
        review_segments = list(review_segments or [])
        has_review = bool(review_segments)

        # If nothing to render, still return a path with minimal header to avoid conditional logic
        out_dir = Path(tmpdir) if tmpdir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        ass_path = out_dir / 'overlay.ass'

        lines: List[str] = []
        lines.append('[Script Info]')
        lines.append('ScriptType: v4.00+')
        lines.append('PlayResX: 1920')
        lines.append('PlayResY: 1080')
        lines.append('')
        lines.append('[V4+ Styles]')
        lines.append('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
                     'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, '
                     'Shadow, Alignment, MarginL, MarginR, MarginV, Encoding')

        if has_timestamp:
            # Bottom-right (alignment 3), semi-transparent outline for legibility
            lines.append(
                'Style: Overlay,'
                f'{self.config.font},{self.config.font_size},'
                '&H00FFFFFF,&H000000FF,&H55000000,&H00000000,'
                '0,0,0,0,100,100,0,0,1,2,0,3,'
                f'20,{self.config.margin_r},{self.config.margin_v},1'
            )

        if has_review:
            # Top-center (alignment 9) purple-ish outline to stand out
            review_font_size = max(6, int(self.config.font_size * 0.9))
            lines.append(
                'Style: ReviewIndicator,'
                f'{self.config.font},{review_font_size},'
                '&H00FFFFFF,&H000000FF,&H702151FF,&H00000000,'
                '0,0,0,0,100,100,0,0,1,2,0,9,'
                f'20,{self.config.margin_r},{max(10, self.config.margin_v)},1'
            )

        lines.append('')
        lines.append('[Events]')
        lines.append('Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text')

        def fmt_ass_time(seconds: float) -> str:
            seconds = max(0.0, float(seconds))
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            cs = int(round((seconds - int(seconds)) * 100))
            return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

        if has_timestamp:
            # Round duration to nearest second similar to legacy logic
            total_secs = int(max(0, int(total_duration + 0.5)))
            base = event_start + timedelta(hours=dst)  # type: ignore[operator]
            for t in range(0, total_secs):
                wall = base + timedelta(seconds=t)
                text = wall.strftime('%Y-%m-%d %H:%M:%S')
                start_ts = fmt_ass_time(t)
                end_ts = fmt_ass_time(t + 1)
                lines.append(f'Dialogue: 0,{start_ts},{end_ts},Overlay,,0000,0000,0000,,{text}')

        if has_review:
            for start, end in review_segments:
                clamped_start = max(0.0, min(total_duration, float(start)))
                clamped_end = max(clamped_start + 0.1, min(total_duration, float(end)))
                start_ts = fmt_ass_time(clamped_start)
                end_ts = fmt_ass_time(clamped_end)
                lines.append(
                    'Dialogue: 1,'
                    f'{start_ts},{end_ts},ReviewIndicator,,0000,0000,0000,,REVIEW ALT ANGLES'
                )

        ass_path.write_text('\n'.join(lines), encoding='utf-8')
        return str(ass_path)

    # --- Helpers ---
    @staticmethod
    def _escape_path(path: str | Path) -> str:
        """Escape path for ffmpeg subtitles filter usage."""
        s = str(path)
        return s.replace('\\', r'\\').replace("'", r"\'")


__all__ = ['OverlayGenerator']
