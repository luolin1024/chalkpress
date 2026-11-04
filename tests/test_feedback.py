# tests/test_feedback.py
"""反馈模块：凭据读取链（env 文件 > 环境变量，缺失 → 入口隐藏）、payload 隐私红线
（不勾日志绝不含日志内容）、bitable 字段映射/截断、token 缓存与提交重试/刷新/降级、
IPC 反馈方法。全部用假 token/假应答，绝不真发飞书。"""
import json
import time

import pytest
import requests

import chalkpress.feedback as feedback

FULL_ENV = """FEISHU_APP_ID=cli_aa61c20847389c03
FEISHU_APP_SECRET=secret-abc
FEISHU_BITABLE_APP_TOKEN=app-token-xyz
FEISHU_BITABLE_TABLE_ID=tbl123
"""

TOKEN_OK = {"code": 0, "tenant_access_token": "t-fake", "expire": 7200}
RECORD_OK = {"code": 0, "msg": "success"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """隔离：清 token 缓存与全部反馈相关环境变量。"""
    feedback.reset_token_cache()
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET",
                "FEISHU_BITABLE_APP_TOKEN", "FEISHU_BITABLE_TABLE_ID",
                "CHALKPRESS_FEEDBACK_ENV"):
        monkeypatch.delenv(key, raising=False)
    yield
    feedback.reset_token_cache()


class FakeResp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


def _stub_feishu(monkeypatch, token_resp=None, record_resps=()):
    """按 URL 路由的 requests.post 替身；记录全部调用（url/json/headers）。"""
    calls = []
    record_iter = iter(record_resps)

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append({"url": url, "json": json, "timeout": timeout,
                      "headers": headers})
        if url.endswith(feedback.TOKEN_API):
            return token_resp
        return next(record_iter, FakeResp(status=500, text="exhausted"))

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def _env_file(tmp_path, monkeypatch, content=FULL_ENV, use_default=False):
    p = tmp_path / "chalkpress-feedback.env"
    p.write_text(content, encoding="utf-8")
    if use_default:  # 走默认路径 ~/.config/chalkpress-feedback.env
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg_dir = tmp_path / ".config"
        cfg_dir.mkdir(exist_ok=True)
        p = cfg_dir / "chalkpress-feedback.env"
        p.write_text(content, encoding="utf-8")
    else:
        monkeypatch.setenv("CHALKPRESS_FEEDBACK_ENV", str(p))
    return p


def _creds_set(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_aa61c20847389c03")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret-abc")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "app-token-xyz")
    monkeypatch.setenv("FEISHU_BITABLE_TABLE_ID", "tbl123")


# ---------- 凭据读取链 ----------

def test_credentials_missing_warns_and_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # 默认路径下无文件
    lines = []
    assert feedback.load_credentials(log=lines.append) is None
    assert len(lines) == 1 and "反馈不可用" in lines[0]
    assert "FEISHU_APP_SECRET" in lines[0]


