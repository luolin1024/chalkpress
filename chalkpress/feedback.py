"""应用内反馈：表单输入 → 飞书开放 API 写多维表格（方案 B：自建应用直连 bitable）。

隐私红线：请求只含用户主动填写的反馈字段 + 可选的运行日志尾部摘录，
绝不携带视频内容/转写文本/流水线产物。凭据缺失/不完整时 GUI 隐藏入口，
本模块 submit_feedback 返回 False 兜底。凭据永不写入仓库/config.toml。
"""
from __future__ import annotations

import os
import platform
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import logs_dir

FEISHU_BASE = "https://open.feishu.cn"
TOKEN_API = "/open-apis/auth/v3/tenant_access_token/internal"
RECORD_API = "/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

TIMEOUT = 10       # 单次请求超时（秒）
RETRIES = 2        # 失败重试次数（总尝试 1 + RETRIES）
TOKEN_TTL_SLACK = 300  # token 提前 5 分钟判过期（expire-300s）
LOG_TAIL_LINES = 50
TEXT_LIMIT = 2000  # 日志摘要超过此长度截断

ENV_FILE_VAR = "CHALKPRESS_FEEDBACK_ENV"
DEFAULT_ENV_FILE = "~/.config/chalkpress-feedback.env"  # 部署时 600 权限
CRED_KEYS = ("FEISHU_APP_ID", "FEISHU_APP_SECRET",
             "FEISHU_BITABLE_APP_TOKEN", "FEISHU_BITABLE_TABLE_ID")

TYPES = {"bug": "bug 报告", "suggestion": "功能建议",
         "question": "使用问题", "other": "其他"}

# payload key → bitable 文本字段名（与开发者建好的多维表格字段精确对齐）
FIELD_NAMES = {"type": "反馈类型", "content": "内容", "contact": "联系方式",
               "app_version": "应用版本", "os": "操作系统",
               "log_excerpt": "日志摘要", "ts": "提交时间"}

_token_cache: dict | None = None  # {"token": str, "deadline": monotonic 秒}


def os_summary() -> str:
    """platform.platform() 的人类摘要：macOS 15.5 / Windows 11 / Linux 6.8…."""
    return " ".join(platform.platform().split("-")[:2])


def latest_log() -> Path | None:
    d = logs_dir()
    if not d.is_dir():
        return None
    logs = sorted(d.glob("chalkpress-*.log"), key=lambda f: f.stat().st_mtime)
    return logs[-1] if logs else None


def read_log_tail(limit: int = LOG_TAIL_LINES) -> str:
    """最近一份运行日志的末尾 limit 行；无日志（未开启保留）返回空串。"""
    p = latest_log()
    if not p:
        return ""
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-limit:])
    except OSError:
        return ""


