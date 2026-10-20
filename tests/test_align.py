# tests/test_align.py
"""md 构建器：关键帧图片以相对链接内嵌，前缀随输出布局变化。"""
from pathlib import Path

from chalkpress.align import frames_gallery, window_markdown
from chalkpress.keyframes import KeyFrame


def _fixture():
    frames = [KeyFrame(ts=0.0, path=Path("keyframes/00m00s.jpg")),
              KeyFrame(ts=42.0, path=Path("keyframes/00m42s.jpg"))]
    aligned = [{"start": 0.0, "end": 42.0,
                "subs": [{"start": 1.0, "end": 2.0, "text": "开场"}]},
               {"start": 42.0, "end": 60.0, "subs": []}]
    return aligned, frames


def test_window_markdown_embeds_images_default_prefix():
    md = window_markdown(*_fixture())
    assert "![00:00](keyframes/00m00s.jpg)" in md
    assert "![00:42](keyframes/00m42s.jpg)" in md


def test_window_markdown_image_prefix_follows_layout():
    """grouped 布局下 md 在 markdown/ 子目录，链接需带 ../ 前缀。"""
    md = window_markdown(*_fixture(), img_rel="../attachments")
    assert "(../attachments/00m00s.jpg)" in md
    assert "keyframes/" not in md


def test_frames_gallery_lists_all_frames():
    md = frames_gallery(_fixture()[1], img_rel="keyframes")
    assert md.startswith("## 附：关键帧截图")
    assert "![01 · 00:00](keyframes/00m00s.jpg)" in md
    assert "![02 · 00:42](keyframes/00m42s.jpg)" in md
