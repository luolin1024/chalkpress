"""匿名使用统计：征得同意后本地收集，每周批量直写飞书多维表格一次。

隐私边界（与首启同意框承诺一致）：
- 仅当 [privacy] analytics_consent = true 时记录/上报；拒绝或未询问零写入、零网络。
- 事件只含 时间戳/事件名/OS/版本号/极少量计数属性——绝无视频内容、转写文字、
  文件名或任何个人信息。
- 匿名 ID 是本地随机生成的 UUID（首次记录事件时创建），不含硬件/账号信息。
- 上报写开发者 bitable 的独立「统计」表（复用反馈凭据的 app_id/secret，表 ID 由
  FEISHU_BITABLE_ANALYTICS_TABLE_ID 提供）；未配置时事件仅缓存在 config 数据目录
  的 analytics_events.json，永不联网。
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
EVENTS_MAX = 2000            # 长期未配置上报时防文件无限增长
POST_TIMEOUT = 10
ANALYTICS_TABLE_VAR = "FEISHU_BITABLE_ANALYTICS_TABLE_ID"  # bitable 独立统计表

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
    """同步上报一轮：直写 bitable 统计表（复用反馈凭据的 app_id/secret）。
    表 ID 未配置 / 无事件 / 未到周期 → False（留本地）；全部记录成功才清缓存，
    中途失败整批保留，下个周期重发。"""
    table_id = os.getenv(ANALYTICS_TABLE_VAR, "").strip()
    if not table_id:
        return False
    from . import feedback
    creds = feedback.load_credentials(log=lambda *_: None)  # 静默：统计失败不吵
    if not creds:
        return False
    with _lock:
        st = _load_state()
        events = list(st["events"])
        if not events or time.time() - st["last_flush"] < FLUSH_INTERVAL:
            return False
        cid = st["client_id"]
    import requests  # 惰性导入：与 feedback/correct 一致，仅实际上报时加载

    url = (feedback.FEISHU_BASE
           + feedback.RECORD_API.format(app_token=creds["feishu_bitable_app_token"],
                                        table_id=table_id))
    token = feedback.get_tenant_token(creds["feishu_app_id"],
                                      creds["feishu_app_secret"],
                                      log=lambda *_: None)
    if not token:
        return False
    try:
        for e in events:
            r = requests.post(url, json={"fields": {
                "事件": str(e.get("event") or ""),
                "属性": json.dumps(e.get("props") or {}, ensure_ascii=False),
                "操作系统": str(e.get("os") or ""),
                "应用版本": str(e.get("app") or ""),
                "匿名ID": cid,
                "时间": int(e.get("ts") or 0),  # bitable Date 字段：秒级时间戳
            }}, timeout=POST_TIMEOUT, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            })
            data = r.json()
            if r.status_code != 200 or not isinstance(data, dict) or data.get("code") != 0:
                return False
    except Exception:
        return False
    with _lock:  # 上报期间新增的事件留在尾部，只截掉已发出的前 n 条
        st = _load_state()
        st["events"] = st["events"][len(events):]
        st["last_flush"] = int(time.time())
        _save_state(st)
    return True


def maybe_flush_async() -> None:
    """到期则后台线程上报（fire-and-forget）；未同意/未配置/未到期零网络开销。"""
    if load_privacy_consent() is not True:
        return
    if not os.getenv(ANALYTICS_TABLE_VAR, "").strip():
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


def _llm_configured() -> bool:
    """启动时采样 LLM 配置状态（仅布尔，绝不读 key 本身）。"""
    try:
        from .config import load_llm_config
        return load_llm_config() is not None
    except Exception:
        return False


def track_startup() -> None:
    """应用启动埋点（GUI sidecar 与 CLI 各计一次）；统计永不影响功能。"""
    try:
        record("app_start", {"llm": _llm_configured()})
        maybe_flush_async()
    except Exception:
        pass


def track_conversion(pages: int = 0, seconds: float = 0.0,
                     summary: bool = False) -> None:
    """转换完成埋点：仅页数/耗时/是否生成 AI 总结，不含视频名或任何内容。"""
    try:
        record("conversion_done",
               {"pages": int(pages), "seconds": round(float(seconds), 1),
                "summary": bool(summary)})
        maybe_flush_async()
    except Exception:
        pass


def track_batch(videos: int) -> None:
    """批量规模埋点：单次任务的待处理视频数（区分单个 vs 课程目录批量）。"""
    try:
        record("batch_start", {"videos": int(videos)})
    except Exception:
        pass


def track_paused() -> None:
    try:
        record("convert_paused")
    except Exception:
        pass


def track_error() -> None:
    """转换失败埋点：只计数，不含错误文本（可能含文件路径）。"""
    try:
        record("convert_error")
    except Exception:
        pass


def track_feedback(ftype: str, ok: bool) -> None:
    try:
        record("feedback_submit", {"type": str(ftype), "ok": bool(ok)})
    except Exception:
        pass