def build_payload(ftype: str, content: str,
                  contact: str = "", attach_log: bool = False) -> dict:
    """表单输入 → 反馈 payload。attach_log=False 时绝不读取/包含任何日志内容。"""
    p = {
        "type": ftype if ftype in TYPES else "other",
        "content": (content or "").strip(),
        "contact": (contact or "").strip(),
        "app_version": __version__,
        "os": os_summary(),
        "attach_log": bool(attach_log),
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if p["attach_log"]:
        p["log_excerpt"] = read_log_tail()
    return p


def _parse_env_file(path: Path) -> dict[str, str]:
    """极简 dotenv：KEY=VALUE；忽略空行/#；容忍 export 前缀与成对引号；文件缺失返回空。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_credentials(log=print) -> dict[str, str] | None:
    """凭据读取链：CHALKPRESS_FEEDBACK_ENV 指向的 env 文件（默认
    ~/.config/chalkpress-feedback.env，600）> 环境变量直接注入。

    缺失/不完整 → None 并 log 一行 warn（IPC feedback.status 据此让 GUI 隐藏入口）。
    """
    env_path = Path(os.getenv(ENV_FILE_VAR) or DEFAULT_ENV_FILE).expanduser()
    vals = _parse_env_file(env_path)
    for key in CRED_KEYS:  # env 文件优先（空值视为未配置），直接注入的环境变量兜底
        if not vals.get(key):
            vals[key] = os.getenv(key, "").strip()
    creds = {key.lower(): vals[key].strip() for key in CRED_KEYS if vals[key].strip()}
    if len(creds) < len(CRED_KEYS):
        missing = [key for key in CRED_KEYS if key.lower() not in creds]
        log(f"反馈不可用：凭据缺失 {', '.join(missing)}（检查 {env_path} 或环境变量）")
        return None
    return creds


def get_tenant_token(app_id: str, secret: str, log=print) -> str | None:
    """tenant_access_token；内存缓存，expire-300s 提前判过期。失败返回 None。"""
    global _token_cache
    if _token_cache and time.monotonic() < _token_cache["deadline"]:
        return _token_cache["token"]
    import requests  # 惰性导入：与 correct/analyze 一致，仅反馈提交时加载

    try:
        r = requests.post(FEISHU_BASE + TOKEN_API,
                          json={"app_id": app_id, "app_secret": secret},
                          timeout=TIMEOUT)
        data = r.json()
        token = data.get("tenant_access_token") or ""
        expire = int(data.get("expire") or 0)
        if r.status_code != 200 or data.get("code") != 0 or not token:
            log(f"获取飞书 token 失败：HTTP {r.status_code} "
                f"{data.get('msg') or r.text[:80]}")
            return None
    except (ValueError, requests.RequestException) as exc:
        log(f"获取飞书 token 失败：{str(exc)[:120]}")
        return None
    _token_cache = {"token": token,
                    "deadline": time.monotonic() + max(expire - TOKEN_TTL_SLACK, 60)}
    return token


def reset_token_cache() -> None:
    """清空 token 缓存（提交重试时刷新一次用）。"""
    global _token_cache
    _token_cache = None


def to_fields(payload: dict) -> dict[str, str]:
    """payload → bitable fields。只映射 payload 已有键：未勾日志时不含「日志摘要」；
    日志摘要 >2000 字截断；类型映射为中文标签；字段名与表格精确对齐。"""
    fields: dict[str, str] = {}
    for key, name in FIELD_NAMES.items():
        if key not in payload:
            continue
        value = payload[key]
        if key == "type":
            value = TYPES.get(value, TYPES["other"])
        text = str(value)
        if key == "log_excerpt" and len(text) > TEXT_LIMIT:
            text = text[:TEXT_LIMIT] + "…（已截断）"
        fields[name] = text
    return fields


def submit_feedback(payload: dict, log=print) -> bool:
    """写 bitable 记录（user_id_type=open_id），10s 超时；失败重试 2 次，
    其间刷新 token 一次；仍失败返回 False（GUI 降级引导 GitHub Issues）。

    凭据缺失直接 False（正常路径下 GUI 入口已隐藏，此处兜底）。
    """
    creds = load_credentials(log=log)
    if not creds:
        return False
    import requests

    url = FEISHU_BASE + RECORD_API.format(app_token=creds["feishu_bitable_app_token"],
                                          table_id=creds["feishu_bitable_table_id"]) + "?user_id_type=open_id"
    body = {"fields": to_fields(payload)}
    err = ""
    refreshed = False
    for attempt in range(1 + RETRIES):
        if attempt:
            log(f"反馈提交失败，重试 {attempt}/{RETRIES}（{err}）")
        token = get_tenant_token(creds["feishu_app_id"], creds["feishu_app_secret"],
                                 log=log)
        if not token:
            err = "获取 tenant_access_token 失败"
            continue
        try:
            r = requests.post(url, json=body, timeout=TIMEOUT, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            })
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError(f"非 JSON 对象应答：{r.text[:80]}")
            if r.status_code == 200 and data.get("code") == 0:
                return True
            err = (f"HTTP {r.status_code} code={data.get('code')} "
                   f"{data.get('msg') or r.text[:80]}")
        except (ValueError, requests.RequestException) as exc:
            err = str(exc)[:120]
        if not refreshed:  # 整个提交只刷新一次，容忍内存里的 token 过期
            reset_token_cache()
            refreshed = True
    log(f"反馈提交失败：{err}")
    return False
