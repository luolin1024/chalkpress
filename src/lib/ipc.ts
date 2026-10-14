// src/lib/ipc.ts
// 传输：前端 → invoke(core_request/core_spawn，Rust 管道) → core stdio 行协议。
// 事件经 Rust app.emit("core-event") 推送，@tauri-apps/api/event 的 listen 接收。
// 弃用 WebView fetch 与 plugin-shell stdio：系统代理/安全软件吞回环请求、
// plugin-shell 事件投递跨平台不可靠（设置面板卡"加载中"的根因）。
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/** sidecar 事件。已知字段按 state.svelte.ts 的消费形状声明。 */
export type CoreEvent = {
  event: string;
  index: number;
  total: number;
  name: string;
  pages: number;
  count: number;
  summary: boolean;
  outdir?: string;
  error?: string;
  key: string;
  ok: number;
  _seq: number;
};

const eventHandlers = new Set<(ev: CoreEvent) => void>();
const exitHandlers = new Set<() => void>();
let unlistenEvent: (() => void) | null = null;
let unlistenExit: (() => void) | null = null;
let started = false;
let ready: Promise<void> | null = null;

export function startCore(): Promise<void> {
  if (ready) return ready;
  ready = doStart();
  return ready;
}

function sleep(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

async function doStart(): Promise<void> {
  if (!unlistenEvent) {
    unlistenEvent = await listen<CoreEvent>("core-event", (e) => {
      for (const h of eventHandlers) h(e.payload);
    });
  }
  if (!unlistenExit) {
    unlistenExit = await listen("core-exit", () => {
      for (const h of exitHandlers) h();
    });
  }
  const pong = await invoke<string>("ping");
  console.log("[ipc] ping →", pong);
  await invoke("core_spawn");  // 幂等：core 已运行时为 no-op
  started = true;
  // 健康轮询：用裸 invoke（request() 内部 await ready 会与 doStart 自死锁）
  let lastErr = "";
  for (let i = 0; i < 50; i++) {
    try {
      const raw = await invoke<string>("core_request",
        { method: "settings.get", params: "{}", timeoutMs: 15000 });
      return;  // core 已应答（业务错误也算就绪）
    } catch (e: unknown) {
      lastErr = String(e instanceof Error ? e.message : e);
    }
    await sleep(1000);
  }
  throw new Error(`core 启动超时（onefile 解压未完成）｜${lastErr}`);
}

export async function request<T = unknown>(method: string, params?: object): Promise<T> {
  if (ready) await ready;          // 启动中则等它完成（含失败抛错）
  if (!started) throw new Error("core 未启动");
  const v = await invoke("core_request", {
    method,
    params: JSON.stringify(params ?? {}),
    timeoutMs: 30000,
  }) as { result?: T; error?: string };  // Rust 命令返回的 Value 形状由 core_request 契约保证
  if (v.error) throw new Error(v.error);
  return v.result as T;
}

export function onEvent(h: (ev: CoreEvent) => void): () => void {
  eventHandlers.add(h);
  return () => eventHandlers.delete(h);
}

export function onCoreExit(h: () => void): () => void {
  exitHandlers.add(h);
  return () => exitHandlers.delete(h);
}
