"""
Unit tests for blink_pipeline.composition.quality module.

Test coverage:
- FFmpegAudioQualityAnalyzer: FFmpeg analysis, metric parsing, scoring
- CachedQualityAnalyzer: Caching behavior, cache invalidation
- Edge cases: No audio, timeouts, malformed output, missing metrics

Author: Phase 1 test suite
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess
import json
import tempfile

from blink_pipeline.composition.quality import (
    FFmpegAudioQualityAnalyzer,
    CachedQualityAnalyzer,
)
from blink_pipeline.composition.models import QualityMetrics, QualityScore


class TestFFmpegAudioQualityAnalyzer:
    """Test FFmpegAudioQualityAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return FFmpegAudioQualityAnalyzer(timeout=30)

    @pytest.fixture
    def mock_ffmpeg_output(self):
        """Create realistic FFmpeg astats output."""
        return """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'video.mp4':
  Duration: 00:00:10.00, start: 0.000000, bitrate: 1000 kb/s
    Stream #0:0: Video: h264
    Stream #0:1: Audio: aac
[Parsed_astats_0 @ 0x123456] Channel: 1
[Parsed_astats_0 @ 0x123456] DC offset: 0.000123
[Parsed_astats_0 @ 0x123456] Min level: -0.500000
[Parsed_astats_0 @ 0x123456] Max level: 0.400000
[Parsed_astats_0 @ 0x123456] Min difference: 0.000000
[Parsed_astats_0 @ 0x123456] Max difference: 0.150000
[Parsed_astats_0 @ 0x123456] Mean difference: 0.010000
[Parsed_astats_0 @ 0x123456] RMS difference: 0.020000
[Parsed_astats_0 @ 0x123456] Peak level dB: -8.000000
[Parsed_astats_0 @ 0x123456] RMS level dB: -23.456789
[Parsed_astats_0 @ 0x123456] RMS peak dB: -15.000000
[Parsed_astats_0 @ 0x123456] RMS trough dB: -35.000000
[Parsed_astats_0 @ 0x123456] Crest factor: 6.000000
[Parsed_astats_0 @ 0x123456] Flat factor: 0.000000
[Parsed_astats_0 @ 0x123456] Peak count: 2.000000
[Parsed_astats_0 @ 0x123456] Noise floor dB: -60.000000
[Parsed_astats_0 @ 0x123456] Noise floor count: 0.000000
[Parsed_astats_0 @ 0x123456] RMS min dB: -45.000000
[Parsed_astats_0 @ 0x123456] Channel: 2
[Parsed_astats_0 @ 0x123456] RMS level dB: -25.123456
[Parsed_astats_0 @ 0x123456] Peak level dB: -10.000000
[Parsed_astats_0 @ 0x123456] RMS min dB: -50.000000
[Parsed_astats_0 @ 0x123456] Peak count: 3.000000
Output #0, null, to 'pipe:':
    Stream #0:0: Audio
frame=  240 fps=0.0 q=-0.0 Lsize=N/A time=00:00:10.00 bitrate=N/A speed= 250x
video:0kB audio:120kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
"""

    def test_analyzer_initialization(self, analyzer):
        """Test analyzer initializes with correct timeout."""
        assert analyzer.timeout == 30
        assert analyzer.logger is not None

    def test_analyze_no_audio(self, analyzer):
        """Test analyze returns minimal quality for videos without audio."""
        video_path = Path("/fake/video.mp4")

        metrics = analyzer.analyze(video_path, has_audio=False)

        assert metrics.rms_db == -60.0
        assert metrics.peak_db == -60.0
        assert metrics.noise_floor_db == -80.0
        assert metrics.clipping_rate == 0.0
        assert metrics.dynamic_range_db == 0.0
        assert metrics.snr_db == 0.0

    @patch('subprocess.run')
    def test_analyze_success(self, mock_run, analyzer, mock_ffmpeg_output):
        """Test successful audio analysis."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = mock_ffmpeg_output
        mock_run.return_value = mock_result

        video_path = Path("/fake/video.mp4")

        metrics = analyzer.analyze(video_path, has_audio=True)

        # Verify FFmpeg was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][0] == 'ffmpeg'
        assert '-af' in call_args[0][0]
        assert 'astats=metadata=1:reset=1' in call_args[0][0]

        # Verify metrics were parsed correctly
        # RMS: average of -23.456789 and -25.123456 = -24.290122
        assert -25.0 < metrics.rms_db < -24.0

        # Peak: max of -8.0 and -10.0 = -8.0
        assert metrics.peak_db == -8.0

        # RMS min: average of -45.0 and -50.0 = -47.5
        assert -48.0 < metrics.noise_floor_db < -47.0

        # Peak count: average of 2.0 and 3.0 = 2.5, rate = 2.5/5 = 0.5
        assert 0.4 < metrics.clipping_rate < 0.6

        # Dynamic range and SNR should be calculated
        assert metrics.dynamic_range_db is not None
        assert metrics.snr_db is not None

    @patch('subprocess.run')
    def test_analyze_ffmpeg_error(self, mock_run, analyzer):
        """Test analyze handles FFmpeg errors gracefully."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        video_path = Path("/fake/video.mp4")

        metrics = analyzer.analyze(video_path, has_audio=True)

        # Should return default metrics
        assert metrics.rms_db == -30.0
        assert metrics.peak_db == -10.0
        assert metrics.noise_floor_db == -50.0

    @patch('subprocess.run')
    def test_analyze_timeout(self, mock_run, analyzer):
        """Test analyze handles timeouts gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['ffmpeg'], timeout=30)

        video_path = Path("/fake/video.mp4")

        metrics = analyzer.analyze(video_path, has_audio=True)

        # Should return default metrics
        assert metrics.rms_db == -30.0
        assert metrics.peak_db == -10.0

    @patch('subprocess.run')
    def test_analyze_exception(self, mock_run, analyzer):
        """Test analyze handles general exceptions gracefully."""
        mock_run.side_effect = Exception("Something went wrong")

        video_path = Path("/fake/video.mp4")

        metrics = analyzer.analyze(video_path, has_audio=True)

        # Should return default metrics
        assert metrics.rms_db == -30.0

    def test_parse_astats_output_empty(self, analyzer):
        """Test parsing empty astats output."""
        metrics = analyzer._parse_astats_output("")

        # Should return default metrics
        assert metrics.rms_db == -30.0
        assert metrics.peak_db == -10.0

    def test_parse_astats_output_no_metrics(self, analyzer):
        """Test parsing output with no relevant metrics."""
        output = """
