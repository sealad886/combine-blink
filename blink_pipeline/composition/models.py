"""
Data Models Module

Core data models for multi-camera composition.
All models use type hints and dataclasses for clarity and validation.

Classes:
- CameraClip: Represents a video clip from a single camera
- QualityMetrics: Audio quality metrics from FFmpeg analysis
- QualityScore: Weighted quality score
- AlignmentResult: Audio alignment result with confidence
- SpeechSegment: Speech segment from diarization
- CompositionSegment: Timeline segment for composition

Author: Phase 3 implementation (data models)
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CameraClip:
    """Represents a video clip from a single camera."""

    camera_id: str
    video_path: Path
    start_time: datetime
    end_time: datetime
    duration: float  # seconds

    # Optional metadata
    resolution: tuple[int, int] | None = None  # (width, height)
    fps: float | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None

    # Computed properties (populated during processing)
    quality_score: Optional['QualityScore'] = None
    alignment_offset: float = 0.0  # seconds
    people_count: int | None = None


@dataclass
class QualityMetrics:
    """Audio quality metrics from FFmpeg analysis."""

    rms_db: float  # RMS level in dB
    peak_db: float  # Peak level in dB
    noise_floor_db: float  # Noise floor in dB
    clipping_rate: float  # Clipping rate (0.0-1.0)

    # Optional additional metrics
    dynamic_range_db: float | None = None
    snr_db: float | None = None  # Signal-to-noise ratio


@dataclass
class QualityScore:
    """Weighted quality score for a clip."""

    overall: float  # 0.0-1.0
    metrics: QualityMetrics
    weights: dict[str, float]

    # Component scores
    rms_score: float = 0.0
    peak_score: float = 0.0
    noise_score: float = 0.0
    clipping_score: float = 0.0


@dataclass
class AlignmentResult:
    """Audio alignment result with confidence."""

    offset_seconds: float  # Estimated offset
    confidence: float  # 0.0-1.0
    method: str  # 'gcc-phat'

    # Optional details
    correlation_peak: float | None = None
    drift_seconds_per_second: float | None = None
    num_windows: int = 1


@dataclass
class SpeechSegment:
    """Speech segment from diarization."""

    start: float  # seconds
    end: float  # seconds
    speaker: str
    text: str | None = None
    confidence: float | None = None


@dataclass
class CompositionSegment:
    """Timeline segment for composition."""

    camera_id: str
    start: float  # seconds (composition timeline)
    end: float  # seconds (composition timeline)
    source_start: float  # seconds (source clip timeline)
    source_end: float  # seconds (source clip timeline)
    audio_source: str  # Camera ID for audio

    # Optional context
    reason: str | None = None  # Why this camera was selected
    speech_active: bool = False
    people_count: int | None = None
    quality_score: float | None = None
    needs_review: bool = False  # Flag for manual review


# Type aliases for clarity
Timeline = list[CompositionSegment]
ClipCollection = list[CameraClip]


__all__ = [
    'CameraClip',
    'QualityMetrics',
    'QualityScore',
    'AlignmentResult',
    'SpeechSegment',
    'CompositionSegment',
    'Timeline',
    'ClipCollection',
]
