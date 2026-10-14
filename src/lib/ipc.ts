// src/lib/ipc.ts
import { Command } from "@tauri-apps/plugin-shell";

// 传输：127.0.0.1 回环 HTTP（POST /rpc + GET /events?after=N 轮询）。
// plugin-shell 的 stdio 事件投递在部分环境（WebView2/WebKitGTK 均复现）静默失效，
// 故只借它拉起进程，收发全走 HTTP，可 curl 直调。
const eventHandlers = new Set<(ev: any) => void>();
const exitHandlers = new Set<() => void>();
let baseUrl = "";
let pollTimer: ReturnType<typeof setInterval> | null = null;
let after = 0;
let failCount = 0;
let dead = false;      // sidecar 进程已退出（区别于未启动）
let ready: Promise<void> | null = null;

export function startCore(): Promise<void> {
  if (ready) return ready;
  ready = doStart();
  return ready;
}

async function doStart(): Promise<void> {
  dead = false;
  const port = 49152 + Math.floor(Math.random() * 16000);
  // 模式与端口全走环境变量：plugin-shell 对 sidecar 传 args 在部分版本会静默丢失
  const c = Command.sidecar("binaries/chalkpress-core", [],
    { env: { CHALKPRESS_IPC_PORT: String(port) } });
  c.stderr.on("data", (l: string) => console.error("[core]", l));
  c.on("close", () => {
    dead = true;
    baseUrl = "";
    ready = null;  // 允许下次 startCore() 重试
    stopPolling();
    exitHandlers.forEach((h) => h());
  });
  try {
    await c.spawn();
  } catch (e) {
    ready = null;  // 允许下次 startCore 重试
    throw e;
  }
  // onefile 首启自解压实测可达 ~80s，健康检查窗口放宽到 150s
  for (let i = 0; i < 300; i++) {
    if (dead) {
      ready = null;
      throw new Error("core 已退出");
    }
    try {
      const r = await fetch(`http://127.0.0.1:${port}/health`);
      if (r.ok) {
        baseUrl = `http://127.0.0.1:${port}`;
        startPolling();
        return;
      }
    } catch { /* 未就绪，继续等 */ }
    await sleep(300);
  }
  // 超时也重置 ready：core 可能在解压完成后照常起了监听，重试即可用
  ready = null;
  throw new Error("core 健康检查超时");
}

function sleep(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

export async function request<T = any>(method: string, params?: object): Promise<T> {
  if (ready) await ready;          // 启动中则等它完成（含失败抛错）
  if (!baseUrl) throw new Error("core 未启动");
  const r = await fetch(`${baseUrl}/rpc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method, params: params ?? {} }),
  });
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j.result as T;
}

function startPolling() {
  after = 0;
  failCount = 0;
  pollTimer = setInterval(async () => {
    if (!baseUrl) return;
    try {
      const r = await fetch(`${baseUrl}/events?after=${after}`);
      const j = await r.json();
      failCount = 0;
      for (const ev of j.events as any[]) {
        after = ev._seq;
        eventHandlers.forEach((h) => h(ev));
      }
    } catch {
      if (++failCount >= 10) {  // 连续 3 秒不可达 → 引擎已退出
        baseUrl = "";
        stopPolling();
        exitHandlers.forEach((h) => h());
      }
    }
  }, 300);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

export function onEvent(h: (ev: any) => void): () => void {
  eventHandlers.add(h);
  return () => eventHandlers.delete(h);
}

export function onCoreExit(h: () => void): () => void {
  exitHandlers.add(h);
  return () => exitHandlers.delete(h);
}