Some other output
Nothing useful here
"""
        metrics = analyzer._parse_astats_output(output)

        # Should return default metrics
        assert metrics.rms_db == -30.0

    def test_parse_astats_output_partial_metrics(self, analyzer):
        """Test parsing output with only some metrics."""
        output = """
[Parsed_astats_0 @ 0x123] RMS level dB: -20.0
[Parsed_astats_0 @ 0x123] Peak level dB: -5.0
"""
        metrics = analyzer._parse_astats_output(output)

        assert metrics.rms_db == -20.0
        assert metrics.peak_db == -5.0
        # Others should have defaults
        assert metrics.noise_floor_db is not None

    def test_extract_trailing_number_valid(self, analyzer):
        """Test extracting trailing number from string."""
        assert analyzer._extract_trailing_number("RMS level dB: -23.456") == -23.456
        assert analyzer._extract_trailing_number("Peak count: 5.0") == 5.0
        assert analyzer._extract_trailing_number("Value: 123") == 123.0

    def test_extract_trailing_number_multiple(self, analyzer):
        """Test extracting last number when multiple present."""
        result = analyzer._extract_trailing_number("Channel 1 RMS: -20.5")
        assert result == -20.5

    def test_extract_trailing_number_none(self, analyzer):
        """Test extracting number from string with no numbers."""
        assert analyzer._extract_trailing_number("No numbers here") is None

    def test_extract_trailing_number_invalid(self, analyzer):
        """Test extracting invalid number."""
        # Should return None for non-numeric strings
        assert analyzer._extract_trailing_number("") is None

    def test_score_good_quality(self, analyzer):
        """Test scoring with good quality metrics."""
        metrics = QualityMetrics(
            rms_db=-20.0,  # Perfect speech level
            peak_db=-6.0,   # Safe from clipping
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=30.0,
            snr_db=30.0
        )

        weights = {
            'rms': 0.35,
            'peak': 0.30,
            'noise': 0.25,
            'clipping': 0.10
        }

        score = analyzer.score(metrics, weights)

        assert 0.8 < score.overall < 1.0
        assert score.rms_score > 0.9
        assert score.peak_score > 0.5
        assert score.noise_score > 0.9
        assert score.clipping_score == 1.0

    def test_score_poor_quality(self, analyzer):
        """Test scoring with poor quality metrics."""
        metrics = QualityMetrics(
            rms_db=-60.0,  # Too quiet
            peak_db=-1.0,   # Clipping
            noise_floor_db=-40.0,  # High noise floor
            clipping_rate=1.0,  # Maximum clipping
            dynamic_range_db=5.0,  # Low dynamic range
            snr_db=5.0
        )

        weights = {
            'rms': 0.35,
            'peak': 0.30,
            'noise': 0.25,
            'clipping': 0.10
        }

        score = analyzer.score(metrics, weights)

        # Overall should be poor due to bad RMS, noise, and clipping
        assert 0.0 <= score.overall < 0.5
        assert score.rms_score < 0.5  # Too quiet
        # Peak score: 1.0 - max(0, (-1 + 3) / 6) = 1.0 - 0.333 = 0.667
        # This is actually OK since -1 dB is not terrible for peaks
        assert 0.5 < score.peak_score < 0.8
        assert score.noise_score < 0.5  # Bad dynamic range
        assert score.clipping_score == 0.0  # Maximum clipping penalty

    def test_score_no_weights(self, analyzer):
        """Test scoring with no weights falls back to RMS."""
        metrics = QualityMetrics(
            rms_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=30.0,
            snr_db=30.0
        )

        weights = {}

        score = analyzer.score(metrics, weights)

        # Should fall back to RMS score
        assert score.overall == score.rms_score

    def test_score_backward_compat_clip_weight(self, analyzer):
        """Test backward compatibility with 'clip' weight instead of 'clipping'."""
        metrics = QualityMetrics(
            rms_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-50.0,
            clipping_rate=0.5,
            dynamic_range_db=30.0,
            snr_db=30.0
        )

        # Use old 'clip' weight name
        weights = {
            'rms': 0.4,
            'peak': 0.3,
            'noise': 0.2,
            'clip': 0.1  # Old name
        }

        score = analyzer.score(metrics, weights)

        # Should work correctly
        assert 0.0 <= score.overall <= 1.0
        assert score.clipping_score == 0.5  # 1.0 - 0.5 clipping_rate

    def test_score_clamps_to_range(self, analyzer):
        """Test scoring clamps all scores to [0, 1]."""
        # Create extreme metrics that could produce out-of-range scores
        metrics = QualityMetrics(
            rms_db=-100.0,  # Extremely quiet
            peak_db=10.0,    # Way over 0 dBFS (shouldn't happen but test it)
            noise_floor_db=-20.0,  # Very high noise
            clipping_rate=2.0,  # Invalid (>1.0)
            dynamic_range_db=100.0,  # Huge range
            snr_db=-10.0  # Negative SNR
        )

        weights = {
            'rms': 0.25,
            'peak': 0.25,
            'noise': 0.25,
            'clipping': 0.25
        }

        score = analyzer.score(metrics, weights)

        # All scores should be clamped to [0, 1]
        assert 0.0 <= score.overall <= 1.0
        assert 0.0 <= score.rms_score <= 1.0
        assert 0.0 <= score.peak_score <= 1.0
        assert 0.0 <= score.noise_score <= 1.0
        assert 0.0 <= score.clipping_score <= 1.0

    def test_score_none_dynamic_range(self, analyzer):
        """Test scoring handles None dynamic_range_db."""
        metrics = QualityMetrics(
            rms_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=None,  # Not calculated
            snr_db=None
        )

        weights = {
            'rms': 0.4,
            'peak': 0.3,
            'noise': 0.2,
            'clipping': 0.1
        }

        score = analyzer.score(metrics, weights)

        # Should use default dynamic range of 20.0
        assert 0.0 <= score.overall <= 1.0
        assert 0.0 <= score.noise_score <= 1.0


class TestCachedQualityAnalyzer:
    """Test CachedQualityAnalyzer."""

    @pytest.fixture
    def base_analyzer(self):
        """Create base analyzer."""
        analyzer = Mock(spec=FFmpegAudioQualityAnalyzer)
        analyzer.analyze.return_value = QualityMetrics(
            rms_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=30.0,
            snr_db=30.0
        )
        analyzer.score.return_value = QualityScore(
            overall=0.85,
            metrics=analyzer.analyze.return_value,
            weights={'rms': 0.5, 'peak': 0.5},
            rms_score=0.9,
            peak_score=0.8,
            noise_score=0.85,
            clipping_score=1.0
        )
        return analyzer

    def test_cached_analyzer_no_cache_dir(self, base_analyzer):
        """Test cached analyzer without cache directory."""
        cached = CachedQualityAnalyzer(base_analyzer, cache_dir=None)

        video_path = Path("/fake/video.mp4")

        metrics = cached.analyze(video_path, has_audio=True)

        # Should call base analyzer directly
        base_analyzer.analyze.assert_called_once_with(video_path, True)
        assert metrics.rms_db == -20.0

    def test_cached_analyzer_cache_miss(self, base_analyzer):
        """Test cached analyzer on cache miss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create a fake video file for cache key generation
            video_path = cache_dir / "video.mp4"
            video_path.write_text("fake video")

            metrics = cached.analyze(video_path, has_audio=True)

            # Should call base analyzer
            base_analyzer.analyze.assert_called_once()
            assert metrics.rms_db == -20.0

            # Should create cache file
            cache_files = list(cache_dir.glob("*.json"))
            assert len(cache_files) == 1

    def test_cached_analyzer_cache_hit(self, base_analyzer):
        """Test cached analyzer on cache hit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create a fake video file
            video_path = cache_dir / "video.mp4"
            video_path.write_text("fake video")

            # First call - cache miss
            metrics1 = cached.analyze(video_path, has_audio=True)
            call_count_1 = base_analyzer.analyze.call_count

            # Second call - cache hit
            metrics2 = cached.analyze(video_path, has_audio=True)
            call_count_2 = base_analyzer.analyze.call_count

            # Should not call base analyzer again
            assert call_count_2 == call_count_1

            # Metrics should be identical
            assert metrics1.rms_db == metrics2.rms_db
            assert metrics1.peak_db == metrics2.peak_db

    def test_cached_analyzer_cache_corrupted(self, base_analyzer):
        """Test cached analyzer handles corrupted cache gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create a fake video file
            video_path = cache_dir / "video.mp4"
            video_path.write_text("fake video")

            # Create corrupted cache file
            cache_key = cached._get_cache_key(video_path)
            cache_file = cache_dir / f"{cache_key}.json"
            cache_file.write_text("corrupted json{")

            metrics = cached.analyze(video_path, has_audio=True)

            # Should fall back to base analyzer
            base_analyzer.analyze.assert_called_once()
            assert metrics.rms_db == -20.0

    def test_cached_analyzer_score_delegates(self, base_analyzer):
        """Test cached analyzer delegates score to base analyzer."""
        cached = CachedQualityAnalyzer(base_analyzer, cache_dir=None)

        metrics = QualityMetrics(
            rms_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-50.0,
            clipping_rate=0.0,
            dynamic_range_db=30.0,
            snr_db=30.0
        )
        weights = {'rms': 0.5, 'peak': 0.5}

        score = cached.score(metrics, weights)

        base_analyzer.score.assert_called_once_with(metrics, weights)
        assert score.overall == 0.85

    def test_cached_analyzer_cache_key_generation(self, base_analyzer):
        """Test cache key generation includes file stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create two files with same name but different content
            video1 = cache_dir / "video.mp4"
            video1.write_text("content1")
            key1 = cached._get_cache_key(video1)

            # Modify file
            video1.write_text("content1 modified")
            key2 = cached._get_cache_key(video1)

            # Keys should be different due to different mtime/size
            assert key1 != key2

    def test_cached_analyzer_cache_key_stat_failure(self, base_analyzer):
        """Test cache key generation handles stat failure."""
        cached = CachedQualityAnalyzer(base_analyzer, cache_dir=Path("/tmp"))

        # Non-existent file
        video_path = Path("/fake/nonexistent.mp4")
        key = cached._get_cache_key(video_path)

        # Should still generate a key based on filename
        assert isinstance(key, str)
        assert len(key) > 0

    def test_cached_analyzer_cache_write_failure(self, base_analyzer):
        """Test cached analyzer handles cache write failure gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create a fake video file
            video_path = cache_dir / "video.mp4"
            video_path.write_text("fake video")

            # Mock open to raise exception on write
            with patch('builtins.open', side_effect=PermissionError("Mock write failure")):
                # Should still return metrics even if caching fails
                metrics = cached.analyze(video_path, has_audio=True)
                assert metrics.rms_db == -20.0


