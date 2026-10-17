<!-- src/components/SettingsPane.svelte -->
<!-- 设置页（侧边栏内嵌面板，非浮层）：配置加载失败时错误直接显示在页面内。 -->
<script lang="ts">
  import { onMount } from "svelte";
  import { openPath } from "@tauri-apps/plugin-opener";
  import { getVersion } from "@tauri-apps/api/app";
  import { request } from "../lib/ipc";
  import { checkUpdate } from "../lib/updater";

  type Settings = {
    options: {
      summary_lang: string;
      zh_script: string;
      auto_correct: boolean;
      term_fix: boolean;
      asr_model: string | null;
      scene_threshold: number | null;
      min_gap: number | null;
      language: string | null;
      asr_backend: string | null;
    };
    app: { keep_log: boolean };
    llm: { api_base: string; api_key: string; model: string };
    llm_configured: boolean;
    logs_dir: string;
  };

  let s = $state<Settings | null>(null);
  let loadErr = $state("");
  let saved = $state(false);
  let saveErr = $state("");
  let ver = $state("");
  let updStatus = $state("");
  let checking = $state(false);

  const DEFAULT_OPTIONS: Settings["options"] = {
    summary_lang: "zh",
    zh_script: "auto",
    auto_correct: true,
    term_fix: false,
    asr_model: null,
    scene_threshold: null,
    min_gap: null,
    language: null,
    asr_backend: null,
  };

  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  /** 打开日志文件夹：目录可能尚未创建（从未开启日志转换过），先经 core 建目录并清理过期日志。 */
  async function openLogs(): Promise<void> {
    try {
      const r = await request<{ dir: string }>("logs.prepare");
      await openPath(r.dir);
    } catch (e) {
      console.error("open logs:", e);
    }
  }
  function touch() {
    saved = false;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, 400);   // 输入防抖，改动即时保存
  }
  async function flush() {
    if (!s) return;
    try {
      await request("settings.set", { options: s.options, app: s.app, llm: s.llm });
      saved = true;
      saveErr = "";
    } catch (e: unknown) {
      saveErr = String(e instanceof Error ? e.message : e);
    }
  }

  async function runUpdateCheck() {
    checking = true;
    updStatus = "";
    try {
      updStatus = await checkUpdate();
    } finally {
      checking = false;
    }
  }

  onMount(async () => {
    loadErr = "";
    try {
      const r = await request<Settings>("settings.get");
      r.llm = { api_base: "", api_key: "", model: "", ...r.llm };
      r.options = { ...DEFAULT_OPTIONS, ...r.options };
      s = r;
    } catch (e: unknown) {
      loadErr = String(e instanceof Error ? e.message : e);
    }
    try {
      ver = `v${await getVersion()}`;
    } catch {
      ver = "";
    }
  });
</script>

