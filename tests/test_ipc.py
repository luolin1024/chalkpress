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

def test_video_done_appends_history(tmp_path, monkeypatch):
    """video_done 事件追加转换历史；删任务不清历史；history.clear 仅清记录。"""
    import chalkpress.history as history_mod
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    s = make_server()
    s.handle({"id": 1, "method": "tasks.add", "params": {"videos": ["/x/a.mp4"]}})
    s._track("video_start", {"name": "a.mp4"})
    s._track("video_done", {"name": "a.mp4", "pages": 12, "summary": True,
                            "outdir": "/x/a_讲义", "duration": 1800})
    h = s.handle({"id": 2, "method": "history.list"})["result"]["history"]
    assert len(h) == 1
    assert h[0]["summary"] is True and h[0]["exists"] is False  # outdir 不存在
    assert h[0]["duration"] == 1800
    s.handle({"id": 3, "method": "tasks.delete", "params": {"videos": ["/x/a.mp4"]}})
    assert len(s.handle({"id": 4, "method": "history.list"})["result"]["history"]) == 1
    s.handle({"id": 5, "method": "history.clear"})
    assert s.handle({"id": 6, "method": "history.list"})["result"]["history"] == []

def test_done_persists_task_outdir(tmp_path, monkeypatch):
    """video_done 入档时把真实输出目录落到任务上，供前端直接打开。"""
    import chalkpress.history as history_mod
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    s = make_server()
    s.handle({"id": 1, "method": "tasks.add", "params": {"videos": ["/x/a.mp4"]}})
    s._track("video_done", {"name": "a.mp4", "outdir": "/x/a_讲义", "pages": 3})
    t = s._load_tasks()[0]
    assert t["status"] == "done" and t["outdir"] == "/x/a_讲义"
    assert s.handle({"id": 2, "method": "tasks.list"})["result"]["tasks"][0]["outdir"] == "/x/a_讲义"


def test_history_delete_single_record(tmp_path, monkeypatch):
    """history.delete 仅删除定位的一条；未命中的定位是 no-op；产物文件不受影响。"""
    import chalkpress.history as history_mod
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    s = make_server()
    s.handle({"id": 1, "method": "tasks.add",
              "params": {"videos": ["/x/a.mp4", "/x/b.mp4"]}})
    s._track("video_done", {"name": "a.mp4", "outdir": "/x/a_讲义", "pages": 3})
    s._track("video_done", {"name": "b.mp4", "outdir": "/x/b_讲义", "pages": 4})
    h = s.handle({"id": 2, "method": "history.list"})["result"]["history"]
    assert len(h) == 2
    s.handle({"id": 3, "method": "history.delete",
              "params": {"video": h[0]["video"], "finished_at": h[0]["finished_at"]}})
    rest = s.handle({"id": 4, "method": "history.list"})["result"]["history"]
    assert len(rest) == 1 and rest[0]["name"] == "a.mp4"
    s.handle({"id": 5, "method": "history.delete",
              "params": {"video": "/x/none.mp4", "finished_at": 0}})
    assert len(s.handle({"id": 6, "method": "history.list"})["result"]["history"]) == 1



def test_paused_record_superseded_by_done(tmp_path, monkeypatch):
    """暂停入档；续跑完成后覆盖同视频的暂停中间态。"""
    import chalkpress.history as history_mod
    import chalkpress.ipc as ipc_mod
    monkeypatch.setattr(ipc_mod, "tasks_path", lambda: tmp_path / "tasks.json")
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    s = make_server()
    s.handle({"id": 1, "method": "tasks.add", "params": {"videos": ["/x/b.mp4"]}})
    s._track("video_start", {"name": "b.mp4"})
    s._track("video_paused", {"name": "b.mp4"})  # 无 outdir → 从任务路径推导
    h = s.handle({"id": 2, "method": "history.list"})["result"]["history"]
    assert len(h) == 1 and h[0]["status"] == "paused"
    assert h[0]["outdir"] == "/x/b_讲义"  # 由任务视频路径推导
    s._track("video_done", {"name": "b.mp4", "pages": 7, "summary": False,
                            "outdir": "/x/b_讲义"})
    h = s.handle({"id": 3, "method": "history.list"})["result"]["history"]
    assert len(h) == 1  # 暂停中间态被覆盖
    assert h[0]["status"] == "done" and h[0]["pages"] == 7

def test_history_record_caps_and_orders(tmp_path, monkeypatch):
    import chalkpress.history as history_mod
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(history_mod, "HISTORY_MAX", 3)
    for i in range(5):
        history_mod.record_history({"name": f"v{i}", "finished_at": i})
    names = [h["name"] for h in history_mod.list_history()]
    assert names == ["v4", "v3", "v2"]  # 最新在前，超限丢最旧


def test_history_clear_missing_file_is_noop(tmp_path, monkeypatch):
    import chalkpress.history as history_mod
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "none.json")
    history_mod.clear_history()  # 不抛异常


def test_scenes_download_pack(tmp_path, monkeypatch):
    """下载预置场景包：落盘缓存、校验载荷；主源失败自动切镜像；坏载荷拒绝。"""
    import chalkpress.scenes as scenes
    monkeypatch.setattr(scenes, "config_dir", lambda: tmp_path)
    payload = {"scene": "软考", "terms": ["二叉树", "哈夫曼树"],
               "direct": {"生存数": "生成树"}}
    urls = []

    def fake_get(url, timeout=None, headers=None):
        urls.append(url)
        if len(urls) == 1:  # 主源失败 → 切镜像
            raise OSError("connection reset")

        class R:
            def raise_for_status(self): pass
            def json(self): return payload
        return R()

    monkeypatch.setattr(scenes.requests, "get", fake_get)
    r = scenes.download_pack("软考")
    assert r["scene"] == "软考" and r["count"] == 2
    assert len(urls) == 2 and "jsdelivr" in urls[0] and "raw.githubusercontent" in urls[1]
    cached = scenes.load_scene("软考")
    assert cached["terms"] == ["二叉树", "哈夫曼树"] and cached["direct"] == {"生存数": "生成树"}

    # 已缓存后重复下载 = 覆盖更新，不报错
    monkeypatch.setattr(scenes.requests, "get", fake_get)
    scenes.download_pack("软考")
    assert scenes.load_scene("软考")["terms"] == ["二叉树", "哈夫曼树"]


def test_scenes_download_pack_rejects_bad_payload(tmp_path, monkeypatch):
    import chalkpress.scenes as scenes
    monkeypatch.setattr(scenes, "config_dir", lambda: tmp_path)

    def fake_get(url, timeout=None, headers=None):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"scene": "软考", "terms": ["x", 3, "ok词"]}  # 全被过滤
        return R()

    monkeypatch.setattr(scenes.requests, "get", fake_get)
    try:
        scenes.download_pack("软考")
        raise AssertionError("应当抛错")
    except RuntimeError as exc:
        assert "场景包下载失败" in str(exc)
    assert not (tmp_path / "term_scenes").exists() or not scenes.load_scene("软考")


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
        duration = 125.0
    ev, kw = sanitize_progress("video_done", {"index": 1, "result": FakeResult()})
    assert ev == "video_done"
    assert "result" not in kw
    assert kw["pages"] == 3 and kw["summary"] is True and kw["duration"] == 125.0
    json.dumps(kw)  # 必须可序列化
