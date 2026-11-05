"""匿名使用统计：征得同意后本地收集，每周批量上报一次（端点未配置只存不发）。

隐私边界（与首启同意框承诺一致）：
- 仅当 [privacy] analytics_consent = true 时记录/上报；拒绝或未询问零写入、零网络。
- 事件只含 时间戳/事件名/OS/版本号/极少量计数属性——绝无视频内容、转写文字、
  文件名或任何个人信息。
- 匿名 ID 是本地随机生成的 UUID（首次记录事件时创建），不含硬件/账号信息。
- 上报端点由环境变量 POST_CHALKPRESS_ANALYTICS_URL 提供；未设置时事件仅缓存在
  config 数据目录的 analytics_events.json，永不联网。
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid

from . import __version__
from .config import config_dir, load_privacy_consent

FLUSH_INTERVAL = 7 * 86400   # 每周至多上报一次
EVENTS_MAX = 2000            # 端点长期未配置时防文件无限增长
POST_TIMEOUT = 10

_lock = threading.Lock()
_flushing = False


def _state_path():
    return config_dir() / "analytics_events.json"


def _load_state() -> dict[str, object]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"client_id": str(data.get("client_id") or ""),
                    "last_flush": int(data.get("last_flush") or 0),
                    "events": [e for e in (data.get("events") or [])
                               if isinstance(e, dict)]}
    except Exception:
        pass
    return {"client_id": "", "last_flush": 0, "events": []}


def _save_state(st: dict[str, object]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def client_id() -> str:
    """本地匿名 UUID；仅在已同意的记录路径里被首次创建。"""
    with _lock:
        st = _load_state()
        if not st["client_id"]:
            st["client_id"] = uuid.uuid4().hex
            _save_state(st)
        return st["client_id"]


def record(event: str, props: dict[str, object] | None = None) -> None:
    """追加一条事件；未同意（None/false）时零写入直接返回。"""
    if load_privacy_consent() is not True:
        return
    entry = {"ts": int(time.time()), "event": event,
             "os": platform.system(), "app": __version__,
             "props": props or {}}
    with _lock:
        st = _load_state()
        if not st["client_id"]:
            st["client_id"] = uuid.uuid4().hex
        st["events"].append(entry)
        if len(st["events"]) > EVENTS_MAX:
            del st["events"][:len(st["events"]) - EVENTS_MAX]
        _save_state(st)


def _flush_once() -> bool:
    """同步上报一轮：到期且配置了端点才 POST；成功后清掉已上报的事件。"""
    url = os.getenv("POST_CHALKPRESS_ANALYTICS_URL", "").strip()
    if not url:
        return False
    with _lock:
        st = _load_state()
        n = len(st["events"])
        if not n or time.time() - st["last_flush"] < FLUSH_INTERVAL:
            return False
        payload = {"client_id": st["client_id"], "events": list(st["events"])}
    import requests  # 惰性导入：与 feedback/correct 一致，仅实际上报时加载

    r = requests.post(url, json=payload, timeout=POST_TIMEOUT)
    r.raise_for_status()
    with _lock:  # 上报期间新增的事件留在尾部，只截掉已发出的前 n 条
        st = _load_state()
        st["events"] = st["events"][n:]
        st["last_flush"] = int(time.time())
        _save_state(st)
    return True


def maybe_flush_async() -> None:
    """到期则后台线程上报（fire-and-forget）；未同意/未配置/未到期零网络开销。"""
    if load_privacy_consent() is not True:
        return
    if not os.getenv("POST_CHALKPRESS_ANALYTICS_URL", "").strip():
        return

    def work():
        global _flushing
        if _flushing:
            return
        _flushing = True
        try:
            _flush_once()
        except Exception:
            pass  # 上报失败静默：缓存保留，下次到期重试
        finally:
            _flushing = False

    threading.Thread(target=work, daemon=True,
                     name="chalkpress-analytics").start()


def track_startup() -> None:
    """应用启动埋点（GUI sidecar 与 CLI 各计一次）；统计永不影响功能。"""
    try:
        record("app_start")
        maybe_flush_async()
    except Exception:
        pass


def track_conversion(pages: int = 0, seconds: float = 0.0) -> None:
    """转换完成埋点：仅页数与耗时计数，不含视频名或任何内容。"""
    try:
        record("conversion_done",
               {"pages": int(pages), "seconds": round(float(seconds), 1)})
        maybe_flush_async()
    except Exception:
        pass
