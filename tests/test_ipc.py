# tests/test_ipc.py
import io
import json
import time

from chalkpress.ipc import sanitize_progress


def make_server():
    from chalkpress.ipc import IPCServer
    return IPCServer(stdin=io.StringIO(), stdout=io.StringIO())


def lines(server):
    out = server.stdout.getvalue()
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def test_unknown_method_returns_error():
    s = make_server()
    resp = s.handle({"id": 1, "method": "nope"})
    assert resp["id"] == 1 and "unknown method" in resp["error"]


def test_settings_roundtrip(tmp_path, monkeypatch):
    import chalkpress.config as config
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    s = make_server()
    s.handle({"id": 1, "method": "settings.set",
              "params": {"options": {"summary_lang": "en", "output_layout": "grouped"},
                         "app": {}}})
    resp = s.handle({"id": 2, "method": "settings.get"})
    assert resp["result"]["options"]["summary_lang"] == "en"
    assert resp["result"]["options"]["output_layout"] == "grouped"
    assert resp["result"]["llm_configured"] is False


def test_convert_start_runs_pending_tasks(tmp_path, monkeypatch):
    """convert.start 消费任务队列：跑 pending 任务并回写状态为 done。"""
    import chalkpress.config as config
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    s = make_server()

    def fake_batch(opt, videos, log=print, cancel_check=None, progress=None):
        for i, v in enumerate(videos, 1):
            progress("video_start", index=i, total=len(videos), name=v.name)
            progress("video_done", name=v.name)
        progress("batch_done", ok=len(videos), total=len(videos))
        return []

    monkeypatch.setattr(ipc_mod, "run_batch", fake_batch)
    s.handle({"id": 1, "method": "tasks.add",
              "params": {"videos": ["/x/a.mp4", "/x/b.mp4"]}})
    s.handle({"id": 2, "method": "convert.start", "params": {}})
    deadline = time.time() + 5
    while s.worker and s.worker.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    evs = [m["event"] for m in lines(s) if "event" in m]
    assert evs[-1] == "batch_done"
    assert {t["video"]: t["status"] for t in s._load_tasks()} == {
        "/x/a.mp4": "done", "/x/b.mp4": "done"}


def test_track_pause_and_delete(tmp_path, monkeypatch):
    """暂停只改状态，任务保留；删除才移除任务并清除输出目录。"""
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    outdir = tmp_path / "a_讲义"
    outdir.mkdir()
    s = make_server()
    s.handle({"id": 1, "method": "tasks.add", "params": {"videos": [str(video)]}})
    s._track("video_start", {"name": "a.mp4"})
    s._track("video_paused", {"name": "a.mp4"})
    assert s._load_tasks()[0]["status"] == "paused"
    s.handle({"id": 2, "method": "tasks.delete", "params": {"videos": [str(video)]}})
    assert s._load_tasks() == []
    assert not outdir.exists()


def test_cancel_sets_event():
    s = make_server()
    s.handle({"id": 1, "method": "convert.cancel"})
    assert s.cancel.is_set()


def test_serve_skips_non_json_lines():
    from chalkpress.ipc import IPCServer
    stdin = io.StringIO('not json\n{"id":1,"method":"nope"}\n\n')
    out = io.StringIO()
    s = IPCServer(stdin=stdin, stdout=out)
    s.serve()
    msgs = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert len(msgs) == 1 and "error" in msgs[0]


def test_fs_list_videos(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("x")
    s = make_server()
    resp = s.handle({"id": 1, "method": "fs.list_videos", "params": {"dir": str(tmp_path)}})
    assert resp["result"]["videos"] == [str(tmp_path / "a.mp4")]


def test_http_mode_roundtrip(tmp_path, monkeypatch):
    """HTTP 模式：/health、/rpc 调用与 /events 增量拉取。"""
    import json as jsonlib
    import threading
    import urllib.request
    import chalkpress.config as config
    from chalkpress.ipc import make_http_server

    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    httpd = make_http_server(0)  # 端口 0 = 内核分配空闲端口
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/health") as r:
            assert jsonlib.load(r) == {"ok": True}

        req = urllib.request.Request(
            f"{base}/rpc", method="POST",
            data=jsonlib.dumps({"method": "settings.set",
                                "params": {"options": {"summary_lang": "en"}}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert jsonlib.load(r) == {"result": {}}

        with urllib.request.urlopen(f"{base}/rpc", data=jsonlib.dumps(
                {"method": "settings.get"}).encode()) as r:
            body = jsonlib.load(r)
        assert body["result"]["options"]["summary_lang"] == "en"

        with urllib.request.urlopen(f"{base}/events?after=0") as r:
            evs = jsonlib.load(r)["events"]
        assert isinstance(evs, list)
    finally:
        httpd.shutdown()


def test_sanitize_progress_result_to_dict():
    """Result 数据类不可 JSON 序列化，必须展平为标量字段。"""
    class FakeResult:
        frames = [1, 2, 3]
        summary_md = "# t"
        outdir = None
    ev, kw = sanitize_progress("video_done", {"index": 1, "result": FakeResult()})
    assert ev == "video_done"
    assert "result" not in kw
    assert kw["pages"] == 3 and kw["summary"] is True
    json.dumps(kw)  # 必须可序列化
