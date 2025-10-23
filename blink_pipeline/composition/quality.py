"""
Quality Analysis Module

Audio quality analysis and scoring using FFmpeg.
Provides Protocol for extensibility and caching for performance.

Classes:
- QualityAnalyzer: Protocol for quality analyzers
- FFmpegAudioQualityAnalyzer: Analyzes audio using FFmpeg astats
- CachedQualityAnalyzer: Wrapper with caching

Author: Phase 1 implementation
"""

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Protocol

from .models import QualityMetrics, QualityScore


class QualityAnalyzer(Protocol):
    """Protocol for audio quality analyzers."""

    def analyze(self, video_path: Path, has_audio: bool = True) -> QualityMetrics:
        """Analyze audio quality for a video file."""
        ...

    def score(self, metrics: QualityMetrics, weights: dict[str, float]) -> QualityScore:
        """Calculate weighted quality score from metrics."""
        ...


class FFmpegAudioQualityAnalyzer:
    """Analyzes audio quality using FFmpeg astats filter."""

    def __init__(self, timeout: int = 30):
        """
        Initialize analyzer.

        Args:
            timeout: Timeout in seconds for FFmpeg analysis
        """
        self.timeout = timeout

    def analyze(self, video_path: Path, has_audio: bool = True) -> QualityMetrics:
        """
        Analyze audio quality for a video file using FFmpeg astats.

        Args:
            video_path: Path to video file
            has_audio: Whether the video has an audio stream

        Returns:
            QualityMetrics with audio analysis results
        """
        if not has_audio:
            # Return minimal quality for videos without audio
            return QualityMetrics(
                rms_db=-60.0,
                peak_db=-60.0,
                noise_floor_db=-80.0,
                clipping_rate=0.0,
                dynamic_range_db=0.0,
                snr_db=0.0
            )

        try:
            command = [
                'ffmpeg',
                '-i', str(video_path),
                '-af', 'astats=metadata=1:reset=1',
                '-f', 'null',
                '-'
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            stderr_output = result.stderr or ''
            if result.returncode != 0 and not stderr_output:
                logging.getLogger(__name__).warning(
                    "Audio analysis failed for %s (code %s)",
                    video_path,
                    result.returncode,
                )
                # Return default moderate quality
                return self._default_metrics()

            # Parse FFmpeg astats output
            metrics = self._parse_astats_output(stderr_output)
            return metrics

        except subprocess.TimeoutExpired:
            logging.getLogger(__name__).warning(f"Audio analysis timed out for {video_path}")
            return self._default_metrics()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Could not analyze audio quality for {video_path}: {e}")
            return self._default_metrics()

    def _parse_astats_output(self, stderr: str) -> QualityMetrics:
        """
        Parse FFmpeg astats output to extract audio metrics.

        Args:
            stderr: FFmpeg stderr output containing astats data

        Returns:
            QualityMetrics with parsed values
        """
        rms_levels: list[float] = []
        rms_min_levels: list[float] = []
        peak_levels: list[float] = []
        peak_counts: list[float] = []

        for line in stderr.splitlines():
            line = line.strip()
            if not line:
                continue

            if 'RMS level dB' in line:
                number = self._extract_trailing_number(line)
                if number is not None:
                    rms_levels.append(number)
            elif 'RMS min dB' in line:
                number = self._extract_trailing_number(line)
                if number is not None:
                    rms_min_levels.append(number)
            elif 'Peak level dB' in line:
                number = self._extract_trailing_number(line)
                if number is not None:
                    peak_levels.append(number)
            elif 'Peak count' in line:
                number = self._extract_trailing_number(line)
                if number is not None:
                    peak_counts.append(number)

        if not rms_levels:
            return self._default_metrics()

        # Calculate averages
        avg_rms = sum(rms_levels) / len(rms_levels)
        max_peak = max(peak_levels) if peak_levels else -60.0
        avg_min_rms = sum(rms_min_levels) / len(rms_min_levels) if rms_min_levels else avg_rms - 20.0
        avg_peak_count = sum(peak_counts) / len(peak_counts) if peak_counts else 0.0

        # Calculate derived metrics
        dynamic_range = abs(avg_min_rms - avg_rms)
        noise_floor = avg_min_rms
        snr = avg_rms - noise_floor
        clipping_rate = min(1.0, avg_peak_count / 5.0)

        return QualityMetrics(
            rms_db=avg_rms,
            peak_db=max_peak,
            noise_floor_db=noise_floor,
            clipping_rate=clipping_rate,
            dynamic_range_db=dynamic_range,
            snr_db=snr
        )

    @staticmethod
    def _extract_trailing_number(value: str) -> float | None:
        """Extract the last number from a string."""
        matches = re.findall(r"-?\d+(?:\.\d+)?", value)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
            return None

    @staticmethod
    def _default_metrics() -> QualityMetrics:
        """Return default moderate quality metrics."""
        return QualityMetrics(
            rms_db=-30.0,
            peak_db=-10.0,
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=20.0,
            snr_db=20.0
        )

    def score(self, metrics: QualityMetrics, weights: dict[str, float]) -> QualityScore:
        """
        Calculate weighted quality score from metrics.

        Scoring strategy:
        - RMS: Good speech is around -20 dB, too loud or too quiet reduces score
        - Peak: Penalize clipping (peaks near 0 dBFS)
        - Noise: Reward good dynamic range (distance from noise floor)
        - Clipping: Penalize repeated peak hits

        Args:
            metrics: Audio quality metrics
            weights: Weights for each component (rms, peak, noise, clipping)

        Returns:
            QualityScore with overall score and component scores
        """
        # RMS score: Good speech around -20 dB
        if metrics.rms_db >= -20:
            # Too loud: penalize gradually
            rms_score = 1.0 - (metrics.rms_db + 20) / 40
        else:
            # Too quiet: penalize based on how far below -60 dB
            rms_score = max(0.0, (metrics.rms_db + 60) / 40)

        # Peak score: Penalize clipping (peaks approaching 0 dBFS)
        peak_score = 1.0 - max(0.0, (metrics.peak_db + 3.0) / 6.0)

        # Noise score: Reward good dynamic range
        dynamic_range = metrics.dynamic_range_db if metrics.dynamic_range_db is not None else 20.0
        noise_score = (dynamic_range - 10.0) / 20.0

        # Clipping score: Penalize repeated peak hits
        clipping_score = 1.0 - metrics.clipping_rate

        # Clamp all scores to [0, 1]
        rms_score = self._clamp(rms_score)
        peak_score = self._clamp(peak_score)
        noise_score = self._clamp(noise_score)
        clipping_score = self._clamp(clipping_score)

        # Calculate weighted overall score
        # Note: weights dict may have 'clip' instead of 'clipping' for backward compat
        w_rms = weights.get('rms', 0.0)
        w_peak = weights.get('peak', 0.0)
        w_noise = weights.get('noise', 0.0)
        w_clipping = weights.get('clipping', weights.get('clip', 0.0))

        overall = (
            rms_score * w_rms +
            peak_score * w_peak +
            noise_score * w_noise +
            clipping_score * w_clipping
        )

        # If no weights provided, fall back to RMS-driven scoring
        if overall == 0.0 and sum(weights.values()) == 0.0:
            overall = rms_score

        overall = self._clamp(overall)

        return QualityScore(
            overall=overall,
            metrics=metrics,
            weights=weights,
            rms_score=rms_score,
            peak_score=peak_score,
            noise_score=noise_score,
            clipping_score=clipping_score
        )

    @staticmethod
    def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Clamp value to [min_val, max_val]."""
        return max(min_val, min(max_val, value))


class CachedQualityAnalyzer:
    """Wrapper that caches quality analysis results to disk."""

    def __init__(self, analyzer: QualityAnalyzer, cache_dir: Path | None = None):
        """
        Initialize with base analyzer and optional cache directory.

        Args:
            analyzer: Base analyzer to use for uncached analysis
            cache_dir: Directory to store cached results (None disables caching)
        """
        self.analyzer = analyzer
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, video_path: Path, has_audio: bool = True) -> QualityMetrics:
        """
        Analyze with caching.

        Caches results by video file path + modification time hash.

        Args:
            video_path: Path to video file
            has_audio: Whether the video has an audio stream

        Returns:
            QualityMetrics from cache or fresh analysis
        """
        if not self.cache_dir:
            # No caching
            return self.analyzer.analyze(video_path, has_audio)

        # Check cache
        cache_key = self._get_cache_key(video_path)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                metrics = QualityMetrics(**data)
                logging.getLogger(__name__).debug(f"Loaded cached quality metrics for {video_path.name}")
                return metrics
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load cache for {video_path}: {e}")

        # Perform fresh analysis
        metrics = self.analyzer.analyze(video_path, has_audio)

        # Save to cache
        try:
            cache_data = {
                'rms_db': metrics.rms_db,
                'peak_db': metrics.peak_db,
                'noise_floor_db': metrics.noise_floor_db,
                'clipping_rate': metrics.clipping_rate,
                'dynamic_range_db': metrics.dynamic_range_db,
                'snr_db': metrics.snr_db
            }
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logging.getLogger(__name__).debug(f"Cached quality metrics for {video_path.name}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to cache quality for {video_path}: {e}")

        return metrics

    def score(self, metrics: QualityMetrics, weights: dict[str, float]) -> QualityScore:
        """Calculate score (delegates to base analyzer)."""
        return self.analyzer.score(metrics, weights)

    def _get_cache_key(self, video_path: Path) -> str:
        """
        Generate cache key from video path and modification time.

        Args:
            video_path: Path to video file

        Returns:
            Cache key (hex hash)
        """
        try:
            stat = video_path.stat()
            key_str = f"{video_path.name}_{stat.st_size}_{stat.st_mtime}"
        except Exception:
            # Fall back to just filename if stat fails
            key_str = video_path.name

        return hashlib.md5(key_str.encode()).hexdigest()


__all__ = ['QualityAnalyzer', 'FFmpegAudioQualityAnalyzer', 'CachedQualityAnalyzer']
