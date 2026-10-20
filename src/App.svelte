<!-- src/App.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { getVersion } from "@tauri-apps/api/app";
  import { getCurrentWebview } from "@tauri-apps/api/webview";
  import { request, startCore, onEvent, onCoreExit } from "./lib/ipc";
  import { app, resetRun, STAGES, computePct, STATUS_LABEL,
           type Task, type TaskStatus } from "./lib/state.svelte";
  import { autoUpdate } from "./lib/updater";
  import RunPanel from "./components/RunPanel.svelte";
  import ResultsCard from "./components/ResultsCard.svelte";
  import HistoryCard from "./components/HistoryCard.svelte";
  import SettingsPane from "./components/SettingsPane.svelte";

  type Page = "home" | "settings";
  let page = $state<Page>("home");
  let coreDown = $state(false);
  let ver = $state("");

  async function addFiles() {
    const sel = await open({ multiple: true,
      filters: [{ name: "视频", extensions: ["mp4","mov","mkv","webm","avi","m4v","flv","ts"] }] });
    if (sel) for (const f of [].concat(sel as never)) await addVideo(f as string);
  }
  async function addFolder() {
    const dir = await open({ directory: true });
    if (!dir) return;
    const { videos } = await request<{ videos: string[] }>("fs.list_videos", { dir });
    for (const v of videos) await addVideo(v);
  }
  async function addVideo(p: string) {
    try {
      const r = await request<{ tasks: Task[] }>("tasks.add", { videos: [p] });
      app.tasks = r.tasks;
    } catch (e: unknown) {
      app.err = String(e instanceof Error ? e.message : e);
    }
  }
  async function removeTask(p: string) {
    const t = app.tasks.find((x) => x.video === p);
    if (t && t.status !== "pending" &&
        !confirm("删除任务将同时清除已生成的讲义文件夹，确定？")) return;
    try {
      const r = await request<{ tasks: Task[] }>("tasks.delete", { videos: [p] });
      app.tasks = r.tasks;
    } catch (e: unknown) {
      alert(String(e instanceof Error ? e.message : e));
    }
  }

  const runnable = (): boolean =>
    app.tasks.some((t) => ["pending", "paused", "failed"].includes(t.status));

  async function start() {
    if (app.phase === "running" || !runnable()) return;
    resetRun();
    app.phase = "running";
    for (const [k] of STAGES) app.run.stages[k] = "todo";
    page = "home";
    try {
      // 选项与 keep_log 以当前持久化设置为准；任务队列由 core 持有（含暂停任务）
      const s = await request<{ options: Record<string, unknown>; app: Record<string, unknown> }>("settings.get");
      await request("convert.start", { options: s.options, app: s.app });
    } catch (e: unknown) {
      app.phase = "error"; app.err = String(e instanceof Error ? e.message : e);
    }
  }
  async function pause() { await request("convert.pause"); }

  onMount(() => {
    let unDrag: (() => void) | null = null;
    try { getVersion().then((v) => (ver = `v${v}`)); } catch { /* 版本显示失败不影响功能 */ }
    autoUpdate().then((v) => v && alert(`已更新到 v${v}，重启后生效`));
    (async () => {
      try { await startCore(); } catch { coreDown = true; }
      try {
        const r = await request<{ tasks: Task[] }>("tasks.list");
        app.tasks = r.tasks;
      } catch { /* 任务列表加载失败不阻塞首页 */ }
      const VIDEO_EXTS = /\.(mp4|mov|mkv|webm|avi|m4v|flv|ts)$/i;
      const onDrop = async (paths: string[]) => {
        for (const path of paths) {
          if (VIDEO_EXTS.test(path)) {
            await addVideo(path);
          } else if (!/\.[^./\\]+$/.test(path)) {
            // 无扩展名 = 目录：让后端递归展开
            try {
              const { videos } = await request<{ videos: string[] }>("fs.list_videos", { dir: path });
              for (const v of videos) await addVideo(v);
            } catch { /* 非目录或读取失败，忽略 */ }
          }
        }
        page = "home";
      };
      unDrag = await getCurrentWebview().onDragDropEvent((ev: any) => {
        const p = ev.payload;
        if (p.type === "drop") void onDrop(p.paths);
      });
    })();
    onEvent((ev) => {
      switch (ev.event) {
        case "tasks_changed":
          if (ev.tasks) app.tasks = ev.tasks;
          break;
        case "video_start":
          app.run.index = ev.index; app.run.total = ev.total; app.run.name = ev.name;
          for (const [k] of STAGES) app.run.stages[k] = "todo";
          app.run.pages = 0; app.run.pct = 0; app.err = "";
          break;
        case "stage":
          app.run.stages[ev.key] = "doing";
          app.run.pct = computePct(app.run.stages);
          break;
        case "stage_done":
          app.run.stages[ev.key] = "done";
          app.run.pct = computePct(app.run.stages);
          break;
        case "frames": app.run.pages = ev.count; break;
        case "video_done":
          app.results.push({ name: ev.name ?? app.run.name,
                             pages: ev.pages ?? 0, summary: !!ev.summary });
          if (ev.outdir) app.outdir = ev.outdir;
          break;
        case "video_error": app.err = `${ev.name}：${ev.error}`; break;
        case "batch_error": app.phase = "error"; app.err = ev.error; break;
        case "batch_paused": app.phase = "paused"; break;
        case "batch_done": app.phase = "done"; break;
      }
    });
    onCoreExit(() => {
      coreDown = true;
      if (app.phase === "running") { app.phase = "error"; app.err = "转换引擎已退出"; }
    });
    return () => unDrag?.();  // 卸载时解绑拖拽监听
  });

  const statusChip = (st: TaskStatus): string =>
    ({ pending: "chip", running: "chip run", paused: "chip paused",
       done: "chip ok", failed: "chip bad" }[st]);
