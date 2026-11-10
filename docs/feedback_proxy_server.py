"""Chalkpress 反馈代理服务（ECS 参考实现）——与 pptcopilot-ecs lead-server 同模式。

客户端发布版把反馈 POST 到本服务（URL/口令经 CI secrets 编译进 Rust 壳），
本服务持有飞书凭据写多维表格：secret 永不进入客户端二进制。

部署：
    pip install flask requests gunicorn
    export CHALKPRESS_FEEDBACK_TOKEN=<共享口令，与 CI secret CHALKPRESS_FEEDBACK_TOKEN 一致>
    export FEISHU_APP_ID=...  FEISHU_APP_SECRET=...
    export FEISHU_BITABLE_APP_TOKEN=...  FEISHU_BITABLE_TABLE_ID=<反馈表 ID>
    gunicorn -w 2 -b 127.0.0.1:8100 feedback_proxy_server:app   # 前置 nginx + TLS

客户端对应 secrets：CHALKPRESS_FEEDBACK_URL（对外 https 地址）+ CHALKPRESS_FEEDBACK_TOKEN。
安全边界：只转发用户主动填写的反馈字段（类型/内容/联系方式/版本/OS/可选日志摘要），
不落盘、不打访问日志内容；口令只做防滥用门槛（可逆，不冒充安全边界）。
"""
from __future__ import annotations

import os
import time

import requests
from flask import Flask, jsonify, request

FEISHU = "https://open.feishu.cn"
TOKEN_API = "/open-apis/auth/v3/tenant_access_token/internal"
RECORD_API = "/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
TIMEOUT = 10
RETRIES = 2

TYPES = {"bug": "bug 报告", "suggestion": "功能建议",
         "question": "使用问题", "other": "其他"}
# 字段名与客户端 chalkpress/feedback.py 及多维表格精确对齐
FIELDS = ("反馈类型", "内容摘要", "联系方式", "应用版本", "操作系统", "日志摘要")

app = Flask(__name__)
_token: dict[str, float | str] = {"v": "", "deadline": 0.0}


def _tenant_token() -> str | None:
    if _token["v"] and time.monotonic() < _token["deadline"]:
        return _token["v"]
    r = requests.post(FEISHU + TOKEN_API,
                      json={"app_id": os.getenv("FEISHU_APP_ID", ""),
                            "app_secret": os.getenv("FEISHU_APP_SECRET", "")},
                      timeout=TIMEOUT)
    data = r.json()
    tok = data.get("tenant_access_token") or ""
    expire = int(data.get("expire") or 0)
    if r.status_code != 200 or data.get("code") != 0 or not tok:
        return None
    _token.update(v=tok, deadline=time.monotonic() + max(expire - 300, 60))
    return tok


def _to_fields(p: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {"反馈类型": TYPES.get(str(p.get("type")), TYPES["other"]),
                    "内容摘要": str(p.get("content") or ""),
                    "联系方式": str(p.get("contact") or ""),
                    "应用版本": str(p.get("app_version") or ""),
                    "操作系统": str(p.get("os") or "")}
    excerpt = str(p.get("log_excerpt") or "")
    if excerpt:
        fields["日志摘要"] = excerpt[:2000]  # 客户端已截断，这里再兜底一次
    if p.get("ts"):
        try:
            from datetime import datetime
            fields["提交时间"] = int(datetime.fromisoformat(str(p["ts"])).timestamp())
        except ValueError:
            pass
    return {k: v for k, v in fields.items() if v != ""}


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/api/feedback")
def feedback():
    want = os.getenv("CHALKPRESS_FEEDBACK_TOKEN", "").strip()
    if want and request.headers.get("X-Chalkpress-Token") != want:
        return jsonify(ok=False, error="forbidden"), 403
    p = request.get_json(silent=True) or {}
    content = str(p.get("content") or "")
    if not 10 <= len(content) <= 500:
        return jsonify(ok=False, error="content 需 10-500 字"), 400

    app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN", "").strip()
    table_id = os.getenv("FEISHU_BITABLE_TABLE_ID", "").strip()
    if not (app_token and table_id and os.getenv("FEISHU_APP_ID")):
        return jsonify(ok=False, error="服务端凭据未配置"), 503
    url = FEISHU + RECORD_API.format(app_token=app_token, table_id=table_id)
    body = {"fields": _to_fields(p)}
    for attempt in range(1 + RETRIES):
        tok = _tenant_token()
        if tok:
            r = requests.post(url, json=body, timeout=TIMEOUT, headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json; charset=utf-8"})
            data = r.json() if r.status_code == 200 else {}
            if isinstance(data, dict) and data.get("code") == 0:
                return jsonify(ok=True)
        time.sleep(1 + attempt)  # token 失效/瞬断退避后重试
    return jsonify(ok=False, error="上游飞书写入失败"), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8100)
