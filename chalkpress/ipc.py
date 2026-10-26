# chalkpress/ipc.py
"""stdio 行 JSON IPC 服务：Tauri sidecar 入口（开发期可直接 python -m chalkpress.ipc 调试）。"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from .config import (
    load_config_file,
    load_llm_config,
    logs_dir,
    normalize_settings,
    prune_logs,
    save_config_file,
    tasks_path,
)
from .pipeline import Options, VIDEO_EXTS, run_batch

log = logging.getLogger("chalkpress.ipc")


def sanitize_progress(ev: str, kw: dict) -> tuple[str, dict]:
    """pipeline 的 progress 事件 → 可 JSON 序列化的 IPC 事件。

    video_done 事件携带 Result 数据类（含 Path/列表），展平为 pages/summary/outdir/duration。
    """
    if "result" in kw:
        r = kw.pop("result")
        kw["pages"] = len(getattr(r, "frames", None) or [])
        kw["summary"] = bool(getattr(r, "summary_md", None))
        kw["outdir"] = str(getattr(r, "outdir", None) or "")
        kw["duration"] = float(getattr(r, "duration", None) or 0)
    return ev, kw


class IPCServer:
    def __init__(self, stdin=None, stdout=None, emit=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self._wlock = threading.Lock()
        self._fh = None
        self._emit_fn = emit

    # ---------- 输出 ----------
    def send(self, obj: dict):
        with self._wlock:
            self.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.stdout.flush()

    def _emit(self, obj: dict):
        """事件出口：stdio 模式写 stdout；HTTP 模式由 run_http 注入缓冲。"""
        if self._emit_fn is not None:
            self._emit_fn(obj)
        else:
            self.send(obj)

    # ---------- 请求处理 ----------
    def handle_call(self, method, params) -> dict:
        """同步调用：返回 {result} 或 {error}，stdio/HTTP 两模式共用。"""
        try:
            return {"result": self.dispatch(method, params or {})}
        except Exception as exc:
            log.exception("handle %s failed", method)
            return {"error": str(exc)}

    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        out = self.handle_call(req.get("method"), req.get("params") or {})
        return {"id": rid, **out}

    def dispatch(self, method: str, params: dict):
        if method == "settings.get":
            cfg = load_config_file()
            return {"options": cfg.get("options", {}),
                    "app": cfg.get("app", {}),
                    "llm": cfg.get("llm", {}),
                    "llm_configured": load_llm_config() is not None,
                    "logs_dir": str(logs_dir())}
        if method == "settings.set":
            save_config_file(normalize_settings(params))
            return {}
        if method == "convert.start":
            self._start(params)
            return {}
        if method in ("convert.pause", "convert.cancel"):
            self.cancel.set()
            return {}
        if method == "tasks.add":
            return {"tasks": self._add_tasks(params.get("videos") or [])}
        if method == "tasks.list":
            return {"tasks": self._load_tasks()}
        if method == "tasks.delete":
            return {"tasks": self._delete_tasks(params.get("videos") or [])}
        if method == "scenes.list":
            from .scenes import list_scenes
            return {"scenes": list_scenes()}
        if method == "scenes.delete":
            from .scenes import delete_scene
            return {"deleted": delete_scene(params.get("scene", ""))}
        if method == "scenes.download_pack":
            from .scenes import download_pack
            r = download_pack(params.get("name") or "软考")
            return {"scene": r["scene"], "count": r["count"]}
        if method == "logs.prepare":
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            return {"dir": str(d), "pruned": prune_logs()}
        if method == "history.list":
            from .history import list_history
            return {"history": list_history()}
        if method == "history.clear":
            from .history import clear_history
            clear_history()
            return {}
        if method == "history.delete":
            from .history import delete_history
            delete_history(params.get("video", ""), int(params.get("finished_at") or 0))
            return {}
        if method == "fs.list_videos":
            d = Path(params["dir"]).expanduser()
            return {"videos": sorted(str(p) for p in d.iterdir()
                                     if p.suffix.lower() in VIDEO_EXTS)}
        raise KeyError(f"unknown method: {method}")

    # ---------- 转换 ----------
    def _start(self, params: dict):
        """开始/继续：跑任务队列里全部 pending/paused/failed 任务；进行中则拒绝。"""
        if self.worker and self.worker.is_alive():
            raise RuntimeError("转换进行中")
        self.cancel.clear()
        tasks = [t for t in self._load_tasks()
                 if t.get("status") in ("pending", "paused", "failed")]
        if not tasks:
            return
        for t in tasks:
            t["status"] = "pending"
        self._save_tasks(tasks)
        o = params.get("options", {})
        keep_log = bool((params.get("app") or {}).get("keep_log", True))
        opt = Options(
            video=Path(tasks[0]["video"]),
            scene_threshold=o.get("scene_threshold"),
            min_gap=o.get("min_gap"),
            language=o.get("language"),
            summary_lang=o.get("summary_lang", "zh"),
            zh_script=o.get("zh_script", "auto"),
            output_layout=o.get("output_layout"),
            speed=o.get("speed"),
            auto_correct=o.get("auto_correct", True),
            term_fix=o.get("term_fix"),
            asr_backend=o.get("asr_backend"),
            asr_model=o.get("asr_model"),
            api_base=o.get("api_base"),
            api_key=o.get("api_key"),
            llm_model=o.get("llm_model"),
            skip_analysis=not load_llm_config(o.get("api_base"), o.get("api_key"),
                                              o.get("llm_model")),
        )
        videos = [Path(t["video"]) for t in tasks]
        self._open_logfile(keep_log)

        def progress(ev, **kw):
            ev, kw = sanitize_progress(ev, kw)
            self._track(ev, kw)
            self._emit({"event": ev, **kw})

        def work():
            try:
                run_batch(opt, videos, log=self._log,
                          cancel_check=self.cancel.is_set, progress=progress)
            except Exception as exc:
                log.exception("run_batch failed")
                self.send({"event": "batch_error", "error": str(exc)})
            finally:
                self._close_logfile()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # ---------- 任务队列 ----------
    def _load_tasks(self) -> list:
        try:
            data = json.loads(tasks_path().read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_tasks(self, tasks: list):
        p = tasks_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
        self._emit({"event": "tasks_changed", "tasks": tasks})

    def _add_tasks(self, videos: list) -> list:
        tasks = self._load_tasks()
        known = {t["video"] for t in tasks}
        for v in videos:
            if v not in known:
                tasks.append({"video": v, "status": "pending"})
        self._save_tasks(tasks)
        return tasks

    def _delete_tasks(self, videos: list) -> list:
        """删除任务并清除其输出目录——删除是唯一真正移除任务的方式。"""
        if self.worker and self.worker.is_alive():
            raise RuntimeError("转换进行中，请先暂停再删除任务")
        tasks = self._load_tasks()
        keep = []
        for t in tasks:
            if t["video"] in videos:
                v = Path(t["video"])
                shutil.rmtree(v.with_name(v.stem + "_讲义"), ignore_errors=True)
            else:
                keep.append(t)
        self._save_tasks(keep)
        return keep

    def _track(self, ev: str, kw: dict):
        """pipeline 视频级事件 → 任务状态落盘并广播。"""
        status = {"video_start": "running", "video_done": "done",
                  "video_paused": "paused", "video_error": "failed"}.get(ev)
        name = kw.get("name")
        if not status or not name:
            return
        tasks = self._load_tasks()
        changed = False
        for t in tasks:
            if Path(t["video"]).name != name:
                continue
            if ev == "video_done" and kw.get("outdir") and t.get("outdir") != kw["outdir"]:
                t["outdir"] = kw["outdir"]
                changed = True
            if t.get("status") != status:
                t["status"] = status
                changed = True
        if changed:
            self._save_tasks(tasks)
        if ev in ("video_done", "video_paused", "video_error"):
            self._record_history(name, kw, status)

    def _record_history(self, name: str, kw: dict, status: str = "done"):
        """转换动态入档（完成/暂停/失败），独立于任务删除，保留"转过什么"。"""
        from .history import record_history
        video = next((t["video"] for t in self._load_tasks()
                      if Path(t["video"]).name == name), "")
        outdir = kw.get("outdir") or ""
        if not outdir and video:
            v = Path(video)
            outdir = str(v.with_name(v.stem + "_讲义"))
        record_history({"video": video, "name": name, "status": status,
                        "outdir": outdir,
                        "pages": int(kw.get("pages") or 0),
                        "summary": bool(kw.get("summary")),
                        "duration": int(float(kw.get("duration") or 0)),
                        "finished_at": int(time.time())})

    def _open_logfile(self, keep_log: bool):
        if not keep_log:
            return
        try:
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            prune_logs()
            self._fh = open(d / f"chalkpress-{time.strftime('%Y%m%d-%H%M%S')}.log",
                            "a", encoding="utf-8")
        except OSError:
            self._fh = None

    def _log(self, text: str):
        if self._fh:
            try:
                self._fh.write(text + "\n")
                self._fh.flush()
            except OSError:
                pass

    def _close_logfile(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    # ---------- 主循环 ----------
    def serve(self):
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                log.warning("丢弃非 JSON 行: %.80s", line)  # stdin 非 JSON 行容错；stdout 污染由 main() 的 sys.stdout 重定向防护
                continue
            self.send(self.handle(req))


def make_http_server(port: int):
    """HTTP 模式（Tauri 前端用）：127.0.0.1 上的 POST /rpc + GET /events?after=N + GET /health。

    plugin-shell 的 stdio 事件投递在部分环境下静默失效，回环 HTTP 可 curl 直调。
    返回已绑定的 ThreadingHTTPServer（port=0 时由内核分配，测试用）。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    events: list[dict] = []
    st = {"trimmed": 0}  # 已从 events 左侧裁掉的事件数
    lock = threading.Lock()
    core = IPCServer()

    def emit(obj: dict):
        with lock:
            obj = dict(obj)
            obj["_seq"] = st["trimmed"] + len(events) + 1
            events.append(obj)
            if len(events) > 4000:  # 控内存，保留最近一段
                drop = len(events) - 2000
                del events[:drop]
                st["trimmed"] += drop

    core._emit_fn = emit

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/health":
                body = b'{"ok": true}'
            elif url.path == "/events":
                after = int(parse_qs(url.query).get("after", ["0"])[0])
                with lock:
                    avail = st["trimmed"] + len(events)
                    chunk = [e for e in events if e["_seq"] > after]
                    body = json.dumps({"events": chunk, "next": avail}).encode()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if urlparse(self.path).path != "/rpc":
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                out = core.handle_call(req.get("method"), req.get("params"))
            except Exception as exc:
                out = {"error": str(exc)}
            body = json.dumps(out).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # 静默访问日志，stderr 只留业务日志

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def run_http(port: int):
    """绑定并伺服；stdin EOF（宿主退出→管道关闭）即关服退出。"""
    httpd = make_http_server(port)

    def watch_stdin():
        for _ in sys.stdin:  # 宿主退出 → 管道 EOF → 关服
            pass
        log.info("stdin EOF，退出")
        httpd.shutdown()

    threading.Thread(target=watch_stdin, daemon=True).start()
    log.info("HTTP IPC listening on %s:%d", *httpd.server_address)
    httpd.serve_forever()


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="HTTP 模式（Tauri 前端）")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    # Tauri 侧用环境变量传配置（plugin-shell 的 sidecar args 在部分版本静默丢失，
    # 所以 --http/--port 都有环境变量兜底）
    if not args.http and os.getenv("CHALKPRESS_IPC_PORT"):
        args.http = True
    if args.port == 0:
        args.port = int(os.getenv("CHALKPRESS_IPC_PORT", "0"))

    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    protocol_out = sys.stdout   # 协议通道固定为真实 stdout
    sys.stdout = sys.stderr     # 第三方 Python 级 print() → stderr
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    if args.http:
        run_http(args.port)
    else:
        IPCServer(stdout=protocol_out).serve()


if __name__ == "__main__":
    main()
