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
from typing import Optional, Tuple, Dict, List


@dataclass
class CameraClip:
    """Represents a video clip from a single camera."""

    camera_id: str
    video_path: Path
    start_time: datetime
    end_time: datetime
    duration: float  # seconds

    # Optional metadata
    resolution: Optional[Tuple[int, int]] = None  # (width, height)
    fps: Optional[float] = None
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None

    # Computed properties (populated during processing)
    quality_score: Optional['QualityScore'] = None
    alignment_offset: float = 0.0  # seconds
    people_count: Optional[int] = None


@dataclass
class QualityMetrics:
    """Audio quality metrics from FFmpeg analysis."""

    rms_db: float  # RMS level in dB
    peak_db: float  # Peak level in dB
    noise_floor_db: float  # Noise floor in dB
    clipping_rate: float  # Clipping rate (0.0-1.0)

    # Optional additional metrics
    dynamic_range_db: Optional[float] = None
    snr_db: Optional[float] = None  # Signal-to-noise ratio


@dataclass
class QualityScore:
    """Weighted quality score for a clip."""

    overall: float  # 0.0-1.0
    metrics: QualityMetrics
    weights: Dict[str, float]

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
    correlation_peak: Optional[float] = None
    drift_seconds_per_second: Optional[float] = None
    num_windows: int = 1


@dataclass
class SpeechSegment:
    """Speech segment from diarization."""

    start: float  # seconds
    end: float  # seconds
    speaker: str
    text: Optional[str] = None
    confidence: Optional[float] = None


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
    reason: Optional[str] = None  # Why this camera was selected
    speech_active: bool = False
    people_count: Optional[int] = None
    quality_score: Optional[float] = None
    needs_review: bool = False  # Flag for manual review


# Type aliases for clarity
Timeline = List[CompositionSegment]
ClipCollection = List[CameraClip]


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
