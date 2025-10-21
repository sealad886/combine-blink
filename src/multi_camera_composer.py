"""
Multi-camera video composition module.

This module handles compositing videos from multiple cameras that recorded the same
event from different angles. It analyzes audio quality, selects optimal camera angles,
and creates a final composite video with the best footage and audio.
"""

import logging
import os
import subprocess
import tempfile
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import numpy as np
from .media_utils import probe_media_info


@dataclass
class CameraClip:
    """Represents a single camera clip with metadata."""
    path: str
    camera: str
    start_time: float  # Seconds since event start
    duration: float
    audio_quality_score: float = 0.0
    video_quality_score: float = 0.0


@dataclass
class CompositionSegment:
    """Represents a segment of the final composition."""
    camera: str
    clip_path: str
    start_time: float  # Time in the final composition
    duration: float
    source_start: float = 0.0  # Start time within the source clip


class MultiCameraComposer:
    """
    Composes multi-camera events into a single video with intelligent
    camera switching and optimal audio selection.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the composer with configuration.

        Args:
            config: Configuration dictionary containing composition settings.
        """
        self.config = config
        self.composition_config = config.get('multi_camera_composition', {})

        # Default composition settings
        self.switching_strategy = self.composition_config.get('switching_strategy', 'time_based')
        self.switching_interval = self.composition_config.get('switching_interval', 5.0)
        self.transition_style = self.composition_config.get('transition_style', 'cut')
        self.transition_duration = self.composition_config.get('transition_duration', 0.5)
        self.audio_source = self.composition_config.get('audio_source', 'best_quality')
        self.enable_composition = self.composition_config.get('enable_composition', True)
        # Determine if we actually need to analyze audio
        self._needs_audio_analysis = (
            self.audio_source == 'best_quality' or self.switching_strategy == 'audio_quality'
        )

        # Fine audio alignment configuration
        self.alignment_config = self.composition_config.get('audio_alignment', {
            'enabled': True,
            'max_shift_seconds': 1.5,
            'analysis_window_seconds': 12.0,
            'sample_rate': 16000,
            'bandpass': True,
            'highpass_hz': 300,
            'lowpass_hz': 3000,
        })
        self._alignment_enabled: bool = bool(self.alignment_config.get('enabled', True))
        self._alignment_max_shift: float = float(self.alignment_config.get('max_shift_seconds', 1.5))
        self._alignment_window: float = float(self.alignment_config.get('analysis_window_seconds', 12.0))
        self._alignment_sr: int = int(self.alignment_config.get('sample_rate', 16000))
        self._alignment_bandpass: bool = bool(self.alignment_config.get('bandpass', True))
        self._alignment_hp: int = int(self.alignment_config.get('highpass_hz', 300))
        self._alignment_lp: int = int(self.alignment_config.get('lowpass_hz', 3000))

        # Timestamp overlay configuration
        self.overlay_config = self.composition_config.get('timestamp_overlay', {
            'enabled': True,
            'font': 'Arial',
            'font_size': 24,
            'margin_v': 20,
            'margin_r': 20,
            'dst_offset_hours': 1,
        })
        self._overlay_enabled: bool = bool(self.overlay_config.get('enabled', True))
        self._overlay_font: str = str(self.overlay_config.get('font', 'Arial'))
        self._overlay_font_size: int = int(self.overlay_config.get('font_size', 24))
        self._overlay_margin_v: int = int(self.overlay_config.get('margin_v', 20))
        self._overlay_margin_r: int = int(self.overlay_config.get('margin_r', 20))
        self._overlay_dst_hours: int = int(self.overlay_config.get('dst_offset_hours', 1))

        # Event start (wall-clock) captured during analysis for overlay timing
        self._event_start: Optional[datetime] = None

    def compose_multi_camera_event(
        self,
        video_clips: List[Dict[str, Any]],
        output_path: str
    ) -> bool:
        """
        Create a composite video from multiple camera angles of the same event.

        Args:
            video_clips: List of video file dictionaries (with 'path', 'camera', 'datetime')
            output_path: Path where the final composite video will be saved

        Returns:
            bool: True if composition succeeded, False otherwise
        """
        # If only one clip or composition disabled, use simple merge
        if len(video_clips) == 1 or not self.enable_composition:
            logging.info(f"Single camera or composition disabled, using simple copy")
            return self._simple_copy(video_clips, output_path)

        # Check if all clips are from the same camera (shouldn't happen with new grouping)
        cameras = set(clip['camera'] for clip in video_clips)
        if len(cameras) == 1:
            logging.info(f"All clips from same camera ({cameras.pop()}), using sequential merge")
            return self._sequential_merge(video_clips, output_path)

        logging.info(f"Composing multi-camera event from {len(video_clips)} clips across {len(cameras)} cameras")

        try:
            # Step 1: Analyze audio quality for each clip and capture event start
            camera_clips = self._analyze_clips(video_clips)

            # Step 1b: Estimate per-camera fine alignment offsets and adjust clip start times
            if self._alignment_enabled:
                try:
                    offsets = self._estimate_alignment_offsets(camera_clips)
                    if offsets:
                        # Apply the same offset to all clips per camera
                        for cc in camera_clips:
                            adj = offsets.get(cc.camera, 0.0)
                            cc.start_time = max(0.0, cc.start_time + adj)
                        logging.info("Applied fine audio alignment offsets: %s", json.dumps(offsets))
                except Exception as e:
                    logging.warning("Audio alignment estimation failed, continuing without it: %s", e)

            # Step 2: Generate overlap-aligned timelines for video and audio across the full event
            video_timeline, audio_timeline = self._generate_aligned_timelines(camera_clips)

            # Step 3: Create the composite video using ffmpeg
            success = self._create_composite_video(video_timeline, audio_timeline, output_path)

            if success:
                logging.info(f"Successfully composed multi-camera event to {output_path}")

            return success

        except Exception as e:
            logging.error(f"Failed to compose multi-camera event: {e}")
            # Fallback to simple merge on error
            logging.info("Falling back to sequential merge")
            return self._sequential_merge(video_clips, output_path)

    def _analyze_clips(self, video_clips: List[Dict[str, Any]]) -> List[CameraClip]:
        """
        Analyze each clip for audio and video quality.

        Args:
            video_clips: List of video file dictionaries

        Returns:
            List of CameraClip objects with quality scores
        """
        camera_clips: List[CameraClip] = []

        # Find the earliest timestamp to establish event start time
        event_start = min(clip['datetime'] for clip in video_clips)
        self._event_start = event_start

        for clip in video_clips:
            # Get clip metadata
            media_info = probe_media_info(clip['path'])

            if media_info.duration <= 0:
                logging.warning(f"Skipping clip with invalid duration: {clip['path']}")
                continue

            # Calculate relative start time
            start_offset = (clip['datetime'] - event_start).total_seconds()

            # Analyze audio quality only if needed for strategy
            if self._needs_audio_analysis:
                audio_score = self._calculate_audio_quality(clip['path'], media_info)
            else:
                # Use neutral default score when not needed
                audio_score = 0.5

            # Video quality can be added later (for now use placeholder)
            video_score = 1.0

            camera_clips.append(CameraClip(
                path=clip['path'],
                camera=clip['camera'],
                start_time=start_offset,
                duration=media_info.duration,
                audio_quality_score=audio_score,
                video_quality_score=video_score
            ))

        return sorted(camera_clips, key=lambda x: x.start_time)

    def _estimate_alignment_offsets(self, camera_clips: List[CameraClip]) -> Dict[str, float]:
        """
        Estimate per-camera fine alignment offsets using cross-correlation on audio.

        Returns a mapping camera -> offset_seconds where positive means the camera lags (behind)
        the reference and should be shifted later (we add to start_time).
        """
        if not camera_clips:
            return {}

        # Use the best audio clip as reference
        ref_clip = max(camera_clips, key=lambda x: x.audio_quality_score)
        ref_cam = ref_clip.camera

        # Build per-camera representative clip overlapping with reference
        offsets: Dict[str, float] = {ref_cam: 0.0}

        for cam in sorted({c.camera for c in camera_clips}):
            if cam == ref_cam:
                continue
            # choose the first clip from this camera that overlaps ref_clip by at least 5 seconds
            candidates = [c for c in camera_clips if c.camera == cam]
            best = None
            best_overlap = 0.0
            ref_start = ref_clip.start_time
            ref_end = ref_clip.start_time + ref_clip.duration
            for c in candidates:
                c_start = c.start_time
                c_end = c.start_time + c.duration
                overlap = max(0.0, min(ref_end, c_end) - max(ref_start, c_start))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = c
            if not best or best_overlap < 5.0:
                # Not enough overlap to estimate reliably
                offsets[cam] = 0.0
                continue

            # Define analysis window within the overlap
            start_in_event = max(ref_start, best.start_time)
            # Center the window at the start of overlap to avoid clip ends
            win = min(self._alignment_window, best_overlap)
            if win <= 0.0:
                offsets[cam] = 0.0
                continue

            # Compute source positions
            ref_src_start = max(0.0, start_in_event - ref_clip.start_time)
            cam_src_start = max(0.0, start_in_event - best.start_time)

            # Extract audio samples
            ref_samples = self._extract_audio_segment(
                ref_clip.path, ref_src_start, win,
                sr=self._alignment_sr,
                bandpass=self._alignment_bandpass,
                hp=self._alignment_hp, lp=self._alignment_lp,
            )
            cam_samples = self._extract_audio_segment(
                best.path, cam_src_start, win,
                sr=self._alignment_sr,
                bandpass=self._alignment_bandpass,
                hp=self._alignment_hp, lp=self._alignment_lp,
            )

            # Sanity check
            if ref_samples.size == 0 or cam_samples.size == 0:
                offsets[cam] = 0.0
                continue

            # Normalize
            ref_samples = ref_samples - np.mean(ref_samples)
            cam_samples = cam_samples - np.mean(cam_samples)
            ref_energy = np.linalg.norm(ref_samples)
            cam_energy = np.linalg.norm(cam_samples)
            if ref_energy == 0 or cam_energy == 0:
                offsets[cam] = 0.0
                continue
            ref_samples /= ref_energy
            cam_samples /= cam_energy

            # Cross-correlation (full)
            corr = np.correlate(cam_samples, ref_samples, mode='full')
            # lag index relative to ref: index of max - (N-1)
            n = ref_samples.shape[0]
            lag_idx = int(np.argmax(corr) - (n - 1))
            lag_seconds = lag_idx / float(self._alignment_sr)
            # Bound the lag to configured max shift
            lag_seconds = float(max(-self._alignment_max_shift, min(self._alignment_max_shift, lag_seconds)))

            # Positive lag_seconds means cam is behind reference (needs to start later)
            offsets[cam] = lag_seconds

        return offsets

    def _extract_audio_segment(
        self,
        video_path: str,
        source_start: float,
        duration: float,
        sr: int = 16000,
        bandpass: bool = True,
        hp: int = 300,
        lp: int = 3000,
    ) -> np.ndarray:
        """Extract a mono PCM audio segment as numpy array of float32 in [-1, 1]."""
        filter_chain = []
        if bandpass:
            filter_chain.append(f"highpass=f={hp}")
            filter_chain.append(f"lowpass=f={lp}")
        af = None
        if filter_chain:
            af = ','.join(filter_chain)

        cmd = [
            'ffmpeg',
            '-ss', f"{max(0.0, source_start):.3f}",
            '-t', f"{max(0.0, duration):.3f}",
            '-i', video_path,
            '-vn',
            '-ac', '1',
            '-ar', str(sr),
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
        ]
        if af:
            cmd.extend(['-af', af])
        cmd.append('pipe:1')

        try:
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or not proc.stdout:
                return np.array([], dtype=np.float32)
            data = np.frombuffer(proc.stdout, dtype=np.int16)
            if data.size == 0:
                return np.array([], dtype=np.float32)
            # Normalize to [-1, 1]
            return (data.astype(np.float32) / 32768.0).copy()
        except Exception:
            return np.array([], dtype=np.float32)

    def _calculate_audio_quality(self, video_path: str, media_info: Any) -> float:
        """
        Calculate audio quality score for a video clip.

        Uses ffmpeg to analyze audio properties like volume, noise level, etc.
        Higher score = better quality.

        Args:
            video_path: Path to video file
            media_info: Media info from probe

        Returns:
            float: Quality score (0.0 to 1.0, higher is better)
        """
        if not media_info.has_audio:
            return 0.0

        try:
            # Use ffmpeg astats filter to get audio statistics
            command = [
                'ffmpeg',
                '-i', video_path,
                '-af', 'astats=metadata=1:reset=1',
                '-f', 'null',
                '-'
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse RMS and peak levels from stderr
            rms_levels = []
            for line in result.stderr.split('\n'):
                if 'RMS level dB' in line:
                    try:
                        # Extract dB value (e.g., "RMS level dB: -25.3")
                        db_value = float(line.split(':')[-1].strip())
                        rms_levels.append(db_value)
                    except (ValueError, IndexError):
                        pass

            if not rms_levels:
                # Default score if we can't parse audio stats
                return 0.5

            # Calculate average RMS level
            avg_rms = sum(rms_levels) / len(rms_levels)

            # Convert dB to quality score (typical speech is -30 to -15 dB)
            # Score range: silence (-60dB) = 0.0, optimal (-20dB) = 1.0, clipping (0dB) = 0.5
            if avg_rms >= -20:
                # Good volume level
                score = 1.0 - (avg_rms + 20) / 40  # Decreases as it approaches 0dB (clipping)
            else:
                # Too quiet
                score = max(0.0, (avg_rms + 60) / 40)  # Increases from -60dB to -20dB

            return max(0.0, min(1.0, score))

        except subprocess.TimeoutExpired:
            logging.warning(f"Audio analysis timed out for {video_path}")
            return 0.5
        except Exception as e:
            logging.warning(f"Could not analyze audio quality for {video_path}: {e}")
            return 0.5

    def _select_audio_source(self, camera_clips: List[CameraClip]) -> CameraClip:
        """
        Select the best audio source from available clips.

        Args:
            camera_clips: List of analyzed camera clips

        Returns:
            CameraClip with the best audio quality
        """
        if not camera_clips:
            raise ValueError("No camera clips available for audio selection")

        if self.audio_source == 'first':
            return camera_clips[0]
        elif self.audio_source == 'longest':
            return max(camera_clips, key=lambda x: x.duration)
        else:  # 'best_quality' or default
            best_clip = max(camera_clips, key=lambda x: x.audio_quality_score)
            logging.info(
                f"Selected audio from {best_clip.camera} "
                f"(quality score: {best_clip.audio_quality_score:.2f})"
            )
            return best_clip

    def _generate_composition_timeline(
        self,
        camera_clips: List[CameraClip]
    ) -> List[CompositionSegment]:
        """
        Generate a timeline of which camera to use at each point in time.

        Args:
            camera_clips: List of analyzed camera clips

        Returns:
            List of CompositionSegment objects defining the final video timeline
        """
        if self.switching_strategy == 'round_robin':
            return self._timeline_round_robin(camera_clips)
        elif self.switching_strategy == 'audio_quality':
            return self._timeline_by_audio_quality(camera_clips)
        else:  # 'time_based' or default
            return self._timeline_time_based(camera_clips)

    def _generate_aligned_timelines(
        self,
        camera_clips: List[CameraClip]
    ) -> Tuple[List[CompositionSegment], List[CompositionSegment]]:
        """
        Build overlap-aligned timelines for video and audio across the full event.

        We create boundaries from all clip starts and ends, and for each interval
        choose the best available camera for video and for audio (configurable).

        Returns:
            (video_segments, audio_segments)
        """
        if not camera_clips:
            return [], []

        # Build boundaries: sorted unique times (seconds from event start)
        boundaries: List[float] = sorted({
            0.0,
            *[c.start_time for c in camera_clips],
            *[c.start_time + c.duration for c in camera_clips],
        })

        # Helper state for round robin selection stability
        rr_index = 0
        cameras_sorted = sorted(set(c.camera for c in camera_clips))

        video_segments: List[CompositionSegment] = []
        audio_segments: List[CompositionSegment] = []

        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            seg_dur = seg_end - seg_start
            if seg_dur <= 0:
                continue

            # Cameras available at seg_start
            avail = [c for c in camera_clips if c.start_time <= seg_start < c.start_time + c.duration]
            if not avail:
                continue

            # VIDEO selection per strategy
            selected_v: Optional[CameraClip] = None
            if self.switching_strategy == 'audio_quality':
                selected_v = max(avail, key=lambda x: x.audio_quality_score)
            elif self.switching_strategy == 'round_robin':
                # Pick next camera in order that is available
                for _ in range(len(cameras_sorted)):
                    cam = cameras_sorted[rr_index % len(cameras_sorted)]
                    rr_index += 1
                    match = [c for c in avail if c.camera == cam]
                    if match:
                        selected_v = match[0]
                        break
                if not selected_v:
                    selected_v = avail[0]
            else:  # 'time_based' default -> prefer stability, keep previous if continuous else best audio
                if video_segments:
                    last = video_segments[-1]
                    cont = [c for c in avail if c.path == last.clip_path]
                    if cont:
                        selected_v = cont[0]
                if not selected_v:
                    selected_v = max(avail, key=lambda x: x.audio_quality_score)

            v_source_start = max(0.0, seg_start - selected_v.start_time)
            video_segments.append(CompositionSegment(
                camera=selected_v.camera,
                clip_path=selected_v.path,
                start_time=seg_start,
                duration=seg_dur,
                source_start=v_source_start,
            ))

            # AUDIO selection
            selected_a: Optional[CameraClip] = None
            if self.audio_source in ('best_quality', 'per_segment'):
                selected_a = max(avail, key=lambda x: x.audio_quality_score)
            elif self.audio_source == 'longest':
                selected_a = max(avail, key=lambda x: x.duration)
            else:  # 'first'
                selected_a = min(avail, key=lambda x: x.start_time)

            a_source_start = max(0.0, seg_start - selected_a.start_time)
            audio_segments.append(CompositionSegment(
                camera=selected_a.camera,
                clip_path=selected_a.path,
                start_time=seg_start,
                duration=seg_dur,
                source_start=a_source_start,
            ))

        # Merge adjacent segments with the same source to reduce cuts
        video_segments = self._coalesce_segments(video_segments)
        audio_segments = self._coalesce_segments(audio_segments)

        return video_segments, audio_segments

    def _timeline_time_based(self, camera_clips: List[CameraClip]) -> List[CompositionSegment]:
        """
        Create timeline by switching cameras at regular intervals.

        Args:
            camera_clips: List of camera clips

        Returns:
            List of composition segments
        """
        timeline = []
        current_time = 0.0

        # Calculate total event duration
        total_duration = max(
            clip.start_time + clip.duration
            for clip in camera_clips
        )

        # Sort clips by camera name for consistent ordering
        cameras_sorted = sorted(set(clip.camera for clip in camera_clips))
        camera_index = 0

        while current_time < total_duration:
            # Find which cameras are available at current_time
            available_clips = [
                clip for clip in camera_clips
                if clip.start_time <= current_time < clip.start_time + clip.duration
            ]

            if not available_clips:
                # No clips available at this time, advance to next clip start
                future_clips = [
                    clip for clip in camera_clips
                    if clip.start_time > current_time
                ]
                if future_clips:
                    current_time = min(clip.start_time for clip in future_clips)
                    continue
                else:
                    break

            # Select next camera in rotation that's available
            selected_clip = None
            for _ in range(len(cameras_sorted)):
                camera_name = cameras_sorted[camera_index % len(cameras_sorted)]
                camera_index += 1

                # Find clip from this camera
                matching = [c for c in available_clips if c.camera == camera_name]
                if matching:
                    selected_clip = matching[0]
                    break

            if not selected_clip:
                selected_clip = available_clips[0]

            # Calculate segment duration
            segment_duration = min(
                self.switching_interval,
                (selected_clip.start_time + selected_clip.duration) - current_time,
                total_duration - current_time
            )

            # Calculate where to start in the source clip
            source_start = current_time - selected_clip.start_time

            timeline.append(CompositionSegment(
                camera=selected_clip.camera,
                clip_path=selected_clip.path,
                start_time=current_time,
                duration=segment_duration,
                source_start=source_start
            ))

            current_time += segment_duration

        return timeline

    def _timeline_round_robin(self, camera_clips: List[CameraClip]) -> List[CompositionSegment]:
        """
        Create timeline by cycling through available cameras equally.

        Similar to time_based but ensures equal representation of all cameras.
        """
        return self._timeline_time_based(camera_clips)  # For now, reuse time_based

    def _timeline_by_audio_quality(self, camera_clips: List[CameraClip]) -> List[CompositionSegment]:
        """
        Create timeline by preferring cameras with better audio at each moment.
        """
        timeline = []
        current_time = 0.0

        total_duration = max(
            clip.start_time + clip.duration
            for clip in camera_clips
        )

        while current_time < total_duration:
            # Find available clips at current time
            available_clips = [
                clip for clip in camera_clips
                if clip.start_time <= current_time < clip.start_time + clip.duration
            ]

            if not available_clips:
                future_clips = [
                    clip for clip in camera_clips
                    if clip.start_time > current_time
                ]
                if future_clips:
                    current_time = min(clip.start_time for clip in future_clips)
                    continue
                else:
                    break

            # Select clip with best audio quality
            selected_clip = max(available_clips, key=lambda x: x.audio_quality_score)

            # Determine how long this clip is the best choice
            segment_duration = min(
                self.switching_interval,
                (selected_clip.start_time + selected_clip.duration) - current_time,
                total_duration - current_time
            )

            source_start = current_time - selected_clip.start_time

            timeline.append(CompositionSegment(
                camera=selected_clip.camera,
                clip_path=selected_clip.path,
                start_time=current_time,
                duration=segment_duration,
                source_start=source_start
            ))

            current_time += segment_duration

        return timeline

    def _create_composite_video(
        self,
        video_timeline: List[CompositionSegment],
        audio_timeline: List[CompositionSegment],
        output_path: str
    ) -> bool:
        """
        Create the final composite video using ffmpeg based on the timeline.

        Args:
            timeline: List of composition segments
            audio_source: Clip to use for audio
            output_path: Output file path

        Returns:
            bool: True if successful
        """
        if not video_timeline:
            logging.error("Empty timeline, cannot create composite")
            return False

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Step 1: Extract and trim video segments according to timeline
                segment_files = []
                for i, segment in enumerate(video_timeline):
                    segment_path = os.path.join(tmpdir, f"segment_{i:03d}.mp4")

                    # Extract segment from source clip
                    command = [
                        'ffmpeg',
                        '-y',
                        '-loglevel', 'error',
                        '-ss', str(segment.source_start),
                        '-i', segment.clip_path,
                        '-t', str(segment.duration),
                        '-c:v', 'libx264',
                        '-preset', 'fast',
                        '-crf', '23',
                        '-an',  # No audio in segments (will add later)
                        segment_path
                    ]

                    result = subprocess.run(command, capture_output=True)
                    if result.returncode != 0:
                        logging.error(f"Failed to extract segment {i}: {result.stderr.decode()}")
                        return False

                    segment_files.append(segment_path)

                # Step 2: Concatenate video segments
                concat_list_path = os.path.join(tmpdir, 'concat_list.txt')
                with open(concat_list_path, 'w') as f:
                    for seg_file in segment_files:
                        f.write(f"file '{seg_file}'\n")

                video_only_path = os.path.join(tmpdir, 'video_only.mp4')
                command = [
                    'ffmpeg',
                    '-y',
                    '-loglevel', 'error',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_list_path,
                    '-c', 'copy',
                    video_only_path
                ]

                result = subprocess.run(command, capture_output=True)
                if result.returncode != 0:
                    logging.error(f"Failed to concatenate segments: {result.stderr.decode()}")
                    return False

                # Optional overlay: burn timestamp in bottom-right using ASS subtitles
                # Build overlay video path if enabled
                overlay_input_path = video_only_path
                if self._overlay_enabled and self._event_start is not None:
                    total_duration = sum(s.duration for s in video_timeline)
                    ass_path = self._generate_timestamp_ass(tmpdir, total_duration, self._event_start, self._overlay_dst_hours)
                    if ass_path:
                        overlayed_video_path = os.path.join(tmpdir, 'video_overlay.mp4')
                        cmd = [
                            'ffmpeg',
                            '-y',
                            '-loglevel', 'error',
                            '-i', overlay_input_path,
                            '-vf', f"subtitles='{ass_path}':force_style='Alignment=3,FontName={self._overlay_font},FontSize={self._overlay_font_size},OutlineColour=&H55000000,BorderStyle=1,Outline=2,Shadow=0,MarginV={self._overlay_margin_v},MarginR={self._overlay_margin_r}'",
                            '-c:v', 'libx264',
                            '-preset', 'fast',
                            '-crf', '22',
                            overlayed_video_path
                        ]
                        res2 = subprocess.run(cmd, capture_output=True)
                        if res2.returncode == 0:
                            overlay_input_path = overlayed_video_path
                        else:
                            logging.warning("Failed to apply timestamp overlay, continuing without it: %s", res2.stderr.decode())

                # Step 3: Extract and concatenate audio segments to span entire event
                audio_seg_files = []
                for i, segment in enumerate(audio_timeline):
                    a_seg_path = os.path.join(tmpdir, f"audio_{i:03d}.wav")
                    command = [
                        'ffmpeg',
                        '-y',
                        '-loglevel', 'error',
                        '-ss', str(segment.source_start),
                        '-i', segment.clip_path,
                        '-t', str(segment.duration),
                        '-vn',
                        '-acodec', 'pcm_s16le',
                        '-ar', '48000',
                        '-ac', '2',
                        a_seg_path
                    ]
                    result = subprocess.run(command, capture_output=True)
                    if result.returncode != 0:
                        logging.error(f"Failed to extract audio segment {i}: {result.stderr.decode()}")
                        return False
                    audio_seg_files.append(a_seg_path)

                audio_concat_list = os.path.join(tmpdir, 'audio_concat.txt')
                with open(audio_concat_list, 'w') as f:
                    for seg_file in audio_seg_files:
                        f.write(f"file '{seg_file}'\n")

                audio_path_wav = os.path.join(tmpdir, 'audio_full.wav')
                command = [
                    'ffmpeg',
                    '-y',
                    '-loglevel', 'error',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', audio_concat_list,
                    '-c', 'copy',
                    audio_path_wav
                ]
                result = subprocess.run(command, capture_output=True)
                if result.returncode != 0:
                    logging.error(f"Failed to concatenate audio: {result.stderr.decode()}")
                    return False

                # Step 4: Combine video (optionally overlayed) and audio
                command = [
                    'ffmpeg',
                    '-y',
                    '-loglevel', 'error',
                    '-i', overlay_input_path,
                    '-i', audio_path_wav,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    '-movflags', '+faststart',
                    output_path
                ]

                result = subprocess.run(command, capture_output=True)
                if result.returncode != 0:
                    logging.error(f"Failed to combine video and audio: {result.stderr.decode()}")
                    return False

                logging.info(f"Created composite with {len(video_timeline)} segments from {len(set(s.camera for s in video_timeline))} cameras")
                return True

        except Exception as e:
            logging.error(f"Error creating composite video: {e}")
            return False

    def _simple_copy(self, video_clips: List[Dict[str, Any]], output_path: str) -> bool:
        """
        Simple copy of a single video file.
        """
        if not video_clips:
            return False

        source = video_clips[0]['path']
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        command = [
            'ffmpeg',
            '-y',
            '-loglevel', 'error',
            '-i', source,
            '-c', 'copy',
            output_path
        ]

        result = subprocess.run(command)
        return result.returncode == 0

    def _sequential_merge(self, video_clips: List[Dict[str, Any]], output_path: str) -> bool:
        """
        Sequential merge of clips from the same camera (fallback behavior).
        """
        from .video import merge_video_clips

        video_paths = [clip['path'] for clip in sorted(video_clips, key=lambda x: x['datetime'])]
        crossfade = self.config.get('video_processing', {}).get('crossfade_duration', 0.5)

        return merge_video_clips(video_paths, output_path, crossfade)

    @staticmethod
    def _coalesce_segments(segments: List[CompositionSegment]) -> List[CompositionSegment]:
        """Merge adjacent segments that use the same source to reduce cuts."""
        if not segments:
            return []
        merged: List[CompositionSegment] = []
        current = segments[0]
        for seg in segments[1:]:
            # If contiguous and from same source clip, extend
            if (
                seg.clip_path == current.clip_path and
                abs((seg.start_time) - (current.start_time + current.duration)) < 1e-3
            ):
                current.duration += seg.duration
            else:
                merged.append(current)
                current = seg
        merged.append(current)
        return merged

    def _generate_timestamp_ass(
        self,
        tmpdir: str,
        total_duration: float,
        event_start: datetime,
        dst_offset_hours: int = 1,
    ) -> Optional[str]:
        """Generate an ASS subtitle file with per-second wallclock timestamps.

        Returns path to the ASS file or None on failure.
        """
        try:
            # Prepare ASS header
            ass_lines: List[str] = []
            ass_lines.append("[Script Info]")
            ass_lines.append("ScriptType: v4.00+")
            ass_lines.append("PlayResX: 1920")
            ass_lines.append("PlayResY: 1080")
            ass_lines.append("")
            ass_lines.append("[V4+ Styles]")
            ass_lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
            # PrimaryColour white &H00FFFFFF, OutlineColour semi-black &H55000000
            style_line = (
                f"Style: Overlay,{self._overlay_font},{self._overlay_font_size},&H00FFFFFF,&H000000FF,&H55000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,3,20,{self._overlay_margin_r},{self._overlay_margin_v},1"
            )
            ass_lines.append(style_line)
            ass_lines.append("")
            ass_lines.append("[Events]")
            ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

            # Generate one Dialogue per second
            total_secs = int(max(0, int(total_duration + 0.5)))
            base = event_start + timedelta(hours=dst_offset_hours)

            def fmt_ass_time(seconds: float) -> str:
                # ASS h:mm:ss.cs
                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                s = int(seconds % 60)
                cs = int((seconds - int(seconds)) * 100)
                return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

            for t in range(0, total_secs):
                wall = base + timedelta(seconds=t)
                text = wall.strftime("%Y-%m-%d %H:%M:%S")
                start_ts = fmt_ass_time(t)
                end_ts = fmt_ass_time(t + 1)
                ass_lines.append(f"Dialogue: 0,{start_ts},{end_ts},Overlay,,0000,0000,0000,,{text}")

            ass_path = os.path.join(tmpdir, 'timestamp.ass')
            with open(ass_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(ass_lines))
            return ass_path
        except Exception as e:
            logging.warning("Failed to generate ASS overlay: %s", e)
            return None
