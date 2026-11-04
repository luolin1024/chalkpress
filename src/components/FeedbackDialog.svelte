<!-- src/components/FeedbackDialog.svelte -->
<!-- 反馈弹窗：类型/内容/联系方式/可选诊断日志 → core feedback.submit → 飞书开放 API 写多维表格。
     凭据缺失时设置页隐藏入口，本组件不会被挂载；提交失败降级引导 GitHub Issues。 -->
<script lang="ts">
  import { request } from "../lib/ipc";
  import { openUrl } from "../lib/opener";
  import { ISSUES_URL } from "../lib/feedback";

  let { onClose }: { onClose: () => void } = $props();

  const TYPES = [
    { key: "bug", label: "bug 报告" },
    { key: "suggestion", label: "功能建议" },
    { key: "question", label: "使用问题" },
    { key: "other", label: "其他" },
  ] as const;

  let ftype = $state<string>("bug");
  let content = $state("");
  let contact = $state("");
  let attachLog = $state(false);
  let busy = $state(false);
  let ok = $state(false);
  let err = $state("");

  const len = $derived(content.trim().length);
  const valid = $derived(len >= 10 && len <= 500);

  async function submit() {
    if (!valid || busy) return;
    busy = true;
    err = "";
    try {
      const r = await request<{ ok: boolean }>("feedback.submit",
        { type: ftype, content: content.trim(), contact: contact.trim(), attach_log: attachLog });
      if (r.ok) ok = true;
      else err = "提交失败";
    } catch (e: unknown) {
      err = String(e instanceof Error ? e.message : e);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && !busy && onClose()} />

<div class="mask" role="presentation" onclick={(e) => e.target === e.currentTarget && !busy && onClose()}>
  <div class="dialog" role="dialog" aria-modal="true" aria-label="问题反馈">
    <h3>问题反馈</h3>

    {#if ok}
      <div class="done">
        <div class="mark">✓</div>
        <p>已提交，感谢反馈！</p>
        <button class="primary" onclick={onClose}>完成</button>
      </div>
    {:else}
      <div class="field">
        <span class="lab">反馈类型</span>
        <div class="seg">
          {#each TYPES as t (t.key)}
            <button class:active={ftype === t.key} onclick={() => (ftype = t.key)}>{t.label}</button>
          {/each}
        </div>
      </div>

      <div class="field">
        <span class="lab">内容描述 <span class="req">*</span>
          <span class="cnt" class:over={len > 500}>{len}/500</span></span>
        <textarea rows={6} maxlength={500} bind:value={content}
                  placeholder="遇到了什么问题，或希望增加什么功能？（10-500 字）"></textarea>
      </div>

      <div class="field">
        <span class="lab">联系方式 <span class="opt">选填</span></span>
        <input bind:value={contact} placeholder="邮箱 / 微信，方便我们回访（自愿）" />
      </div>

      <label class="attach">
        <input type="checkbox" bind:checked={attachLog} />
        <span>附带诊断日志
          <span class="tip">附最近一次运行日志的末尾 50 行，便于定位问题；日志可能包含文件路径等本机信息</span>
        </span>
      </label>

      {#if err}
        <p class="err">✗ {err}，请重试；仍失败可通过
          <button class="link" onclick={() => openUrl(ISSUES_URL)}>GitHub Issues</button> 反馈</p>
      {/if}

      <div class="foot">
        <button class="ghost" disabled={busy} onclick={onClose}>取消</button>
        <button class="primary" disabled={!valid || busy} onclick={submit}>
          {busy ? "提交中…" : "提交"}
        </button>
      </div>
    {/if}
  </div>
</div>

<style>
  .mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 100;
          display: flex; align-items: center; justify-content: center; }
  .dialog { width: 460px; max-width: calc(100vw - 48px); max-height: calc(100vh - 48px);
            overflow-y: auto; background: var(--bg); border: 1px solid var(--line);
            border-radius: 14px; padding: 20px 22px; box-shadow: 0 12px 40px rgba(0,0,0,.18); }
  h3 { margin: 0 0 16px; font-size: 16px; font-weight: 600; }
  .field { margin-bottom: 14px; }
  .lab { display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; }
  .req { color: var(--red); }
  .opt { color: var(--faint); font-size: 11.5px; font-weight: 400; margin-left: 4px; }
  .cnt { float: right; color: var(--faint); font-size: 11.5px; font-weight: 400; }
  .cnt.over { color: var(--red); }
  textarea, input:not([type="checkbox"]) { width: 100%; box-sizing: border-box; padding: 8px 10px;
    border: 1px solid var(--line); border-radius: 8px; font: inherit; font-size: 13px;
    background: var(--card); color: var(--ink); resize: vertical; }
  textarea:focus, input:not([type="checkbox"]):focus { outline: none; border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-bg); }
  .seg { display: flex; gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; width: fit-content; }
  .seg button { border: 0; background: var(--card); padding: 7px 14px; font-size: 12.5px;
                cursor: pointer; color: var(--ink2); border-right: 1px solid var(--line); }
  .seg button:last-child { border-right: 0; }
  .seg button.active { background: var(--accent); color: #fff; font-weight: 600; }
  .attach { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; cursor: pointer; }
  .attach input { width: 16px; height: 16px; margin-top: 2px; flex: none; accent-color: var(--accent); }
  .attach .tip { display: block; color: var(--ink2); font-size: 11.5px; margin-top: 2px; }
  .err { color: var(--red); font-size: 12.5px; margin: 10px 0 0; }
  .link { border: 0; background: none; color: var(--accent); cursor: pointer;
          font-size: 12.5px; padding: 0; text-decoration: underline; }
  .foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
  .ghost { background: var(--card); color: var(--ink); border: 1px solid var(--line);
           border-radius: 10px; padding: 8px 18px; cursor: pointer; }
  .ghost:hover { border-color: var(--faint); }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 8px 24px; font-weight: 600; cursor: pointer; }
  .primary:hover { background: var(--accent-dk); }
  .primary:disabled { opacity: .5; cursor: default; }
  .done { text-align: center; padding: 18px 0 8px; }
  .mark { width: 44px; height: 44px; border-radius: 50%; background: var(--accent-bg);
          color: var(--accent-dk); font-size: 22px; display: flex; align-items: center;
          justify-content: center; margin: 0 auto 12px; }
  .done p { margin: 0 0 16px; font-size: 14px; }
</style>
