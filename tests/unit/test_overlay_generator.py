import os
from datetime import datetime

from blink_pipeline.composition.config import TimestampOverlayConfig
from blink_pipeline.composition.overlay import OverlayGenerator


def test_generate_ass_file_timestamp_and_review(tmp_path):
    cfg = TimestampOverlayConfig()
    gen = OverlayGenerator(cfg, output_dir=tmp_path)

    base = datetime(2023, 1, 2, 3, 4, 5)
    ass_path = gen.generate_ass_file(
        total_duration=5.0,
        event_start=base,
        dst_offset_hours=1,
        include_timestamp=True,
        review_segments=[(1.2, 2.7)],
        tmpdir=tmp_path,
    )

    assert os.path.exists(ass_path)
    content = open(ass_path, 'r', encoding='utf-8').read()

    # Styles
    assert 'Style: Overlay,' in content
    assert 'Style: ReviewIndicator,' in content

    # 5 timestamp dialogues (one per second)
    overlay_dialogue_count = content.count(',Overlay,')
    assert overlay_dialogue_count == 5

    # Review banner present
    assert 'REVIEW ALT ANGLES' in content


def test_build_timestamp_filter_writes_ass(tmp_path):
    cfg = TimestampOverlayConfig()
    gen = OverlayGenerator(cfg, output_dir=tmp_path)

    base = datetime(2024, 5, 6, 7, 8, 9)
    filt = gen.build_timestamp_filter(base, duration=3.0)

    # Should return a subtitles filter referencing an .ass file in tmp_path or output dir
    assert filt.startswith("subtitles='")
    assert filt.endswith("'")