def test_credentials_from_env_file(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    lines = []
    creds = feedback.load_credentials(log=lines.append)
    assert creds == {"feishu_app_id": "cli_aa61c20847389c03",
                     "feishu_app_secret": "secret-abc",
                     "feishu_bitable_app_token": "app-token-xyz",
                     "feishu_bitable_table_id": "tbl123"}
    assert lines == []  # 完整时不告警


def test_credentials_default_path(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch, use_default=True)
    assert feedback.load_credentials(log=lambda *_: None) is not None


def test_credentials_env_file_wins_over_env_vars(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret-from-env")
    creds = feedback.load_credentials(log=lambda *_: None)
    assert creds is not None
    assert creds["feishu_app_secret"] == "secret-abc"  # env 文件优先
    monkeypatch.setenv("FEISHU_BITABLE_TABLE_ID", "")
    creds = feedback.load_credentials(log=lambda *_: None)
    assert creds["feishu_bitable_table_id"] == "tbl123"


def test_credentials_env_vars_fallback_when_file_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _creds_set(monkeypatch)
    assert feedback.load_credentials(log=lambda *_: None) is not None


def test_credentials_incomplete_returns_none(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch,
              "FEISHU_APP_ID=cli_aa61c20847389c03\nFEISHU_APP_SECRET=s\n")
    lines = []
    assert feedback.load_credentials(log=lines.append) is None
    assert "FEISHU_BITABLE_APP_TOKEN" in lines[0]


def test_env_file_parsing_tolerates_quotes_comments_export(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch, content=(
        "# 注释\n"
        "export FEISHU_APP_ID = 'cli_aa61c20847389c03'\n"
        'FEISHU_APP_SECRET="sec=ret"\n'
        "\n"
        "FEISHU_BITABLE_APP_TOKEN=app-token-xyz\n"
        "FEISHU_BITABLE_TABLE_ID=tbl123\n"))
    creds = feedback.load_credentials(log=lambda *_: None)
    assert creds is not None
    assert creds["feishu_app_id"] == "cli_aa61c20847389c03"
    assert creds["feishu_app_secret"] == "sec=ret"  # 值内 = 不拆


# ---------- payload 隐私红线 ----------

def test_payload_no_log_content_when_unattached(monkeypatch, tmp_path):
    """不勾选日志：即使磁盘上有运行日志，payload 也绝不出现任何日志内容。"""
    d = tmp_path / "logs"
    d.mkdir()
    (d / "chalkpress-1.log").write_text("SECRET /Users/x/video.mp4\n", encoding="utf-8")
    monkeypatch.setattr(feedback, "logs_dir", lambda: d)
    p = feedback.build_payload("bug", "转换崩溃了", "a@b.c", attach_log=False)
    assert p["attach_log"] is False
    assert "log_excerpt" not in p
    assert "SECRET" not in json.dumps(p, ensure_ascii=False)
    assert p["type"] == "bug" and p["contact"] == "a@b.c"
    assert p["app_version"] and p["os"] and p["ts"]


def test_payload_attach_log_tail(monkeypatch, tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    lines = [f"line-{i}" for i in range(60)]
    (d / "chalkpress-old.log").write_text("old\n", encoding="utf-8")
    (d / "chalkpress-new.log").write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(feedback, "logs_dir", lambda: d)
    p = feedback.build_payload("bug", "出错了", "", attach_log=True)
    tail = p["log_excerpt"]
    assert tail.splitlines() == lines[-50:]      # 最近一份 + 末尾 50 行
    assert "old" not in tail


def test_payload_no_log_file_when_attached(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "logs_dir", lambda: tmp_path / "absent")
    p = feedback.build_payload("other", "建议", "", attach_log=True)
    assert p["log_excerpt"] == ""


# ---------- bitable 字段映射 ----------

def test_to_fields_exact_field_names():
    fields = feedback.to_fields({
        "type": "bug", "content": "转换崩溃", "contact": "a@b.c",
        "app_version": "0.5.2", "os": "macOS 15.5",
        "attach_log": True, "log_excerpt": "boom", "ts": "2026-11-05T10:00:00+08:00",
    })
    assert list(fields) == ["反馈类型", "内容", "联系方式", "应用版本",
                            "操作系统", "日志摘要", "提交时间"]
    assert fields["反馈类型"] == "bug 报告"
    assert fields["提交时间"] == "2026-11-05T10:00:00+08:00"


def test_to_fields_no_log_field_when_unattached():
    fields = feedback.to_fields(feedback.build_payload("other", "x" * 20))
    assert "日志摘要" not in fields


def test_to_fields_truncates_long_log():
    fields = feedback.to_fields({"log_excerpt": "L" * (feedback.TEXT_LIMIT + 500)})
    assert fields["日志摘要"].endswith("…（已截断）")
    assert len(fields["日志摘要"]) == feedback.TEXT_LIMIT + len("…（已截断）")


def test_to_fields_unknown_type_falls_back():
    fields = feedback.to_fields({"type": "weird", "content": "x" * 20})
    assert fields["反馈类型"] == "其他"


# ---------- token 缓存 ----------

def test_token_cached_within_ttl(monkeypatch):
    calls = _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK))
    tok1 = feedback.get_tenant_token("aid", "sec", log=lambda *_: None)
    tok2 = feedback.get_tenant_token("aid", "sec", log=lambda *_: None)
    assert tok1 == tok2 == "t-fake"
    assert len(calls) == 1  # 缓存命中，不发第二次


def test_token_refetch_after_expiry(monkeypatch):
    calls = _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK))
    feedback.get_tenant_token("aid", "sec", log=lambda *_: None)
    cache = feedback._token_cache
    assert cache is not None
    cache["deadline"] = time.monotonic() - 1  # 手动判过期
    assert feedback.get_tenant_token("aid", "sec", log=lambda *_: None) == "t-fake"
    assert len(calls) == 2


def test_token_ttl_slack_applied(monkeypatch):
    _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK))
    feedback.get_tenant_token("aid", "sec", log=lambda *_: None)
    cache = feedback._token_cache
    assert cache is not None
    assert cache["deadline"] <= time.monotonic() + 7200 - feedback.TOKEN_TTL_SLACK + 1


def test_token_failure_returns_none(monkeypatch):
    _stub_feishu(monkeypatch,
                 token_resp=FakeResp(status=400, data={"code": 10003, "msg": "bad secret"}))
    assert feedback.get_tenant_token("aid", "sec", log=lambda *_: None) is None
    assert feedback._token_cache is None


# ---------- 提交（重试/刷新/降级语义） ----------

def test_submit_without_credentials_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = _stub_feishu(monkeypatch)
    assert feedback.submit_feedback({"type": "bug", "content": "x"}) is False
    assert calls == []  # 凭据缺失连请求都不该发


