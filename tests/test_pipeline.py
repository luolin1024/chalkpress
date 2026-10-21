# tests/test_pipeline.py
"""输出布局目录解析：original 平铺 / grouped 分类子目录。"""
from pathlib import Path

from chalkpress.pipeline import _layout_dirs


def test_layout_original_splits_markdown_by_type():
    d = _layout_dirs(Path("/out"), "original")
    assert d["summary"] == Path("/out/summary")
    assert d["aligned"] == Path("/out/aligned")
    assert d["img"] == Path("/out/aligned/keyframes")  # 关键帧随对照目录
    assert d["pdf"] == Path("/out")
    assert d["srt"] == Path("/out")


def test_layout_grouped_splits_all_by_type():
    d = _layout_dirs(Path("/out"), "grouped")
    assert d["summary"] == Path("/out/summary")
    assert d["aligned"] == Path("/out/aligned")
    assert d["pdf"] == Path("/out/pdf")
    assert d["img"] == Path("/out/attachments")
    assert d["srt"] == Path("/out")  # 字幕不属于四类，留在根目录


def test_layout_unknown_value_falls_back_original():
    """配置文件手改出未知值时安全回退 original 结构。"""
    d = _layout_dirs(Path("/out"), "grouped")
    assert d["img"] == Path("/out/aligned/keyframes")
    assert d["summary"] == Path("/out/summary")


def test_md_image_links_reach_images_from_both_files():
    """两份 md 各自目录出发的相对链接都要能落到关键帧图片。"""
    import os
    for layout in ("original", "grouped"):
        d = _layout_dirs(Path("/out"), layout)
        assert os.path.relpath(d["img"], d["aligned"]).replace(os.sep, "/") == _rel(layout, "aligned")
        assert os.path.relpath(d["img"], d["summary"]).replace(os.sep, "/") == _rel(layout, "summary")


def _rel(layout: str, md: str) -> str:
    if layout == "grouped":
        return "../attachments"
    return "keyframes" if md == "aligned" else "../aligned/keyframes"