class TestQualityIntegration:
    """Integration tests for quality module."""

    def test_full_pipeline_no_cache(self):
        """Test complete quality analysis pipeline without caching."""
        analyzer = FFmpegAudioQualityAnalyzer(timeout=30)

        # Test with no audio
        metrics = analyzer.analyze(Path("/fake/video.mp4"), has_audio=False)
        assert metrics.rms_db == -60.0

        weights = {'rms': 0.35, 'peak': 0.30, 'noise': 0.25, 'clipping': 0.10}
        score = analyzer.score(metrics, weights)

        assert 0.0 <= score.overall <= 1.0
        assert score.metrics == metrics
        assert score.weights == weights

    def test_full_pipeline_with_cache(self):
        """Test complete quality analysis pipeline with caching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            base_analyzer = FFmpegAudioQualityAnalyzer(timeout=30)
            analyzer = CachedQualityAnalyzer(base_analyzer, cache_dir=cache_dir)

            # Create fake video
            video_path = cache_dir / "test.mp4"
            video_path.write_text("fake video content")

            # First analysis
            metrics1 = analyzer.analyze(video_path, has_audio=False)

            # Second analysis (should hit cache)
            metrics2 = analyzer.analyze(video_path, has_audio=False)

            # Should be identical
            assert metrics1.rms_db == metrics2.rms_db
            assert metrics1.peak_db == metrics2.peak_db

            # Score both
            weights = {'rms': 0.5, 'peak': 0.5}
            score1 = analyzer.score(metrics1, weights)
            score2 = analyzer.score(metrics2, weights)

            assert score1.overall == score2.overall