def test_submit_success_first_try(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    calls = _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK),
                         record_resps=[FakeResp(data=RECORD_OK)])
    p = feedback.build_payload("bug", "转换崩溃", "a@b.c", attach_log=False)
    assert feedback.submit_feedback(p) is True
    assert len(calls) == 2
    token_call, record_call = calls
    assert token_call["url"].endswith(feedback.TOKEN_API)
    assert token_call["json"] == {"app_id": "cli_aa61c20847389c03",
                                  "app_secret": "secret-abc"}
    assert record_call["url"].startswith(feedback.FEISHU_BASE)
    assert "/bitable/v1/apps/app-token-xyz/tables/tbl123/records" in record_call["url"]
    assert record_call["url"].endswith("?user_id_type=open_id")
    assert record_call["headers"]["Authorization"] == "Bearer t-fake"
    assert record_call["timeout"] == feedback.TIMEOUT
    assert record_call["json"]["fields"]["反馈类型"] == "bug 报告"
    assert "日志摘要" not in record_call["json"]["fields"]  # 未勾日志绝不入表


def test_submit_retries_then_succeeds(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    calls = _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK),
                         record_resps=[FakeResp(status=500),
                                       FakeResp(data={"code": 1254290, "msg": "rate"}),
                                       FakeResp(data=RECORD_OK)])
    assert feedback.submit_feedback({"type": "bug", "content": "x"}) is True
    record_calls = [c for c in calls if c["url"].endswith(
        "/bitable/v1/apps/app-token-xyz/tables/tbl123/records?user_id_type=open_id")]
    token_calls = [c for c in calls if c["url"].endswith(feedback.TOKEN_API)]
    assert len(record_calls) == 1 + feedback.RETRIES  # 总尝试 = 1 + 重试 2
    assert len(token_calls) == 2                      # 重试前刷新 token 一次


def test_submit_fails_after_retries(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    calls = _stub_feishu(monkeypatch, token_resp=FakeResp(data=TOKEN_OK),
                         record_resps=[FakeResp(status=500)] * 3)
    logs = []
    assert feedback.submit_feedback({"type": "bug", "content": "x"},
                                    log=logs.append) is False
    assert any("反馈提交失败" in line for line in logs)  # 降级前有失败说明
    token_calls = [c for c in calls if c["url"].endswith(feedback.TOKEN_API)]
    assert len(token_calls) == 2  # 刷新只一次，不无限刷


def test_submit_token_endpoint_broken_fails_clean(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)
    calls = _stub_feishu(monkeypatch,
                         token_resp=FakeResp(status=400, data={"code": 10003, "msg": "x"}))
    assert feedback.submit_feedback({"type": "bug", "content": "x"}) is False
    assert len(calls) == 3  # 每次尝试都先拿 token，拿不到不写表


def test_submit_network_error_returns_false(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch)

    def boom(url, json=None, timeout=None, headers=None):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", boom)
    assert feedback.submit_feedback({"type": "bug", "content": "x"}) is False


# ---------- IPC ----------

def _server(monkeypatch, tmp_path):
    import io
    from chalkpress.ipc import IPCServer
    monkeypatch.setenv("HOME", str(tmp_path))  # 默认凭据路径下无文件 → 不可用
    return IPCServer(stdin=io.StringIO(), stdout=io.StringIO())


def test_ipc_feedback_status_follows_credentials(monkeypatch, tmp_path):
    s = _server(monkeypatch, tmp_path)
    assert s.handle({"id": 1, "method": "feedback.status"})["result"] == {"enabled": False}
    _creds_set(monkeypatch)  # 环境变量直接注入
    assert s.handle({"id": 2, "method": "feedback.status"})["result"] == {"enabled": True}
    monkeypatch.delenv("FEISHU_BITABLE_TABLE_ID")  # 不完整 → 隐藏
    assert s.handle({"id": 3, "method": "feedback.status"})["result"] == {"enabled": False}


def test_ipc_feedback_submit_rejects_bad_content(monkeypatch, tmp_path):
    s = _server(monkeypatch, tmp_path)
    _creds_set(monkeypatch)
    resp = s.handle({"id": 1, "method": "feedback.submit", "params": {"content": "短"}})
    assert "10-500" in resp["error"]


def test_ipc_feedback_submit_dispatches(monkeypatch, tmp_path):
    s = _server(monkeypatch, tmp_path)
    _creds_set(monkeypatch)
    seen = {}
    monkeypatch.setattr(feedback, "submit_feedback",
                        lambda p, log=print: seen.update(p) or True)
    resp = s.handle({"id": 1, "method": "feedback.submit",
                     "params": {"type": "suggestion", "content": "希望支持批量重命名讲义文件",
                                "contact": "w", "attach_log": False}})
    assert resp["result"] == {"ok": True}
    assert seen["type"] == "suggestion" and seen["attach_log"] is False
