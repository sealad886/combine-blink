"""
Rendering Module

FFmpeg-based video rendering with single-pass and multi-pass strategies.

Classes:
- CompositionRenderer: Abstract base renderer
- SinglePassRenderer: One-pass filter_complex rendering
- MultiPassRenderer: Multi-pass fallback for complex compositions

Notes
- This module reuses the centralized AudioProcessor for audio stitching
    and the centralized OverlayGenerator for timestamp/review overlays.
- Timeline segments are expected to be the legacy-compatible format from
    composition.timeline (with `clip_path`, `start`, `end`, `source_start`, etc.).

Author: Phase 4-5 implementation
Status: Initial implementation
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

# Dedicated renderer logger namespace for pipeline clarity
logger = logging.getLogger("pipeline.render")

from .audio import AudioProcessor
from .config import AudioMixConfig, CompositionConfig
from .overlay import OverlayGenerator
from .timeline import CameraClip, CompositionSegment, Timeline


class CompositionRenderer(ABC):
    """Abstract base class for composition renderers."""

    def __init__(self, config: CompositionConfig):
        """Initialize renderer with configuration."""
        self.config = config
        # Centralized processors
        self.audio_processor = AudioProcessor(
            cleanup=self.config.audio_cleanup,
            mix=self.config.audio_mix,
        )
        self.overlay_generator = OverlayGenerator(self.config.timestamp_overlay)

    @abstractmethod
    def render(
        self,
        clips: List[CameraClip],
        timeline: Timeline,
        output_path: Path,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> bool:
        """Render composition to output file."""
        pass

    # --- Shared helpers ---
    def _video_codec_args(self) -> List[str]:
        """Return ffmpeg args for chosen video encoder based on config.encoding.
        
        MPS Optimization: VideoToolbox on Apple Silicon supports constant quality mode
        (-q:v) since FFmpeg 4.4+, which provides better quality/speed tradeoff than
        bitrate mode. Use -q:v 50-70 for excellent quality (higher = better, 1-100 scale).
        """
        enc = self.config.encoding
        if getattr(enc, 'use_hw_encode', True):
            # Hardware encoder (macOS videotoolbox on Apple Silicon by default)
            codec = getattr(enc, 'hw_codec', 'h264_videotoolbox') or 'h264_videotoolbox'
            
            # MPS Optimization: Use constant quality mode if quality value specified
            # Otherwise fall back to bitrate mode for backward compatibility
            quality = getattr(enc, 'quality', None)  # -q:v value (1-100, higher=better)
            
            args = ['-c:v', codec]
            
            # MPS Optimization: Add VideoToolbox-specific performance flags
            # -realtime 0: Disable realtime mode for better quality (default is 1)
            # -allow_sw 1: Allow software fallback if hardware unavailable
            # -require_sw 0: Prefer hardware encoding
            if 'videotoolbox' in codec:
                args.extend(['-realtime', '0', '-allow_sw', '1'])
            
            if quality is not None and 1 <= quality <= 100:
                # Constant quality mode (recommended for Apple Silicon)
                args.extend(['-q:v', str(int(quality))])
            else:
                # Bitrate mode (legacy compatibility)
                bitrate = getattr(enc, 'bitrate', '8000k') or '8000k'
                args.extend(['-b:v', str(bitrate)])
            
            # MPS Optimization: Use optimal pixel format for VideoToolbox
            # p010le for 10-bit quality on newer hardware, yuv420p for compatibility
            pix_fmt = getattr(enc, 'pix_fmt', 'yuv420p') or 'yuv420p'
            args.extend(['-pix_fmt', pix_fmt])
            
            return args
        
        # Software x264 fallback
        preset = getattr(enc, 'x264_preset', None) or 'veryfast'
        crf = getattr(enc, 'x264_crf', None) or 22
        return ['-c:v', 'libx264', '-preset', str(preset), '-crf', str(crf), '-pix_fmt', 'yuv420p']

    def _probe_video_dimensions(self, path: str) -> Tuple[int, int]:
        """Return (width, height) for the first video stream via ffprobe; fallback to 1920x1080."""
        try:
            res = subprocess.run(
                [
                    'ffprobe', '-v', 'error', '-hide_banner', '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height', '-of', 'json', path
                ],
                capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL
            )
            data = json.loads(res.stdout or '{}')
            streams = data.get('streams') or []
            if streams:
                w = int(streams[0].get('width') or 1920)
                h = int(streams[0].get('height') or 1080)
                # enforce even dimensions
                w -= (w % 2)
                h -= (h % 2)
                return max(2, w), max(2, h)
        except Exception:
            pass
        return 1920, 1080

    def _probe_has_audio(self, path: str) -> bool:
        """Return True if input has at least one audio stream."""
        try:
            res = subprocess.run(
                [
                    'ffprobe', '-v', 'error', '-hide_banner', '-select_streams', 'a',
                    '-show_entries', 'stream=index', '-of', 'csv=p=0', path
                ],
                capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL
            )
            out = (res.stdout or '').strip()
            return bool(out)
        except Exception:
            return True  # assume yes to avoid being over-restrictive

    @staticmethod
    def _review_intervals(timeline: Timeline) -> List[Tuple[float, float]]:
        """Extract merged review intervals from segments with needs_review=True."""
        raw: List[Tuple[float, float]] = []
        for seg in timeline:
            try:
                if getattr(seg, 'needs_review', False):
                    start = float(getattr(seg, 'start_time', getattr(seg, 'start')))
                    dur = float(getattr(seg, 'duration'))
                    raw.append((start, start + max(0.0, dur)))
            except Exception:
                continue
        if not raw:
            return []
        # Merge overlapping
        raw.sort(key=lambda x: x[0])
        merged = [raw[0]]
        for s, e in raw[1:]:
            ls, le = merged[-1]
            if s <= le + 1e-3:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))
        return merged


class SinglePassRenderer(CompositionRenderer):
    """Single-pass filter_complex rendering (faster)."""

    def render(
        self,
        clips: List[CameraClip],
        timeline: Timeline,
        output_path: Path,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> bool:
        """Render in one pass using filter_complex.

        Notes
        - Audio timeline currently mirrors the video timeline.
        - Timestamp overlay requires event_start, which is not provided here;
          we still emit review banners when segments are flagged.
        """
        if not timeline:
            return False

        # Determine unique input paths across timeline
        unique_paths: List[str] = []
        index_by_path: Dict[str, int] = {}
        def _add(p: str):
            if p not in index_by_path:
                index_by_path[p] = len(unique_paths)
                unique_paths.append(p)
        for seg in timeline:
            _add(str(getattr(seg, 'clip_path')))

        # Probe reference resolution
        ref_w, ref_h = self._probe_video_dimensions(unique_paths[0])

        # Build overlay (review indicators only without timestamps)
        ass_path: Optional[str] = None
        review_segments = self._review_intervals(timeline)
        need_overlay = bool(review_segments) or bool(self.config.timestamp_overlay.enabled and False)
        if need_overlay:
            total_duration = sum(float(getattr(s, 'duration')) for s in timeline)
            ass_path = self.overlay_generator.generate_ass_file(
                total_duration=total_duration,
                event_start=None,
                dst_offset_hours=self.config.timestamp_overlay.dst_offset_hours,
                include_timestamp=False,
                review_segments=review_segments,
                tmpdir=None,
            )

        # Build filter graph
        filters: List[str] = []

        # Video trims
        v_labels: List[str] = []
        for idx, seg in enumerate(timeline):
            ip = index_by_path[str(getattr(seg, 'clip_path'))]
            # timeline CompositionSegment can have start_time or start
            start = float(getattr(seg, 'source_start', 0.0))
            dur = float(getattr(seg, 'duration'))
            end = max(0.0, start + dur)
            vlab = f"v{idx}"
            v_labels.append(vlab)
            filters.append(
                f"[{ip}:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
                f"scale={ref_w}:{ref_h}:force_original_aspect_ratio=decrease,"
                f"pad={ref_w}:{ref_h}:(({ref_w}-iw)/2):(({ref_h}-ih)/2):color=black,format=yuv420p,setsar=1[{vlab}]"
            )

        # Video concat and optional ASS subtitles
        v_inputs = ''.join(f'[{label}]' for label in v_labels)
        filters.append(f"{v_inputs}concat=n={len(v_labels)}:v=1:a=0[vcat]")
        vout = 'vcat'
        if ass_path:
            # Use centralized OverlayGenerator escaping to be safe
            ass_escaped = self.overlay_generator._escape_path(ass_path)  # type: ignore[attr-defined]
            filters.append(f"[vcat]subtitles='{ass_escaped}'[vout]")
            vout = 'vout'

        # Audio trims
        a_labels: List[str] = []
        has_audio_map: Dict[str, bool] = {p: self._probe_has_audio(p) for p in unique_paths}
        for idx, seg in enumerate(timeline):
            ip = index_by_path[str(getattr(seg, 'clip_path'))]
            start = float(getattr(seg, 'source_start', 0.0))
            dur = float(getattr(seg, 'duration'))
            end = max(0.0, start + dur)
            alab = f"a{idx}"
            a_labels.append(alab)
            if has_audio_map.get(unique_paths[ip], True):
                filters.append(f"[{ip}:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[{alab}]")
            else:
                filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.3f},asetpts=PTS-STARTPTS[{alab}]")

        # Audio stitch: acrossfade ladder via AudioProcessor, else concat
        if not a_labels:
            filters.append("anullsrc=r=48000:cl=stereo[asilent]")
            aout = 'asilent'
        elif len(a_labels) == 1 or float(self.config.audio_mix.crossfade_seconds) <= 0.0:
            a_inputs = ''.join(f'[{label}]' for label in a_labels)
            filters.append(f"{a_inputs}concat=n={len(a_labels)}:v=0:a=1[acat]")
            aout = 'acat'
        else:
            cf = max(0.01, min(5.0, float(self.config.audio_mix.crossfade_seconds)))
            filters_str, aout = self.audio_processor.build_acrossfade_chain(
                a_labels,
                duration=cf,
                curve1=self.config.audio_mix.curve1,
                curve2=self.config.audio_mix.curve2,
                overlap=self.config.audio_mix.overlap,
                output_label='afx',
            )
            if filters_str:
                filters.append(filters_str)

        # Optional audio cleanup after stitching
        a_cleanup = self.audio_processor.build_cleanup_filter()
        if a_cleanup and aout:
            filters.append(f"[{aout}]{a_cleanup}[aout]")
            aout = 'aout'

        # Assemble command
        cmd: List[str] = ['ffmpeg', '-y', '-nostdin', '-loglevel', 'error']
        for p in unique_paths:
            cmd.extend(['-i', p])
        cmd.extend([
            '-filter_complex', '; '.join(filters),
            '-map', f'[{vout}]',
            '-map', f'[{aout}]',
        ])
        # Video codec args
        cmd.extend(self._video_codec_args())
        # Audio encode
        cmd.extend(['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(output_path)])

        logger.info(
            "SinglePass | inputs=%d | vsegs=%d | asegs=%d | out=%s",
            len(unique_paths), len(v_labels), len(a_labels), str(output_path)
        )
        logger.debug("SinglePass | cmd=%s", ' '.join(cmd)[:2000])

        res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
        if res.returncode != 0:
            # Surface a concise error; leave full stderr in logs when needed
            snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
            logger.error(snippet)
            return False
        try:
            size = output_path.stat().st_size
            logger.info("SinglePass | complete | size=%.2f MB", size / (1024*1024))
            if size == 0:
                logger.error("SinglePass | produced empty file")
                return False
        except Exception:
            pass
        logger.info("SinglePass | success")
        return True


class MultiPassRenderer(CompositionRenderer):
    """Multi-pass rendering fallback for complex compositions."""

    def render(
        self,
        clips: List[CameraClip],
        timeline: Timeline,
        output_path: Path,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> bool:
        """Render in multiple passes (extract/concat video, overlay, stitch audio, mux)."""
        if not timeline:
            return False

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            if progress_callback:
                try:
                    progress_callback(0.02)
                except Exception:
                    pass
            logger.info("MultiPass | step=extract | segments=%d", len(timeline))

            # MPS OPTIMIZATION: Extract video segments in parallel using ThreadPoolExecutor
            # This leverages multiple cores on Apple Silicon for faster I/O operations
            segment_files: List[Path] = []
            max_workers = min(4, len(timeline))  # Limit to 4 parallel extractions
            
            def extract_segment(args):
                """Extract a single video segment."""
                idx, seg = args
                seg_path = tmp / f"segment_{idx:03d}.mp4"
                command = [
                    'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                    '-ss', f"{float(getattr(seg, 'source_start', 0.0)):.3f}",
                    '-i', str(getattr(seg, 'clip_path')),
                    '-t', f"{float(getattr(seg, 'duration', 0.0)):.3f}",
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-an', str(seg_path)
                ]
                logger.debug("MultiPass | extract_cmd=%s", ' '.join(command)[:2000])
                res = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL)
                if res.returncode != 0:
                    snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                    logger.error(snippet)
                    return None
                return (idx, seg_path)
            
            # Execute extractions in parallel
            segment_map = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(extract_segment, (i, seg)): i for i, seg in enumerate(timeline)}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        idx, seg_path = result
                        segment_map[idx] = seg_path
            
            # Build ordered segment list
            for i in range(len(timeline)):
                if i in segment_map:
                    segment_files.append(segment_map[i])
                else:
                    logger.error("MultiPass | segment %d extraction failed", i)
                    return False

            # Step 2: Concatenate video segments
            if progress_callback:
                try:
                    progress_callback(0.20)
                except Exception:
                    pass
            logger.info("MultiPass | step=concat_video | n=%d", len(segment_files))
            concat_list = tmp / 'concat_list.txt'
            concat_list.write_text(''.join([f"file '{p}'\n" for p in segment_files]), encoding='utf-8')
            video_only = tmp / 'video_only.mp4'
            concat_cmd = [
                'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                '-f', 'concat', '-safe', '0', '-i', str(concat_list),
                '-c', 'copy', str(video_only)
            ]
            logger.debug("MultiPass | concat_cmd=%s", ' '.join(concat_cmd)[:2000])
            res = subprocess.run(concat_cmd, capture_output=True, stdin=subprocess.DEVNULL)
            if res.returncode != 0:
                snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                logger.error(snippet)
                return False

            # Step 3: Optional overlay via centralized generator (review banners only here)
            overlay_input = video_only
            review_segments = self._review_intervals(timeline)
            need_overlay = bool(review_segments)
            if need_overlay:
                total_duration = sum(float(getattr(s, 'duration')) for s in timeline)
                ass_path = self.overlay_generator.generate_ass_file(
                    total_duration=total_duration,
                    event_start=None,
                    dst_offset_hours=self.config.timestamp_overlay.dst_offset_hours,
                    include_timestamp=False,
                    review_segments=review_segments,
                    tmpdir=tmp,
                )
                if ass_path:
                    overlayed = tmp / 'video_overlay.mp4'
                    logger.info("MultiPass | step=overlay | ass=%s", str(ass_path))
                    overlay_cmd = [
                        'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                        '-i', str(overlay_input),
                        '-vf', f"subtitles='{ass_path}'",
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', str(overlayed)
                    ]
                    logger.debug("MultiPass | overlay_cmd=%s", ' '.join(overlay_cmd)[:2000])
                    res2 = subprocess.run(overlay_cmd, capture_output=True, stdin=subprocess.DEVNULL)
                    if res2.returncode == 0:
                        overlay_input = overlayed
                    else:
                        snippet = (res2.stderr or b'').decode(errors='ignore')[:1000]
                        logger.error(snippet)

            # Step 4: Extract, cleanup audio segments as WAV
            if progress_callback:
                try:
                    progress_callback(0.35)
                except Exception:
                    pass
            logger.info("MultiPass | step=extract_audio | segments=%d", len(timeline))
            cleanup_filter = self.audio_processor.build_cleanup_filter()
            
            # MPS OPTIMIZATION: Extract audio segments in parallel
            audio_seg_files: List[Path] = []
            max_audio_workers = min(4, len(timeline))
            
            def extract_audio_segment(args):
                """Extract a single audio segment."""
                idx, seg = args
                a_seg = tmp / f"audio_{idx:03d}.wav"
                cmd = [
                    'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                    '-ss', f"{float(getattr(seg, 'source_start', 0.0)):.3f}",
                    '-i', str(getattr(seg, 'clip_path')),
                    '-t', f"{float(getattr(seg, 'duration', 0.0)):.3f}",
                    '-vn'
                ]
                if cleanup_filter:
                    cmd.extend(['-af', cleanup_filter])
                cmd.extend(['-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(a_seg)])
                logger.debug("MultiPass | audio_extract_cmd=%s", ' '.join(cmd)[:2000])
                res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
                if res.returncode != 0:
                    snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                    logger.error(snippet)
                    return None
                return (idx, a_seg)
            
            # Execute audio extractions in parallel
            audio_map = {}
            with ThreadPoolExecutor(max_workers=max_audio_workers) as executor:
                futures = {executor.submit(extract_audio_segment, (i, seg)): i for i, seg in enumerate(timeline)}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        idx, a_seg = result
                        audio_map[idx] = a_seg
            
            # Build ordered audio segment list
            for i in range(len(timeline)):
                if i in audio_map:
                    audio_seg_files.append(audio_map[i])
                else:
                    logger.error("MultiPass | audio segment %d extraction failed", i)
                    return False

            # Step 5: Stitch audio with acrossfade via AudioProcessor
            if progress_callback:
                try:
                    progress_callback(0.55)
                except Exception:
                    pass
            logger.info("MultiPass | step=audio_stitch")
            audio_full = tmp / 'audio_full.wav'
            if len(audio_seg_files) <= 1 or float(self.config.audio_mix.crossfade_seconds) <= 0.0:
                # Simple concat copy
                audio_concat_list = tmp / 'audio_concat.txt'
                audio_concat_list.write_text(''.join([f"file '{p}'\n" for p in audio_seg_files]), encoding='utf-8')
                simple_audio_concat = [
                    'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                    '-f', 'concat', '-safe', '0', '-i', str(audio_concat_list),
                    '-c', 'copy', str(audio_full)
                ]
                logger.debug("MultiPass | audio_concat_cmd=%s", ' '.join(simple_audio_concat)[:2000])
                res = subprocess.run(simple_audio_concat, capture_output=True, stdin=subprocess.DEVNULL)
                if res.returncode != 0:
                    snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                    logger.error(snippet)
                    return False
            else:
                cmd = ['ffmpeg', '-y', '-nostdin', '-loglevel', 'error']
                for p in audio_seg_files:
                    cmd.extend(['-i', str(p)])
                cf = max(0.01, min(5.0, float(self.config.audio_mix.crossfade_seconds)))
                # Build acrossfade from input indices 0..n-1
                input_labels = [f"{i}:a" for i in range(len(audio_seg_files))]
                filters_str, out_label = self.audio_processor.build_acrossfade_chain(
                    input_labels,
                    duration=cf,
                    curve1=self.config.audio_mix.curve1,
                    curve2=self.config.audio_mix.curve2,
                    overlap=self.config.audio_mix.overlap,
                    output_label='aout',
                )
                logger.info("MultiPass | step=audio_stitch_acrossfade | n=%d | duration=%.2fs", len(audio_seg_files), cf)
                cmd.extend([
                    '-filter_complex', filters_str,
                    '-map', f'[{out_label}]',
                    '-c:a', 'pcm_s16le', str(audio_full)
                ])
                logger.debug("MultiPass | audio_stitch_cmd=%s", ' '.join(cmd)[:2000])
                res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
                if res.returncode != 0:
                    snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                    logger.error(snippet)
                    return False

            # Step 6: Mux video and audio into final output
            if progress_callback:
                try:
                    progress_callback(0.85)
                except Exception:
                    pass
            logger.info("MultiPass | step=mux | out=%s", str(output_path))
            cmd = [
                'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
                '-i', str(overlay_input), '-i', str(audio_full),
                *self._video_codec_args(),
                '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(output_path)
            ]
            logger.debug("MultiPass | mux_cmd=%s", ' '.join(cmd)[:2000])
            res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
            if res.returncode != 0:
                snippet = (res.stderr or b'').decode(errors='ignore')[:1000]
                logger.error(snippet)
                return False
            if progress_callback:
                try:
                    progress_callback(1.0)
                except Exception:
                    pass
            try:
                size = output_path.stat().st_size
                logger.info("MultiPass | complete | size=%.2f MB", size / (1024*1024))
                if size == 0:
                    logger.error("MultiPass | produced empty file")
                    return False
            except Exception:
                pass
            logger.info("MultiPass | success")
            return True


__all__ = ['CompositionRenderer', 'SinglePassRenderer', 'MultiPassRenderer']
