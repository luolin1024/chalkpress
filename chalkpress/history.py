"""转换历史档案：成功完成的转换记录（独立于任务队列）。

任务删除会清除产物，但历史保留"曾经转过什么"的档案；列表时动态标记
产物是否仍在。上限 HISTORY_MAX 条，超出丢弃最旧的。
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import history_path

HISTORY_MAX = 500


def load_history() -> list:
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_history(entry: dict) -> None:
    """追加一条记录（最新在前），超限截断最旧的。"""
    entries = load_history()
    entries.insert(0, entry)
    p = history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries[:HISTORY_MAX], ensure_ascii=False, indent=1),
                 encoding="utf-8")


def list_history() -> list:
    """档案（最新在前），附产物存活标记 exists。"""
    out = []
    for h in load_history():
        h = dict(h)
        h["exists"] = bool(h.get("outdir")) and Path(h["outdir"]).exists()
        out.append(h)
    return out


def clear_history() -> None:
    """清空档案（不删除任何产物文件）。"""
    try:
        history_path().unlink()
    except FileNotFoundError:
        pass