<div class="pane">
  <h2>设置</h2>
  <p class="hint">
    改动即时保存
    {#if saveErr}· <span class="bad">保存失败：{saveErr}</span>{:else if saved}· 已保存 ✓{/if}
  </p>

  {#if loadErr}
    <p class="err">✗ {loadErr}</p>
  {:else if !s}
    <p class="hint">加载中…</p>
  {:else}
    <section>
      <h3>输出</h3>
      <label>输出语言（AI 总结）
        <select bind:value={s.options.summary_lang} onchange={touch}>
          <option value="zh">简体中文</option><option value="zh-en">中英对照</option><option value="en">English</option>
        </select></label>
      <label>简繁
        <select bind:value={s.options.zh_script} onchange={touch}>
          <option value="auto">自动</option><option value="simplified">简体</option><option value="traditional">繁体</option>
        </select></label>
      <label class="row">软考术语修正<span class="tip">拼音比对纠错，无 AI、瞬时</span>
        <input type="checkbox" bind:checked={s.options.term_fix} onchange={touch} /></label>
    </section>

    <section>
      <h3>语音识别</h3>
      <label>字幕模型
        <select bind:value={s.options.asr_model} onchange={touch}>
          <option value={null}>自动（推荐）</option><option value="tiny">tiny（最快）</option>
          <option value="small">small（默认）</option><option value="medium">medium（最准）</option>
        </select></label>
      <label>识别语言
        <select bind:value={s.options.language} onchange={touch}>
          <option value={null}>自动检测（推荐）</option><option value="zh">中文</option>
          <option value="en">英语</option><option value="ja">日语</option>
          <option value="ko">韩语</option><option value="de">德语</option>
          <option value="fr">法语</option><option value="es">西班牙语</option>
        </select></label>
      <label>识别引擎
        <select bind:value={s.options.asr_backend} onchange={touch}>
          <option value={null}>默认（faster-whisper）</option>
          <option value="mlx-whisper">mlx-whisper（Apple 芯片加速）</option>
        </select></label>
      <label class="row">AI 字幕校对
        <input type="checkbox" bind:checked={s.options.auto_correct} onchange={touch} /></label>
    </section>

    <section>
      <h3>AI 分析（OpenAI 兼容接口）</h3>
      <label>接口地址<input bind:value={s.llm.api_base} oninput={touch} placeholder="不配置则跳过 AI 步骤" /></label>
      <label>API Key<input type="password" bind:value={s.llm.api_key} oninput={touch} /></label>
      <label>模型<input bind:value={s.llm.model} oninput={touch} /></label>
    </section>

    <section>
      <h3>关键帧（高级）</h3>
      <label>场景切换灵敏度
        <select bind:value={s.options.scene_threshold} onchange={touch}>
          <option value={null}>标准</option><option value={0.05}>更多页数（画面琐碎）</option>
          <option value={0.12}>更少页数（课件翻页少）</option>
        </select></label>
      <label>关键帧最小间隔
        <select bind:value={s.options.min_gap} onchange={touch}>
          <option value={null}>2 秒</option><option value={5}>5 秒</option><option value={10}>10 秒</option>
        </select></label>
    </section>

    <section>
      <h3>日志</h3>
      <label class="row">保留运行日志
        <input type="checkbox" bind:checked={s.app.keep_log} onchange={touch} /></label>
      <button class="ghost" onclick={openLogs}>打开日志文件夹</button>
    </section>

    <section>
      <h3>更新</h3>
      <label class="row">当前版本<span class="tip">{ver || "…"}</span></label>
      <button class="ghost" disabled={checking} onclick={runUpdateCheck}>
        {checking ? "检查中…" : "检查更新"}
      </button>
      {#if updStatus}<p class="hint">{updStatus}</p>{/if}
      <p class="tip">应用启动时也会自动检查并静默安装更新</p>
    </section>
  {/if}
</div>

<style>
  .pane { max-width: 640px; }
  h2 { margin: 0 0 4px; font-size: 18px; }
  h3 { font-size: 12px; color: var(--ink2); margin: 20px 0 6px; text-transform: none; }
  label { display: block; font-size: 13px; margin: 10px 0; }
  label.row { display: flex; justify-content: space-between; align-items: center; }
  label.row .tip { color: var(--ink2); font-size: 11px; margin-right: auto; margin-left: 10px; }
  input[type="text"], input:not([type]), input[type="password"], select {
      width: 100%; margin-top: 4px; padding: 7px 10px; border: 1px solid var(--line);
      border-radius: 8px; font: inherit; background: var(--card); }
  input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  input[type="checkbox"] { width: auto; }
  .hint { color: var(--ink2); font-size: 12px; margin: 4px 0 0; }
  .tip { color: var(--ink2); font-size: 11px; }
  .err { color: var(--red); font-size: 13px; }
  .bad { color: var(--red); }
  .ghost { border: 1px solid var(--line); background: var(--card); border-radius: 8px;
           padding: 7px 14px; cursor: pointer; }
  .ghost:disabled { opacity: 0.6; cursor: default; }
</style>
