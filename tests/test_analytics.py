# tests/test_analytics.py
"""匿名统计：同意门禁（未同意零写入零网络）、事件形状、每周批量上报。"""
import json
import sys
import time
import types

import chalkpress.analytics as analytics


def _patch(tmp_path, monkeypatch, consent=None):
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr(analytics, "_state_path",
                        lambda: tmp_path / "analytics_events.json")
    if consent is not None:
        config.save_privacy_consent(consent)


def _state(tmp_path):
    return json.loads((tmp_path / "analytics_events.json").read_text())


def test_no_consent_means_zero_writes(tmp_path, monkeypatch):
    """未询问（null）与拒绝（false）都不落盘——analytics 完全静默。"""
    _patch(tmp_path, monkeypatch, consent=None)
    analytics.track_startup()
    analytics.track_conversion(pages=3, seconds=1.2)
    assert not (tmp_path / "analytics_events.json").exists()
    _patch(tmp_path, monkeypatch, consent=False)
    analytics.record("app_start")
    assert not (tmp_path / "analytics_events.json").exists()


def test_consent_records_anonymous_events(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch, consent=True)
    analytics.track_startup()
    analytics.track_conversion(pages=5, seconds=9.63)
    st = _state(tmp_path)
    assert len(st["client_id"]) == 32  # 本地随机 UUID hex，匿名 ID
    evs = st["events"]
    assert [e["event"] for e in evs] == ["app_start", "conversion_done"]
    assert set(evs[0]) == {"ts", "event", "os", "app", "props"}
    assert evs[1]["props"] == {"pages": 5, "seconds": 9.6}
    assert all("name" not in e and "video" not in e for e in evs)  # 不含内容类字段


def test_client_id_stable_across_records(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch, consent=True)
    analytics.record("a")
    cid = analytics.client_id()
    analytics.record("b")
    assert analytics.client_id() == cid == _state(tmp_path)["client_id"]


def test_flush_without_endpoint_keeps_events_local(tmp_path, monkeypatch):
    """端点未配置：只存不发（零网络），事件保留。"""
    _patch(tmp_path, monkeypatch, consent=True)
    monkeypatch.delenv("POST_CHALKPRESS_ANALYTICS_URL", raising=False)
    analytics.record("app_start")
    assert analytics._flush_once() is False
    assert len(_state(tmp_path)["events"]) == 1


def test_flush_posts_batch_and_clears_when_due(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch, consent=True)
    monkeypatch.setenv("POST_CHALKPRESS_ANALYTICS_URL", "https://example.com/hit")
    analytics.record("app_start")
    analytics.record("conversion_done", {"pages": 2, "seconds": 3.0})
    posts = []

    class FakeResp:
        def raise_for_status(self):
            pass

    fake = types.SimpleNamespace(
        post=lambda url, json=None, timeout=None:
            posts.append((url, json, timeout)) or FakeResp())
    monkeypatch.setitem(sys.modules, "requests", fake)
    assert analytics._flush_once() is True
    url, payload, timeout = posts[0]
    assert url == "https://example.com/hit"
    assert payload["client_id"] == _state(tmp_path)["client_id"]
    assert [e["event"] for e in payload["events"]] == ["app_start", "conversion_done"]
    st = _state(tmp_path)
    assert st["events"] == [] and st["last_flush"] > 0  # 成功后清缓存、记水位


def test_flush_skips_within_week(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch, consent=True)
    monkeypatch.setenv("POST_CHALKPRESS_ANALYTICS_URL", "https://example.com/hit")
    analytics.record("app_start")
    st = _state(tmp_path)
    st["last_flush"] = int(time.time()) - analytics.FLUSH_INTERVAL + 3600
    (tmp_path / "analytics_events.json").write_text(json.dumps(st))
    assert analytics._flush_once() is False
    assert len(_state(tmp_path)["events"]) == 1  # 未到期不发送


def test_public_trackers_never_raise(tmp_path, monkeypatch):
    """统计永不影响功能：内部任何异常都被吞掉。"""
    _patch(tmp_path, monkeypatch, consent=True)
    monkeypatch.setattr(analytics, "record",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    analytics.track_startup()
    analytics.track_conversion(pages=1, seconds=1.0)
