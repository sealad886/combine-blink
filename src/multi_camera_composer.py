"""
Multi-camera video composition module.

This module handles compositing videos from multiple cameras that recorded the same
event from different angles. It analyzes audio quality, selects optimal camera angles,
and creates a final composite video with the best footage and audio.
"""

import logging
import os
import re
import subprocess
import tempfile
import json
from datetime import datetime, timedelta
from typing import Callable, List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

from src.media_utils import probe_media_info
from src.av_alignment import estimate_offsets_and_drift


@dataclass
class CameraClip:
    """Represents a single camera clip with metadata."""
    path: str
    camera: str
    start_time: float  # Seconds since event start
    duration: float
    audio_quality_score: float = 0.0
    video_quality_score: float = 0.0
    people_count: float = 0.0


@dataclass
class CompositionSegment:
    """Represents a segment of the final composition."""
    camera: str
    clip_path: str
    start_time: float  # Time in the final composition
    duration: float
    source_start: float = 0.0  # Start time within the source clip
    needs_review: bool = False
    speech_active: bool = True


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
            self.audio_source == 'best_quality'
            or self.switching_strategy in ('audio_quality', 'speech_people')
        )

        weights_cfg = self.composition_config.get('audio_quality_weights', {})
        self._quality_weights = {
            'rms': float(weights_cfg.get('rms', 0.4)),
            'peak': float(weights_cfg.get('peak', weights_cfg.get('peak_level', 0.2))),
            'noise': float(weights_cfg.get('noise', weights_cfg.get('noise_floor', 0.2))),
            'clip': float(weights_cfg.get('clip', weights_cfg.get('clipping', 0.2))),
        }
        total_weight = sum(self._quality_weights.values())
        if total_weight <= 0:
            self._quality_weights = {'rms': 1.0, 'peak': 0.0, 'noise': 0.0, 'clip': 0.0}
        else:
            self._quality_weights = {
                k: (v / total_weight if total_weight else 0.0)
                for k, v in self._quality_weights.items()
            }

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
        # New alignment tuning
        self._alignment_hop: float = float(self.alignment_config.get('hop_seconds', max(0.1, self._alignment_window / 2.0)))
        self._alignment_estimate_drift: bool = bool(self.alignment_config.get('estimate_drift', True))
        # Storage for per-camera alignment metadata
        self._alignment_offsets: Dict[str, float] = {}
        self._alignment_drifts: Dict[str, float] = {}

        people_defaults = {
            'enabled': True,
            'sample_frames': 6,
            'resize_width': 640,
            'min_frame_width': 320,
        }
        self.people_config = people_defaults.copy()
        self.people_config.update(self.composition_config.get('people_detection', {}))
        people_enabled_cfg = bool(self.people_config.get('enabled', True))
        self._people_detection_warned: bool = False
        self._people_detection_enabled: bool = (
            self.switching_strategy == 'speech_people'
            and people_enabled_cfg
            and cv2 is not None
        )
        if self.switching_strategy == 'speech_people' and people_enabled_cfg and cv2 is None and not self._people_detection_warned:
            logging.warning(
                "speech_people switching_strategy requires opencv-python for people detection; "
                "falling back to audio-driven selection."
            )
            self._people_detection_warned = True
        self._people_sample_frames: int = max(1, int(self.people_config.get('sample_frames', 6)))
        self._people_resize_width: int = max(160, int(self.people_config.get('resize_width', 640)))
        self._people_min_frame_width: int = max(160, int(self.people_config.get('min_frame_width', 320)))

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

        cleanup_defaults = {
            'enabled': True,
            'highpass_hz': 120.0,
            'lowpass_hz': 7000.0,
            'denoise': True,
            'denoise_nf': -25.0,
            'loudness_normalize': True,
            'loudnorm_target_i': -24.0,
            'loudnorm_target_tp': -2.0,
            'loudnorm_target_lra': 11.0,
            'extra_filters': [],
            'custom_filter': None,
        }
        cleanup_cfg = cleanup_defaults.copy()
        cleanup_cfg.update(self.composition_config.get('audio_cleanup', {}))

        def _float_or_none(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        self._cleanup_enabled: bool = bool(cleanup_cfg.get('enabled', True))
        self._cleanup_highpass: Optional[float] = _float_or_none(cleanup_cfg.get('highpass_hz'))
        if self._cleanup_highpass is not None and self._cleanup_highpass <= 0:
            self._cleanup_highpass = None
        self._cleanup_lowpass: Optional[float] = _float_or_none(cleanup_cfg.get('lowpass_hz'))
        if self._cleanup_lowpass is not None and self._cleanup_lowpass <= 0:
            self._cleanup_lowpass = None
        self._cleanup_denoise: bool = bool(cleanup_cfg.get('denoise', True))
        nf_value = _float_or_none(cleanup_cfg.get('denoise_nf'))
        self._cleanup_denoise_nf: float = nf_value if nf_value is not None else -25.0
        self._cleanup_loudnorm: bool = bool(cleanup_cfg.get('loudness_normalize', True))
        loudnorm_i = _float_or_none(cleanup_cfg.get('loudnorm_target_i'))
        self._cleanup_loudnorm_i: float = loudnorm_i if loudnorm_i is not None else -24.0
        loudnorm_tp = _float_or_none(cleanup_cfg.get('loudnorm_target_tp'))
        self._cleanup_loudnorm_tp: float = loudnorm_tp if loudnorm_tp is not None else -2.0
        loudnorm_lra = _float_or_none(cleanup_cfg.get('loudnorm_target_lra'))
        self._cleanup_loudnorm_lra: float = loudnorm_lra if loudnorm_lra is not None else 11.0

        extra_filters = cleanup_cfg.get('extra_filters', [])
        if isinstance(extra_filters, str):
            extra_filters = [extra_filters]
        self._cleanup_extra_filters: List[str] = [str(f) for f in extra_filters if f]
        custom_filter = cleanup_cfg.get('custom_filter')
        self._cleanup_custom_filter: Optional[str] = str(custom_filter) if custom_filter else None
        self._cleanup_filter_string: Optional[str] = None

        # Event start (wall-clock) captured during analysis for overlay timing
        self._event_start: Optional[datetime] = None
        self._speech_segments_event: List[Tuple[float, float]] = []
        self._review_segments: List[Tuple[float, float]] = []
        self._has_speech_data: bool = False
        # Audio stitching improvements
        self._audio_crossfade_s: float = float(self.composition_config.get('audio_crossfade_seconds', 0.06))

    def compose_multi_camera_event(
        self,
        video_clips: List[Dict[str, Any]],
        output_path: str,
        speech_segments: Optional[List[Dict[str, Any]]] = None,
        speech_timeline: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Create a composite video from multiple camera angles of the same event.

        Args:
            video_clips: List of video file dictionaries (with 'path', 'camera', 'datetime')
            output_path: Path where the final composite video will be saved
            speech_segments: Optional diarization segments with start/end times (seconds)
            speech_timeline: Optional clip timeline produced during transcription
            progress_callback: Optional callback function(current, total) for progress updates

        Returns:
            bool: True if composition succeeded, False otherwise
        """
        # If only one clip or composition disabled, use simple merge
        if len(video_clips) == 1 or not self.enable_composition:
            logging.info(f"Single camera or composition disabled, using simple copy")
            result = self._simple_copy(video_clips, output_path)
            if progress_callback:
                progress_callback(len(video_clips), len(video_clips))  # Report completion
            return result

        # Check if all clips are from the same camera (shouldn't happen with new grouping)
        cameras = set(clip['camera'] for clip in video_clips)
        if len(cameras) == 1:
            logging.info(f"All clips from same camera ({cameras.pop()}), using sequential merge")
            result = self._sequential_merge(video_clips, output_path)
            if progress_callback:
                progress_callback(len(video_clips), len(video_clips))  # Report completion
            return result

        logging.info(f"Composing multi-camera event from {len(video_clips)} clips across {len(cameras)} cameras")

        # Calculate total steps for progress tracking
        total_steps = len(video_clips)

        def _report_progress(completed: int):
            """Helper to report progress if callback provided."""
            if progress_callback:
                try:
                    logging.info(f"[COMPOSER] Reporting progress: {completed}/{total_steps}")
                    progress_callback(completed, total_steps)
                except Exception as e:
                    logging.warning(f"Progress callback error: {e}", exc_info=True)

        try:
            # Step 1: Analyze audio quality for each clip and capture event start (20% of work)
            _report_progress(int(total_steps * 0.0))
            camera_clips = self._analyze_clips(video_clips)
            self._load_speech_segments(speech_segments, speech_timeline, camera_clips)
            self._review_segments = []
            _report_progress(int(total_steps * 0.2))

            # Step 1b: Estimate per-camera fine alignment offsets and adjust timings (10% of work)
            if self._alignment_enabled:
                try:
                    ref_clip = max(camera_clips, key=lambda x: x.audio_quality_score)
                    offsets, drifts = estimate_offsets_and_drift(
                        camera_clips,
                        ref_clip.camera,
                        sample_rate=self._alignment_sr,
                        window_seconds=self._alignment_window,
                        hop_seconds=self._alignment_hop,
                        max_shift_seconds=self._alignment_max_shift,
                        bandpass=self._alignment_bandpass,
                        hp=self._alignment_hp,
                        lp=self._alignment_lp,
                        estimate_drift=self._alignment_estimate_drift,
                    )
                    self._alignment_offsets = dict(offsets or {})
                    self._alignment_drifts = dict(drifts or {})
                    if self._alignment_offsets:
                        # Apply base offsets to clip start times for better video sync; drift applied later to audio only
                        for cc in camera_clips:
                            base = self._alignment_offsets.get(cc.camera, 0.0)
                            if abs(base) > 1e-6:
                                cc.start_time = max(0.0, cc.start_time + base)
                        logging.info("Applied alignment offsets: %s", json.dumps(self._alignment_offsets))
                        if any(abs(v) > 1e-6 for v in self._alignment_drifts.values()):
                            logging.info("Estimated alignment drifts (s/s): %s", json.dumps(self._alignment_drifts))
                except Exception as e:
                    logging.warning("Audio alignment estimation failed, continuing without it: %s", e)
            _report_progress(int(total_steps * 0.3))

            # Step 2: Generate overlap-aligned timelines for video and audio across the full event (10% of work)
            video_timeline, audio_timeline = self._generate_aligned_timelines(camera_clips)
            self._review_segments = self._extract_review_segments(video_timeline)
            _report_progress(int(total_steps * 0.4))

            # Step 3: Create the composite video using ffmpeg (60% of work)
            success = self._create_composite_video(video_timeline, audio_timeline, output_path)
            _report_progress(total_steps)  # 100% complete

            if success:
                logging.info(f"Successfully composed multi-camera event to {output_path}")

            return success

        except Exception as e:
            logging.error(f"Failed to compose multi-camera event: {e}")
            # Fallback to simple merge on error
            logging.info("Falling back to sequential merge")
            result = self._sequential_merge(video_clips, output_path)
            if progress_callback:
                progress_callback(total_steps, total_steps)  # Report completion even on fallback
            return result

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

            if self._people_detection_enabled:
                people_count = self._resolve_people_count(clip, media_info)
            else:
                people_count = float(clip.get('people_count') or 0.0)

            camera_clips.append(CameraClip(
                path=clip['path'],
                camera=clip['camera'],
                start_time=start_offset,
                duration=media_info.duration,
                audio_quality_score=audio_score,
                video_quality_score=video_score,
                people_count=people_count,
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

    def _build_audio_cleanup_filter(self) -> Optional[str]:
        """Return the ffmpeg filterchain used to clean extracted audio segments."""
        if not getattr(self, '_cleanup_enabled', False):
            return None
        if self._cleanup_filter_string is not None:
            return self._cleanup_filter_string

        if self._cleanup_custom_filter:
            self._cleanup_filter_string = self._cleanup_custom_filter
            return self._cleanup_filter_string

        filters: List[str] = []
        if self._cleanup_highpass is not None:
            filters.append(f"highpass=f={self._cleanup_highpass:g}")
        if self._cleanup_lowpass is not None:
            filters.append(f"lowpass=f={self._cleanup_lowpass:g}")
        if self._cleanup_denoise:
            filters.append(f"afftdn=nf={self._cleanup_denoise_nf:g}")
        if self._cleanup_loudnorm:
            filters.append(
                "loudnorm=I={i:g}:TP={tp:g}:LRA={lra:g}:dual_mono=true".format(
                    i=self._cleanup_loudnorm_i,
                    tp=self._cleanup_loudnorm_tp,
                    lra=self._cleanup_loudnorm_lra,
                )
            )
        if self._cleanup_extra_filters:
            filters.extend(self._cleanup_extra_filters)

        self._cleanup_filter_string = ','.join(filters) if filters else None
        return self._cleanup_filter_string

    def _resolve_people_count(self, clip: Dict[str, Any], media_info: Any) -> float:
        """Determine how many people are visible in this clip (best effort)."""
        # Honour any upstream metadata first
        for key in ("people_count", "people_estimate", "person_count"):
            value = clip.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                logging.debug("Non-numeric %s value '%s' on clip %s", key, value, clip.get('path'))

        video_path = clip.get('path') or clip.get('full_path')
        if not video_path:
            return 0.0

        return self._estimate_people_count(video_path, media_info)

    def _estimate_people_count(self, video_path: str, media_info: Any) -> float:
        if not self._people_detection_enabled:
            if self.people_config.get('enabled', True) and cv2 is None and not self._people_detection_warned:
                logging.warning(
                    "OpenCV is required for people detection but is not installed; "
                    "falling back to audio-only camera selection."
                )
                self._people_detection_warned = True
            return 0.0

        try:
            return self._detect_people_hog(video_path, float(getattr(media_info, 'duration', 0.0) or 0.0))
        except Exception as exc:  # pragma: no cover - best effort fallback
            logging.warning("People detection failed for %s: %s", video_path, exc)
            return 0.0

    def _detect_people_hog(self, video_path: str, duration: float) -> float:
        # Lazily initialise detector per call to avoid cross-process issues
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 0.0

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count <= 0 and duration > 0:
            # Fallback estimate of frame count assuming 25fps
            frame_count = int(duration * 25)
        frame_count = max(frame_count, self._people_sample_frames)

        step = max(1, frame_count // (self._people_sample_frames + 1))
        samples = 0
        detections = 0

        resize_width = self._people_resize_width
        min_width = self._people_min_frame_width

        for idx in range(self._people_sample_frames):
            target_frame = min(idx * step, frame_count - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            height, width = frame.shape[:2]
            if width <= 0 or height <= 0:
                continue

            scale = 1.0
            if width > resize_width:
                scale = resize_width / float(width)
            elif width < min_width:
                scale = min_width / float(width)

            if scale != 1.0:
                frame = cv2.resize(frame, (int(width * scale), int(height * scale)))

            found, _ = hog.detectMultiScale(
                frame,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
            detections += len(found)
            samples += 1

        cap.release()

        if samples == 0:
            return 0.0

        return float(detections) / float(samples)

    def _load_speech_segments(
        self,
        speech_segments: Optional[List[Dict[str, Any]]],
        speech_timeline: Optional[List[Dict[str, Any]]],
        camera_clips: List[CameraClip],
    ) -> None:
        """Transform transcription segments into event-relative intervals."""
        self._speech_segments_event = []
        self._has_speech_data = False

        if not speech_segments or not speech_timeline or not camera_clips:
            return

        timeline_entries: List[Dict[str, float]] = []
        for entry in speech_timeline:
            path = entry.get('path')
            if not path:
                continue
            try:
                offset = float(entry.get('offset', 0.0))
                duration = float(entry.get('duration', 0.0))
            except (TypeError, ValueError):
                continue
            timeline_entries.append({'path': path, 'offset': offset, 'duration': duration})

        if not timeline_entries:
            return

        timeline_entries.sort(key=lambda item: item['offset'])
        clip_map = {clip.path: clip for clip in camera_clips}

        intervals: List[Tuple[float, float]] = []

        for segment in speech_segments:
            try:
                seg_start = float(segment.get('start', 0.0))
                seg_end = float(segment.get('end', 0.0))
            except (TypeError, ValueError):
                continue

            if seg_end <= seg_start:
                continue

            cursor = seg_start
            safety = 0
            while cursor < seg_end and safety < len(timeline_entries) + 5:
                safety += 1
                entry = next(
                    (
                        item for item in timeline_entries
                        if item['offset'] <= cursor < item['offset'] + item['duration']
                    ),
                    None,
                )
                if not entry:
                    break

                clip = clip_map.get(entry['path'])
                if not clip:
                    cursor = entry['offset'] + entry['duration'] + 1e-3
                    continue

                clip_relative_start = cursor - entry['offset']
                clip_relative_start = max(0.0, clip_relative_start)
                clip_relative_end = min(seg_end, entry['offset'] + entry['duration']) - entry['offset']

                event_start = clip.start_time + clip_relative_start
                event_end = clip.start_time + clip_relative_end

                event_start = max(event_start, clip.start_time)
                event_end = min(event_end, clip.start_time + clip.duration)

                if event_end > event_start:
                    intervals.append((event_start, event_end))

                cursor = entry['offset'] + entry['duration'] + 1e-3

        if not intervals:
            return

        self._speech_segments_event = self._merge_intervals(intervals)
        self._has_speech_data = True

    @staticmethod
    def _merge_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if not intervals:
            return []
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        merged: List[Tuple[float, float]] = [sorted_intervals[0]]
        for start, end in sorted_intervals[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end + 1e-3:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    def _segment_has_speech(self, start: float, end: float) -> bool:
        if not getattr(self, '_has_speech_data', False):
            return True
        for seg_start, seg_end in self._speech_segments_event:
            if seg_start >= end:
                break
            if seg_end > start and seg_start < end:
                return True
        return False

    @staticmethod
    def _extract_review_segments(segments: List[CompositionSegment]) -> List[Tuple[float, float]]:
        review_intervals = [
            (seg.start_time, seg.start_time + seg.duration)
            for seg in segments
            if seg.needs_review and seg.duration > 0
        ]
        return MultiCameraComposer._merge_intervals(review_intervals)

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

            stderr_output = result.stderr or ''
            if result.returncode != 0 and not stderr_output:
                logging.warning(
                    "Audio analysis failed for %s (code %s)",
                    video_path,
                    result.returncode,
                )
                return 0.5

            rms_levels: List[float] = []
            rms_min_levels: List[float] = []
            peak_levels: List[float] = []
            peak_counts: List[float] = []

            def _extract_trailing_number(value: str) -> Optional[float]:
                matches = re.findall(r"-?\d+(?:\.\d+)?", value)
                if not matches:
                    return None
                try:
                    return float(matches[-1])
                except ValueError:
                    return None

            for raw_line in stderr_output.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if 'RMS level dB' in line:
                    number = _extract_trailing_number(line)
                    if number is not None:
                        rms_levels.append(number)
                if 'RMS min dB' in line:
                    number = _extract_trailing_number(line)
                    if number is not None:
                        rms_min_levels.append(number)
                if 'Peak level dB' in line:
                    number = _extract_trailing_number(line)
                    if number is not None:
                        peak_levels.append(number)
                if 'Peak count' in line:
                    number = _extract_trailing_number(line)
                    if number is not None:
                        peak_counts.append(number)

            if not rms_levels:
                return 0.5

            avg_rms = sum(rms_levels) / len(rms_levels)

            if avg_rms >= -20:
                rms_score = 1.0 - (avg_rms + 20) / 40
            else:
                rms_score = max(0.0, (avg_rms + 60) / 40)

            max_peak = max(peak_levels) if peak_levels else None
            if max_peak is None:
                peak_score = 0.7
            else:
                peak_score = 1.0 - max(0.0, max_peak + 3.0) / 6.0

            if rms_min_levels:
                avg_min_rms = sum(rms_min_levels) / len(rms_min_levels)
                dynamic_range = abs(avg_min_rms - avg_rms)
                noise_score = (dynamic_range - 10.0) / 20.0
            else:
                noise_score = 0.5

            if peak_counts:
                avg_peak_count = sum(peak_counts) / len(peak_counts)
                clip_score = 1.0 - min(1.0, avg_peak_count / 5.0)
            else:
                clip_score = 0.9

            def clamp(value: float) -> float:
                return max(0.0, min(1.0, value))

            rms_score = clamp(rms_score)
            peak_score = clamp(peak_score)
            noise_score = clamp(noise_score)
            clip_score = clamp(clip_score)

            weights = self._quality_weights
            final_score = (
                rms_score * weights.get('rms', 0.0)
                + peak_score * weights.get('peak', 0.0)
                + noise_score * weights.get('noise', 0.0)
                + clip_score * weights.get('clip', 0.0)
            )

            # If no weights were provided, fall back to RMS-driven scoring
            if final_score == 0.0 and sum(weights.values()) == 0.0:
                final_score = rms_score

            return clamp(final_score)

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

        speech_people_strategy = self.switching_strategy == 'speech_people'
        people_threshold = 0.1 if speech_people_strategy else 0.0

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

            speech_active = True
            available_people: List[CameraClip] = []
            people_cameras: set = set()
            multiple_people_angles = False
            if speech_people_strategy:
                speech_active = self._segment_has_speech(seg_start, seg_end)
                available_people = [c for c in avail if c.people_count > people_threshold]
                people_cameras = {c.camera for c in available_people}
                multiple_people_angles = len(people_cameras) >= 2

            # VIDEO selection per strategy (speech-aware)
            selected_v: Optional[CameraClip] = None
            if speech_people_strategy and (not speech_active) and available_people:
                selected_v = max(available_people, key=lambda x: x.people_count)
            if selected_v is None:
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
            needs_review = speech_people_strategy and (not speech_active) and multiple_people_angles
            video_segments.append(CompositionSegment(
                camera=selected_v.camera,
                clip_path=selected_v.path,
                start_time=seg_start,
                duration=seg_dur,
                source_start=v_source_start,
                needs_review=needs_review,
                speech_active=speech_active,
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
            # Apply dynamic alignment (base + drift * t) to audio source only
            if self._alignment_enabled and self._alignment_offsets:
                base = self._alignment_offsets.get(selected_a.camera, 0.0)
                drift = self._alignment_drifts.get(selected_a.camera, 0.0)
                offset_at_t = float(base + drift * seg_start)
                a_source_start = max(0.0, a_source_start + offset_at_t)
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
                need_overlay = (
                    (self._overlay_enabled and self._event_start is not None)
                    or bool(self._review_segments)
                )
                if need_overlay:
                    total_duration = sum(s.duration for s in video_timeline)
                    ass_path = self._generate_timestamp_ass(
                        tmpdir=tmpdir,
                        total_duration=total_duration,
                        event_start=self._event_start,
                        dst_offset_hours=self._overlay_dst_hours,
                        include_timestamp=self._overlay_enabled and self._event_start is not None,
                        review_segments=self._review_segments,
                    )
                    if ass_path:
                        overlayed_video_path = os.path.join(tmpdir, 'video_overlay.mp4')
                        cmd = [
                            'ffmpeg',
                            '-y',
                            '-loglevel', 'error',
                            '-i', overlay_input_path,
                            '-vf', f"subtitles='{ass_path}'",
                            '-c:v', 'libx264',
                            '-preset', 'fast',
                            '-crf', '22',
                            overlayed_video_path
                        ]
                        res2 = subprocess.run(cmd, capture_output=True)
                        if res2.returncode == 0:
                            overlay_input_path = overlayed_video_path
                        else:
                            logging.warning("Failed to apply overlay subtitles, continuing without it: %s", res2.stderr.decode())

                # Step 3: Extract, clean, and concatenate audio segments to span entire event
                cleanup_filter = self._build_audio_cleanup_filter()
                audio_seg_files = []
                for i, segment in enumerate(audio_timeline):
                    a_seg_path = os.path.join(tmpdir, f"audio_{i:03d}.wav")
                    base_command = [
                        'ffmpeg',
                        '-y',
                        '-loglevel', 'error',
                        '-ss', str(segment.source_start),
                        '-i', segment.clip_path,
                        '-t', str(segment.duration),
                        '-vn',
                    ]

                    command = list(base_command)
                    current_filter = cleanup_filter
                    if current_filter:
                        command.extend(['-af', current_filter])
                    command.extend([
                        '-acodec', 'pcm_s16le',
                        '-ar', '48000',
                        '-ac', '2',
                        a_seg_path
                    ])

                    result = subprocess.run(command, capture_output=True)
                    if result.returncode != 0:
                        if current_filter:
                            logging.warning(
                                "Audio cleanup filter failed for segment %d (%s); retrying without cleanup. Error: %s",
                                i,
                                segment.clip_path,
                                result.stderr.decode().strip(),
                            )
                            self._cleanup_enabled = False
                            self._cleanup_filter_string = None
                            cleanup_filter = None
                            fallback_command = list(base_command)
                            fallback_command.extend([
                                '-acodec', 'pcm_s16le',
                                '-ar', '48000',
                                '-ac', '2',
                                a_seg_path
                            ])
                            result = subprocess.run(fallback_command, capture_output=True)
                        if result.returncode != 0:
                            logging.error(f"Failed to extract audio segment {i}: {result.stderr.decode()}")
                            return False
                    audio_seg_files.append(a_seg_path)

                # Step 2b: Stitch audio with optional crossfades using filter_complex
                audio_path_wav = os.path.join(tmpdir, 'audio_full.wav')
                if len(audio_seg_files) == 1 or self._audio_crossfade_s <= 0.0:
                    # Simple concat copy fallback (single file or disabled crossfade)
                    audio_concat_list = os.path.join(tmpdir, 'audio_concat.txt')
                    with open(audio_concat_list, 'w') as f:
                        for seg_file in audio_seg_files:
                            f.write(f"file '{seg_file}'\n")
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
                else:
                    # Build acrossfade chain: [0:a][1:a] -> A01, [A01][2:a] -> A02, ...
                    cmd = ['ffmpeg', '-y', '-loglevel', 'error']
                    for seg in audio_seg_files:
                        cmd.extend(['-i', seg])
                    # Build filter graph
                    cf = max(0.01, min(5.0, self._audio_crossfade_s))
                    filters: List[str] = []
                    last_label = None
                    n = len(audio_seg_files)
                    if n == 2:
                        filters.append(f"[0:a][1:a]acrossfade=d={cf}:c1=tri:c2=tri[aout]")
                        out_label = 'aout'
                    else:
                        # First pair
                        filters.append(f"[0:a][1:a]acrossfade=d={cf}:c1=tri:c2=tri[a01]")
                        last_label = 'a01'
                        for idx in range(2, n):
                            next_label = f"a0{idx}"
                            filters.append(
                                f"[{last_label}][{idx}:a]acrossfade=d={cf}:c1=tri:c2=tri[{next_label}]"
                            )
                            last_label = next_label
                        out_label = last_label or '0:a'

                    cmd.extend([
                        '-filter_complex',
                        '; '.join(filters),
                        '-map', f'[{out_label}]',
                        '-c:a', 'pcm_s16le',
                        audio_path_wav,
                    ])
                    result = subprocess.run(cmd, capture_output=True)
                    if result.returncode != 0:
                        logging.error(f"Audio acrossfade stitching failed: {result.stderr.decode()}")
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
                seg.needs_review == current.needs_review and
                seg.speech_active == current.speech_active and
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
        event_start: Optional[datetime],
        dst_offset_hours: int = 1,
        include_timestamp: bool = True,
        review_segments: Optional[List[Tuple[float, float]]] = None,
    ) -> Optional[str]:
        """Generate an ASS subtitle file for timestamps and review indicators."""
        has_timestamp = include_timestamp and event_start is not None
        review_segments = review_segments or []
        has_review = bool(review_segments)

        if not has_timestamp and not has_review:
            return None

        try:
            ass_lines: List[str] = []
            ass_lines.append("[Script Info]")
            ass_lines.append("ScriptType: v4.00+")
            ass_lines.append("PlayResX: 1920")
            ass_lines.append("PlayResY: 1080")
            ass_lines.append("")
            ass_lines.append("[V4+ Styles]")
            ass_lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")

            if has_timestamp:
                timestamp_style = (
                    f"Style: Overlay,{self._overlay_font},{self._overlay_font_size},&H00FFFFFF,&H000000FF,&H55000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,3,20,{self._overlay_margin_r},{self._overlay_margin_v},1"
                )
                ass_lines.append(timestamp_style)

            if has_review:
                review_style = (
                    f"Style: ReviewIndicator,{self._overlay_font},{int(self._overlay_font_size * 0.9)},&H00FFFFFF,&H000000FF,&H702151FF,&H00000000,0,0,0,0,100,100,0,0,1,2,0,9,20,{self._overlay_margin_r},{max(10, self._overlay_margin_v)},1"
                )
                ass_lines.append(review_style)

            ass_lines.append("")
            ass_lines.append("[Events]")
            ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

            def fmt_ass_time(seconds: float) -> str:
                seconds = max(0.0, seconds)
                h = int(seconds // 3600)
                m = int((seconds % 3600) // 60)
                s = int(seconds % 60)
                cs = int(round((seconds - int(seconds)) * 100))
                return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

            if has_timestamp:
                total_secs = int(max(0, int(total_duration + 0.5)))
                base = event_start + timedelta(hours=dst_offset_hours)  # type: ignore[operator]
                for t in range(0, total_secs):
                    wall = base + timedelta(seconds=t)
                    text = wall.strftime("%Y-%m-%d %H:%M:%S")
                    start_ts = fmt_ass_time(t)
                    end_ts = fmt_ass_time(t + 1)
                    ass_lines.append(f"Dialogue: 0,{start_ts},{end_ts},Overlay,,0000,0000,0000,,{text}")

            if has_review:
                for start, end in review_segments:
                    clamped_start = max(0.0, min(total_duration, start))
                    clamped_end = max(clamped_start + 0.1, min(total_duration, end))
                    start_ts = fmt_ass_time(clamped_start)
                    end_ts = fmt_ass_time(clamped_end)
                    ass_lines.append(
                        "Dialogue: 1,{start},{end},ReviewIndicator,,0000,0000,0000,,REVIEW ALT ANGLES".format(
                            start=start_ts,
                            end=end_ts,
                        )
                    )

            ass_path = os.path.join(tmpdir, 'overlay.ass')
            with open(ass_path, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(ass_lines))
            return ass_path
        except Exception as exc:  # pragma: no cover - file IO errors
            logging.warning("Failed to generate ASS overlay: %s", exc)
            return None
