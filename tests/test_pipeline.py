# tests/test_pipeline.py
"""输出布局目录解析：original 平铺 / grouped 分类子目录。"""
from pathlib import Path

from chalkpress.pipeline import _layout_dirs


def test_layout_original_keeps_flat_structure():
    d = _layout_dirs(Path("/out"), "original")
    assert d["md"] == Path("/out")
    assert d["pdf"] == Path("/out")
    assert d["img"] == Path("/out/keyframes")
    assert d["srt"] == Path("/out")


def test_layout_grouped_splits_by_type():
    d = _layout_dirs(Path("/out"), "grouped")
    assert d["md"] == Path("/out/markdown")
    assert d["pdf"] == Path("/out/pdf")
    assert d["img"] == Path("/out/attachments")
    assert d["srt"] == Path("/out")  # 字幕不属于三类，留在根目录


def test_layout_unknown_value_falls_back_original():
    """配置文件手改出未知值时安全回退现状结构。"""
    d = _layout_dirs(Path("/out"), "bogus")
    assert d["img"] == Path("/out/keyframes")
    assert d["md"] == Path("/out")
