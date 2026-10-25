<!-- src/components/SettingsPane.svelte -->
<!-- 设置页（侧边栏内嵌面板，非浮层）：配置加载失败时错误直接显示在页面内。
     视觉：ChatGPT 式设置——节标题 + 圆角卡片，行内"标签+说明在左、控件在右"，细分隔线。 -->
<script lang="ts">
  import { onMount } from "svelte";
  import { openPath } from "../lib/opener";
  import { getVersion } from "@tauri-apps/api/app";
  import { request } from "../lib/ipc";
  import { checkUpdate } from "../lib/updater";

  type Settings = {
    options: {
      summary_lang: string;
      zh_script: string;
      output_layout: string;
      speed: string;
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

  type ScenePack = { scene: string; count: number; updated_at: number };

  let s = $state<Settings | null>(null);
  let scenes = $state<ScenePack[]>([]);
  let loadErr = $state("");
  let saved = $state(false);
  let saveErr = $state("");
  let ver = $state("");
  let updStatus = $state("");
  let checking = $state(false);

  const DEFAULT_OPTIONS: Settings["options"] = {
    summary_lang: "zh",
    zh_script: "auto",
    output_layout: "original",
    speed: "standard",
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

  async function loadScenes() {
    try {
      scenes = (await request<{ scenes: ScenePack[] }>("scenes.list")).scenes;
    } catch { /* 场景列表加载失败不影响设置 */ }
  }
  async function removeScene(scene: string) {
    if (!confirm(`删除场景「${scene}」的术语缓存？下次遇到该场景将重新收集。`)) return;
    try {
      await request("scenes.delete", { scene });
      await loadScenes();
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
    loadScenes();
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
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">输出语言（AI 总结）</span></span>
          <span class="control">
            <select bind:value={s.options.summary_lang} onchange={touch}>
              <option value="zh">简体中文</option><option value="zh-en">中英对照</option><option value="en">English</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">简繁</span></span>
          <span class="control">
            <select bind:value={s.options.zh_script} onchange={touch}>
              <option value="auto">自动</option><option value="simplified">简体</option><option value="traditional">繁体</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">目录结构</span>
            <span class="tip">分类结构按类型分文件夹，md 图片链接自动适配</span></span>
          <span class="control">
            <select bind:value={s.options.output_layout} onchange={touch}>
              <option value="original">原始结构</option>
              <option value="grouped">分类结构</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">术语修正</span>
            <span class="tip">AI 识别课程领域（软考/编程/医学/法律…），收集易听错的专业术语并拼音纠错；同场景复用缓存，需已配置 AI</span></span>
          <input type="checkbox" bind:checked={s.options.term_fix} onchange={touch} />
        </div>
      </div>
    </section>

    <section>
      <h3>语音识别</h3>
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">转写速度</span>
            <span class="tip">并发线程档位，极速档用满全部 CPU 核心</span></span>
          <span class="control">
            <select bind:value={s.options.speed} onchange={touch}>
              <option value="standard">标准 · 4 线程</option>
              <option value="fast">快速 · 8 线程</option>
              <option value="turbo">极速 · 全部核心</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">字幕模型</span></span>
          <span class="control">
            <select bind:value={s.options.asr_model} onchange={touch}>
              <option value={null}>自动（推荐）</option><option value="tiny">tiny（最快）</option>
              <option value="small">small（默认）</option><option value="medium">medium（最准）</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">识别语言</span></span>
          <span class="control">
            <select bind:value={s.options.language} onchange={touch}>
              <option value={null}>自动检测（推荐）</option><option value="zh">中文</option>
              <option value="en">英语</option><option value="ja">日语</option>
              <option value="ko">韩语</option><option value="de">德语</option>
              <option value="fr">法语</option><option value="es">西班牙语</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">识别引擎</span>
            <span class="tip">自动 = 安装时按系统选最适配：Apple 芯片用 mlx 加速</span></span>
          <span class="control">
            <select bind:value={s.options.asr_backend} onchange={touch}>
              <option value={null}>自动（推荐）</option>
              <option value="mlx-whisper">mlx-whisper（Apple 芯片）</option>
              <option value="faster-whisper">faster-whisper（兼容）</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">AI 字幕校对</span>
            <span class="tip">同音字/误听修正，需已配置 AI</span></span>
          <input type="checkbox" bind:checked={s.options.auto_correct} onchange={touch} />
        </div>
      </div>
    </section>

    <section>
      <h3>场景术语库</h3>
      <div class="card">
        <p class="cardhint">开启「术语修正」后，转换时自动识别课程领域并收集易听错的专业术语；同一场景复用缓存，不再重复收集。内置软考预置包已自动就绪。</p>
        {#each scenes as sc (sc.scene)}
          <div class="scene-row">
            <span class="scene-meta">
              <span class="scene-name">{sc.scene}</span>
              <span class="scene-info">{sc.count} 条术语 · {new Date(sc.updated_at * 1000).toLocaleDateString()}</span>
            </span>
            <button class="del" onclick={() => removeScene(sc.scene)}>删除</button>
          </div>
        {:else}
          <p class="cardhint empty">尚未收集任何场景</p>
        {/each}
      </div>
    </section>

    <section>
      <h3>AI 分析（OpenAI 兼容接口）</h3>
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">接口地址</span><span class="tip">不配置则跳过 AI 步骤</span></span>
          <span class="control"><input bind:value={s.llm.api_base} oninput={touch} placeholder="https://…" /></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">API Key</span></span>
          <span class="control"><input type="password" bind:value={s.llm.api_key} oninput={touch} /></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">模型</span><span class="tip">需支持图片输入</span></span>
          <span class="control"><input bind:value={s.llm.model} oninput={touch} /></span>
        </div>
      </div>
    </section>

    <section>
      <h3>关键帧（高级）</h3>
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">场景切换灵敏度</span></span>
          <span class="control">
            <select bind:value={s.options.scene_threshold} onchange={touch}>
              <option value={null}>标准</option><option value={0.05}>更多页数（画面琐碎）</option>
              <option value={0.12}>更少页数（课件翻页少）</option>
            </select></span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">关键帧最小间隔</span></span>
          <span class="control">
            <select bind:value={s.options.min_gap} onchange={touch}>
              <option value={null}>2 秒</option><option value={5}>5 秒</option><option value={10}>10 秒</option>
            </select></span>
        </div>
      </div>
    </section>

    <section>
      <h3>日志</h3>
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">保留运行日志</span><span class="tip">排查问题用，保留 14 天</span></span>
          <input type="checkbox" bind:checked={s.app.keep_log} onchange={touch} />
        </div>
        <div class="item">
          <span class="meta"><span class="lab">日志文件夹</span></span>
          <button class="ghost" onclick={openLogs}>打开</button>
        </div>
      </div>
    </section>

    <section>
      <h3>更新</h3>
      <div class="card">
        <div class="item">
          <span class="meta"><span class="lab">当前版本</span><span class="tip">启动时自动检查并静默安装更新</span></span>
          <span class="control ver">{ver || "…"}</span>
        </div>
        <div class="item">
          <span class="meta"><span class="lab">检查更新</span>{#if updStatus}<span class="tip">{updStatus}</span>{/if}</span>
          <button class="ghost" disabled={checking} onclick={runUpdateCheck}>
            {checking ? "检查中…" : "检查"}
          </button>
        </div>
      </div>
    </section>
  {/if}
</div>

<style>
  .pane { max-width: 620px; }
  h2 { font-size: 17px; font-weight: 600; margin: 0 0 2px; }
  h3 { font-size: 12px; font-weight: 500; color: var(--ink2); margin: 18px 0 6px; }
  .hint { color: var(--ink2); font-size: 12px; margin: 2px 0 0; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 2px 14px; }
  .item { display: flex; align-items: center; gap: 14px; padding: 11px 0; }
  .item + .item { border-top: 1px solid var(--line); }
  .meta { flex: 1; min-width: 0; }
  .lab { display: block; font-size: 13px; font-weight: 500; }
  .tip { display: block; color: var(--ink2); font-size: 11.5px; margin-top: 2px; }
  .control { width: 200px; flex: none; }
  .control.ver { color: var(--ink2); font-size: 12px; text-align: right; }
  .cardhint { color: var(--ink2); font-size: 11.5px; margin: 9px 0; }
  .cardhint.empty { margin: 12px 0; }
  select, input { width: 100%; height: 32px; padding: 0 10px; border: 1px solid var(--line);
                  border-radius: 8px; font: inherit; font-size: 13px;
                  background: var(--card); color: var(--ink); }
  input[type="checkbox"] { width: 17px; height: 17px; flex: none; accent-color: var(--accent); }
  select:hover, input:hover { border-color: var(--faint); }
  select:focus, input:focus { outline: none; border-color: var(--accent);
                              box-shadow: 0 0 0 3px var(--accent-bg); }
  .scene-row { display: flex; align-items: center; gap: 10px; padding: 9px 0; }
  .scene-row + .scene-row, .cardhint + .scene-row { border-top: 1px solid var(--line); }
  .scene-meta { flex: 1; min-width: 0; }
  .scene-name { display: block; font-size: 13px; font-weight: 500; }
  .scene-info { display: block; color: var(--ink2); font-size: 11.5px; margin-top: 1px; }
  .del { border: 0; background: transparent; color: var(--ink2); cursor: pointer;
         font-size: 12px; padding: 4px 10px; border-radius: 6px; }
  .del:hover { color: var(--red); background: var(--bg); }
  .ghost { height: 30px; padding: 0 14px; border: 1px solid var(--line); background: var(--card);
           border-radius: 8px; cursor: pointer; font-size: 12.5px; color: var(--ink); }
  .ghost:hover { border-color: var(--faint); }
  .ghost:disabled { opacity: 0.6; cursor: default; }
  .err { color: var(--red); font-size: 13px; }
  .bad { color: var(--red); }
</style>