</script>

<div class="shell">
  {#if coreDown}
    <div class="corebar">转换引擎未启动，请重启应用；若持续出现请重新安装。
      <button class="retry" onclick={() => { coreDown = false; startCore().catch(() => (coreDown = true)); }}>重试</button>
    </div>
  {/if}

  <div class="body">
    <aside class="side">
      <div class="brand">
        <svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14" fill="#4f5bd5"/>
          <path d="M22 12 h14 l8 8 v30 a4 4 0 0 1 -4 4 h-18 a4 4 0 0 1 -4 -4 v-34 a4 4 0 0 1 4 -4 z" fill="#f6f3e7"/>
          <path d="M36 12 l8 8 h-8 z" fill="#c6ccee"/>
          <path d="M27 25 l14 8 -14 8 z" fill="#4f5bd5"/>
        </svg>
        <span>Chalkpress</span>
      </div>

      <nav class="navi">
        <button class="nav" class:active={page === "home"} onclick={() => (page = "home")}>
          <span class="ico">▶</span> 首页
        </button>
        <button class="nav" class:active={page === "settings"} onclick={() => (page = "settings")}>
          <span class="ico">⚙</span> 设置
        </button>
      </nav>

      <div class="foot">{ver}</div>
    </aside>

    <main class="wrap">
      {#if page === "settings"}
        <SettingsPane />
      {:else if app.phase === "running" || app.phase === "paused"}
        <RunPanel onPause={pause} onResume={start} paused={app.phase === "paused"} />
      {:else if app.phase === "done"}
        <ResultsCard />
      {:else}
        <section class="hero">
          <div class="drop" role="button" tabindex="0" onclick={addFiles}
               onkeydown={(e) => (e.key === "Enter" || e.key === " ") && addFiles()}>
            <div class="drop-icon">▶</div>
            <div class="drop-title">拖入视频，或点击添加</div>
            <div class="drop-sub">支持 mp4 · mov · mkv · webm 等，可多选或整个文件夹</div>
          </div>
          <button class="ghost" onclick={addFolder}>添加文件夹</button>

          {#if app.tasks.length}
            <div class="card">
              {#each app.tasks as t (t.video)}
                <div class="vrow">
                  <span class="vname">{t.video.split(/[\\/]/).pop()}</span>
                  <span class="vsize">{t.video}</span>
                  <span class={statusChip(t.status)}>{STATUS_LABEL[t.status]}</span>
                  <button class="x" title="删除任务" onclick={() => removeTask(t.video)}>✕</button>
                </div>
              {/each}
              <div class="vsum">{app.tasks.length} 个任务 · 暂停可断点继续，删除才会真正移除</div>
            </div>
            {#if runnable()}
              <button class="primary" onclick={start}>
                {app.tasks.some((t) => t.status === "paused") ? "继续转换" : "开始转换"}
              </button>
            {/if}
          {/if}
          <HistoryCard />
          {#if app.err}<p class="err">✗ {app.err}</p>{/if}
        </section>
      {/if}
    </main>
  </div>
</div>

<style>
  .shell { display: flex; flex-direction: column; height: 100vh; }
  .corebar { background: var(--red); color: #fff; text-align: center; padding: 6px; font-size: 13px; }
  .retry { margin-left: 10px; background: #fff; color: var(--red); border: 1px solid #fff;
           border-radius: 6px; padding: 1px 12px; font-size: 12px; cursor: pointer; }
  .body { display: flex; flex: 1; min-height: 0; }

  .side { width: 156px; flex: none; border-right: 1px solid var(--line); background: var(--card);
          padding: 16px 10px 12px; display: flex; flex-direction: column; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px;
           padding: 0 8px 16px; }
  .logo { width: 22px; height: 22px; display: inline-block; }
  .navi { display: flex; flex-direction: column; gap: 4px; }
  .nav { display: flex; align-items: center; gap: 8px; text-align: left; border: 0;
         background: transparent; padding: 10px 12px; border-radius: var(--radius);
         cursor: pointer; font-size: 14px; color: var(--ink2); }
  .nav:hover { background: var(--line); }
  .nav.active { background: var(--accent); color: #fff; font-weight: 600; }
  .nav .ico { font-size: 12px; }
  .foot { margin-top: auto; padding: 8px; color: var(--faint); font-size: 11px; }

  .wrap { flex: 1; min-width: 0; overflow-y: auto; padding: 18px 24px 32px; }

  .hero { display: flex; flex-direction: column; align-items: center; gap: 14px; margin-top: 6vh; }
  .drop { width: 100%; background: var(--card); border: 1.5px dashed var(--faint); border-radius: var(--radius);
          padding: 44px 0 38px; text-align: center; cursor: pointer; transition: border-color .15s; }
  .drop:hover { border-color: var(--accent); }
  .drop-icon { width: 44px; height: 44px; border-radius: 12px; background: var(--accent); color: #fff;
               display: flex; align-items: center; justify-content: center; font-size: 20px; margin: 0 auto 10px; }
  .drop-title { font-weight: 600; font-size: 15px; }
  .drop-sub { color: var(--ink2); font-size: 12px; margin-top: 3px; }
  .card { width: 100%; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 16px; }
  .vrow { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .vname { font-weight: 500; }
  .vsize { color: var(--faint); font-size: 11px; margin-left: auto; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
  .chip { flex: none; font-size: 11px; color: var(--ink2); border: 1px solid var(--line);
          border-radius: 99px; padding: 1px 9px; }
  .chip.run { color: var(--accent-dk); border-color: var(--accent-bg); background: var(--accent-bg); }
  .chip.paused { color: #8a6d1a; border-color: #efe3bd; background: #fbf4dd; }
  .chip.ok { color: #2f6d4f; border-color: #cfe5da; background: #ecf6f1; }
  .chip.bad { color: var(--red); border-color: #f0d3d1; background: #fbeeee; }
  .x { border: 0; background: transparent; color: var(--faint); cursor: pointer; }
  .x:hover { color: var(--red); }
  .vsum { color: var(--ink2); font-size: 12px; padding: 8px 0; }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 11px 28px; font-size: 15px; font-weight: 600; cursor: pointer; width: 100%; }
  .primary:hover { background: var(--accent-dk); }
  .ghost { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
           padding: 8px 18px; cursor: pointer; }
  .ghost:hover { border-color: var(--faint); }
  .err { color: var(--red); }
</style>
