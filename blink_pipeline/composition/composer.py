"""
Modular Composer

Main entry point for modular multi-camera composition.
Orchestrates all modules to produce composed video output.

Classes:
- ModularComposer: Main composer class

Author: Phase 5 integration
Status: Production implementation
"""

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from ..media_utils import probe_media_info
from .alignment import CachedAlignmentEngine
from .audio import AudioProcessor
from .config import CompositionConfig
from .models import CameraClip, SpeechSegment
from .overlay import OverlayGenerator
from .quality import CachedQualityAnalyzer, FFmpegAudioQualityAnalyzer
from .rendering import MultiPassRenderer, SinglePassRenderer
from .timeline import (
    CameraClip as TimelineCameraClip,
    SpeechSegment as TimelineSpeechSegment,
    TimelineGenerator,
)

# Use a dedicated logger namespace for clearer pipeline logs
logger = logging.getLogger("pipeline.compose")


class ModularComposer:
    """Main multi-camera composition orchestrator."""

    def __init__(self, config_dict: Dict[str, Any]):
        """Initialize composer with configuration dictionary."""
        self.config = CompositionConfig.from_dict(config_dict.get('multi_camera_composition', {}))

        # Determine cache directory
        cache_base = config_dict.get('output', {}).get('audio_cache_dir', 'output/audio_cache')
        cache_dir = Path(cache_base) if cache_base else Path('output/audio_cache')

        # Initialize modules
        self.quality_analyzer = CachedQualityAnalyzer(
            FFmpegAudioQualityAnalyzer(),
            cache_dir=cache_dir / 'quality_analysis'
        )
        self.alignment_engine = CachedAlignmentEngine(
            self.config.audio_alignment
        )
        self.timeline_generator = TimelineGenerator(self.config)
        self.audio_processor = AudioProcessor(self.config.audio_cleanup, self.config.audio_mix)
        self.overlay_generator = OverlayGenerator(self.config.timestamp_overlay)

        # Select renderer
        if self.config.single_pass_filter_complex:
            self.renderer = SinglePassRenderer(self.config)
        else:
            self.renderer = MultiPassRenderer(self.config)

        # Store event metadata for overlay generation
        self._event_start: Optional[datetime] = None

    def compose_multi_camera_event(
        self,
        video_clips: List[Dict[str, Any]],
        output_video_path: str,
        speech_segments: Optional[List[Dict[str, Any]]] = None,
        speech_timeline: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> bool:
        """
        Compose multi-camera event into single video.

        Args:
            video_clips: List of clip dictionaries from discovery
            output_video_path: Output path for composed video
            speech_segments: Optional speech segments from diarization
            speech_timeline: Optional speech timeline
            progress_callback: Optional progress callback

        Returns:
            True if successful, False otherwise
        """
        total_steps = len(video_clips)

        def _report_progress(stage: str, pct: float):
            """Report progress using legacy (completed, total) format."""
            if progress_callback:
                try:
                    progress_callback(int(total_steps * pct), total_steps)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")

        try:
            # Context
            out_path = Path(output_video_path)
            group_name = out_path.stem.replace('_merged', '')

            # Log configuration snapshot
            logger.info(
                "Compose start | group=%s | clips=%d | renderer=%s | single_pass=%s | enable_composition=%s",
                group_name,
                len(video_clips),
                type(self.renderer).__name__,
                bool(self.config.single_pass_filter_complex),
                bool(self.config.enable_composition),
            )

            # Fallback: Single clip or composition disabled
            if len(video_clips) == 1 or not self.config.enable_composition:
                logger.info("Fallback path | reason=%s", "single-clip" if len(video_clips) == 1 else "composition-disabled")
                return self._simple_copy(video_clips, output_video_path)

            # Fallback: All clips from same camera
            cameras = set(clip['camera'] for clip in video_clips)
            if len(cameras) == 1:
                only_cam = list(cameras)[0]
                logger.info("Fallback path | reason=same-camera | camera=%s", only_cam)
                return self._sequential_merge(video_clips, output_video_path)

            logger.info("Timeline analysis starting | group=%s", group_name)
            _report_progress("Analysis", 0.0)

            # Step 1: Convert to modular types and analyze quality
            clips = self._convert_clips(video_clips)
            if not clips:
                logger.error("No valid clips after conversion")
                return False
            # Log a brief clip summary
            try:
                cams = sorted({c.camera_id for c in clips})
                durations = [round(float(c.duration or 0.0), 2) for c in clips]
                total_dur = round(sum(durations), 2)
                sample = ", ".join([f"{c.camera_id}:{round(c.duration or 0.0,1)}s" for c in clips[:5]])
                logger.info(
                    "Clips converted | group=%s | cameras=%s | n=%d | total_dur=%.2fs | sample=[%s]",
                    group_name, ",".join(cams), len(clips), total_dur, sample
                )
            except Exception:
                pass
            _report_progress("Analysis", 0.2)

            # Capture event start time for overlays
            self._event_start = min(c.start_time for c in clips)
            logger.info("Event start | %s", self._event_start.isoformat(timespec='seconds'))

            # Analyze audio quality
            logger.info("Audio quality analysis | clips=%d", len(clips))
            for clip in clips:
                if clip.quality_score is None:
                    metrics = self.quality_analyzer.analyze(clip.video_path)
                    # Compute weighted score
                    score = (
                        metrics.rms_db / -60.0 +
                        (metrics.peak_db + 3.0) / 3.0 +
                        1.0 - (abs(metrics.noise_floor_db) / 60.0)
                    ) / 3.0
                    from .models import QualityScore
                    clip.quality_score = QualityScore(
                        overall=max(0.0, min(1.0, score)),
                        metrics=metrics,
                        weights={}
                    )
            try:
                qs = [c.quality_score.overall for c in clips if c.quality_score]
                if qs:
                    logger.info("Quality summary | min=%.3f avg=%.3f max=%.3f", min(qs), sum(qs)/len(qs), max(qs))
            except Exception:
                pass
            _report_progress("Analysis", 0.3)

            # Step 2: Align clips if enabled
            if self.config.audio_alignment.enabled:
                logger.info("Audio alignment | enabled=True | ref=best-quality")
                camera_clips: Dict[str, List[Path]] = {}
                for clip in clips:
                    if clip.camera_id not in camera_clips:
                        camera_clips[clip.camera_id] = []
                    camera_clips[clip.camera_id].append(clip.video_path)

                ref_clip = max(clips, key=lambda c: c.quality_score.overall if c.quality_score else 0.0)
                alignment_results = self.alignment_engine.align_clips(
                    camera_clips=camera_clips,
                    ref_camera=ref_clip.camera_id
                )

                for result in alignment_results:
                    for clip in clips:
                        if clip.camera_id == result.camera:
                            clip.alignment_offset = result.offset_seconds
                            logger.info(
                                "Alignment | cam=%s | offset=%.4fs | confidence=%.3f",
                                clip.camera_id, result.offset_seconds, result.confidence
                            )
                _report_progress("Alignment", 0.4)

            # Step 3: Convert to timeline format
            timeline_clips = self._convert_to_timeline_clips(clips)
            timeline_speech = self._convert_speech(speech_segments) if speech_segments else None

            # Step 4: Generate timeline
            logger.info("Timeline generation | strategy=%s", self.config.switching_strategy)
            video_timeline, audio_timeline = self.timeline_generator.generate(
                timeline_clips,
                timeline_speech
            )
            try:
                total_v = round(sum(float(getattr(s, 'duration')) for s in video_timeline), 2)
            except Exception:
                total_v = 0.0
            logger.info(
                "Timeline ready | video_segments=%d | audio_segments=%d | total_video_duration=%.2fs",
                len(video_timeline), len(audio_timeline), total_v
            )
            # Log first few timeline segments for traceability
            for i, s in enumerate(video_timeline[:5]):
                logger.debug(
                    "Segment[%d] cam=%s src=[%.2f,%.2f] dst=[%.2f,%.2f] dur=%.2fs",
                    i,
                    getattr(s, 'camera_id', '?'),
                    float(getattr(s, 'source_start', 0.0)),
                    float(getattr(s, 'source_end', 0.0)),
                    float(getattr(s, 'start', 0.0)),
                    float(getattr(s, 'end', 0.0)),
                    float(getattr(s, 'duration', getattr(s, 'end', 0.0) - getattr(s, 'start', 0.0)))
                )
            _report_progress("Timeline", 0.5)

            # Step 5: Render composition
            logger.info("Rendering start | renderer=%s | out=%s", type(self.renderer).__name__, output_video_path)
            output_path = Path(output_video_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _report_progress("Rendering", 0.6)

            success = self._render_with_event_context(
                clips,
                video_timeline,
                output_path,
                lambda pct: _report_progress("Rendering", 0.6 + 0.4 * pct)
            )

            _report_progress("Complete", 1.0)

            # Verify output
            try:
                if success and output_path.exists():
                    size = output_path.stat().st_size
                    if size > 0:
                        logger.info("Compose complete | out=%s | size=%.2f MB", output_video_path, size / (1024*1024))
                    else:
                        logger.error("Compose produced empty file | out=%s", output_video_path)
                elif success and not output_path.exists():
                    logger.error("Compose reported success but file missing | out=%s", output_video_path)
            except Exception:
                pass

            return success

        except Exception as e:
            logger.error(f"Modular composition error: {e}", exc_info=True)
            if progress_callback:
                try:
                    progress_callback(total_steps, total_steps)
                except:
                    pass
            return False

    def _render_with_event_context(
        self,
        clips: List[CameraClip],
        video_timeline: list,
        output_path: Path,
        progress_callback: Optional[Callable[[float], None]]
    ) -> bool:
        """Render with event context injected for timestamp overlays."""
        class EventContextGenerator(OverlayGenerator):
            """Overlay generator that injects event_start context."""
            def __init__(self, base_generator: OverlayGenerator, event_start: datetime):
                super().__init__(base_generator.config)
                self._event_start = event_start

            def generate_ass_overlays(self, timeline, review_intervals):
                # Temporarily monkey-patch event_start
                old_start = getattr(self, '_event_start_backup', None)
                self._event_start_backup = old_start
                return super().generate_ass_overlays(timeline, review_intervals)

        # Create context-aware generator
        context_generator = EventContextGenerator(self.overlay_generator, self._event_start)

        # Temporarily swap generators
        original_generator = self.renderer.overlay_generator
        self.renderer.overlay_generator = context_generator

        try:
            logger.info(
                "Renderer dispatch | renderer=%s | segments=%d | out=%s",
                type(self.renderer).__name__, len(video_timeline), str(output_path)
            )
            return self.renderer.render(
                clips,
                video_timeline,
                output_path,
                progress_callback
            )
        finally:
            self.renderer.overlay_generator = original_generator

    def _simple_copy(self, video_clips: List[Dict[str, Any]], output_path: str) -> bool:
        """Simple copy for single clip or disabled composition."""
        try:
            input_path = video_clips[0]['file']
            logger.info(f"Copying {input_path} to {output_path}")
            cmd = [
                'ffmpeg', '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-i', input_path,
                '-c', 'copy', output_path
            ]
            logger.info("Simple copy | in=%s | out=%s", input_path, output_path)
            result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if result.returncode != 0:
                stderr_snippet = (result.stderr or '')[:1000]
                logger.error(f"ffmpeg copy failed: {stderr_snippet}")
                return False
            try:
                size = Path(output_path).stat().st_size
                logger.info("Simple copy complete | size=%.2f MB", size / (1024*1024))
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Simple copy failed: {e}")
            return False

    def _sequential_merge(self, video_clips: List[Dict[str, Any]], output_path: str) -> bool:
        """Sequential merge for same-camera clips."""
        try:
            from ..video import merge_video_clips
            clip_paths = [clip['file'] for clip in video_clips]
            logger.info(f"Merging {len(clip_paths)} same-camera clips")
            return merge_video_clips(
                clip_paths,
                output_path,
                crossfade_duration=self.config.audio_mix.crossfade_duration_seconds
            )
        except Exception as e:
            logger.error(f"Sequential merge failed: {e}")
            return False

    def _simple_concat(self, clips: List[Path], output_path: Path) -> bool:
        """Simple concatenation without fancy processing."""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for clip in clips:
                    f.write(f"file '{clip.absolute()}'\n")
                concat_file = f.name

            cmd = [
                'ffmpeg', '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'concat', '-safe', '0',
                '-i', concat_file, '-c', 'copy', str(output_path)
            ]
            logger.info("Simple concat | list=%s | out=%s | n=%d", concat_file, str(output_path), len(clips))
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
                if result.returncode != 0:
                    stderr_snippet = (result.stderr or '')[:1000]
                    logger.error(f"ffmpeg concat failed: {stderr_snippet}")
                    return False
                try:
                    size = Path(output_path).stat().st_size
                    logger.info("Simple concat complete | size=%.2f MB", size / (1024*1024))
                except Exception:
                    pass
                return True
            finally:
                try:
                    Path(concat_file).unlink()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Simple concat failed: {e}")
            return False

    def _convert_clips(self, video_clips: List[Dict[str, Any]]) -> List[CameraClip]:
        """Convert legacy clip format to CameraClip models."""
        clips = []
        for clip_dict in video_clips:
            try:
                # Support both 'file' and 'path' field names
                video_path = Path(clip_dict.get('file') or clip_dict.get('path'))

                # Try to probe media info (may be mocked in tests)
                try:
                    media_info = probe_media_info(video_path)
                    # Convert MagicMock to dict if needed (for tests)
                    if not isinstance(media_info, dict):
                        media_info = {
                            'duration': getattr(media_info, 'duration', 0.0),
                            'fps': getattr(media_info, 'fps', 30.0),
                            'width': getattr(media_info, 'width', 1920),
                            'height': getattr(media_info, 'height', 1080),
                        }
                except Exception as probe_err:
                    if video_path.exists():
                        raise  # Re-raise if file exists but probe fails
                    logger.warning(f"Clip not found: {video_path}")
                    continue

                # Get timestamps - use 'datetime' or 'start_time'
                start_time = clip_dict.get('start_time') or clip_dict.get('datetime', datetime.now())
                duration_secs = media_info.get('duration', 0.0)
                end_time = clip_dict.get('end_time') or (start_time + timedelta(seconds=duration_secs))

                clips.append(CameraClip(
                    video_path=video_path,
                    camera_id=clip_dict.get('camera', 'unknown'),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration_secs,
                    fps=media_info.get('fps', 30.0),
                    resolution=(
                        media_info.get('width', 1920),
                        media_info.get('height', 1080)
                    )
                ))
            except Exception as e:
                logger.error(f"Failed to convert clip {clip_dict.get('file')}: {e}")

        return clips

    def _convert_to_timeline_clips(self, clips: List[CameraClip]) -> List[TimelineCameraClip]:
        """Convert CameraClip to timeline-compatible format."""
        if not clips:
            return []

        # Compute event_start if not already set
        event_start = self._event_start if self._event_start is not None else min(c.start_time for c in clips)

        timeline_clips = []
        for clip in clips:
            relative_start = (clip.start_time - event_start).total_seconds()
            timeline_clips.append(TimelineCameraClip(
                path=str(clip.video_path),
                camera=clip.camera_id,
                camera_id=clip.camera_id,
                start_time=relative_start,
                duration=clip.duration,
                audio_quality_score=clip.quality_score.overall if clip.quality_score else 0.5,
                video_quality_score=clip.quality_score.overall if clip.quality_score else 0.5
            ))

        return timeline_clips

    def _convert_speech(self, speech_segments: List[Dict[str, Any]] | None) -> Optional[List[SpeechSegment]]:
        """Convert legacy speech format to SpeechSegment models."""
        if not speech_segments:
            return None

        segments = []
        for seg in speech_segments:
            try:
                segments.append(SpeechSegment(
                    speaker=seg.get('speaker', 'unknown'),
                    start=seg.get('start', 0.0),
                    end=seg.get('end', 0.0),
                    text=seg.get('text', '')
                ))
            except Exception as e:
                logger.error(f"Failed to convert speech segment: {e}")

        return segments if segments else None


__all__ = ['ModularComposer']
