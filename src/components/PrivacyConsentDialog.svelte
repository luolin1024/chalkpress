<!-- src/components/PrivacyConsentDialog.svelte -->
<!-- 首次启动隐私确认：一次性，选择持久化到 config.toml [privacy] analytics_consent。
     必须二选一（无跳过/遮罩关闭）；拒绝仅不发送统计，功能完全不受影响。 -->
<script lang="ts">
  import { request } from "../lib/ipc";

  let { onDone }: { onDone: () => void } = $props();

  let busy = $state(false);
  let err = $state("");

  async function choose(consent: boolean) {
    if (busy) return;
    busy = true;
    err = "";
    try {
      await request("privacy.set", { consent });
      onDone();
    } catch (e: unknown) {
      err = String(e instanceof Error ? e.message : e);
      busy = false;
    }
  }
</script>

<div class="mask" role="presentation">
  <div class="dialog" role="dialog" aria-modal="true" aria-label="隐私声明">
    <h3>欢迎使用 Chalkpress</h3>

    <div class="row">
      <span class="mark">✅</span>
      <p><b>我们收集：</b>软件内使用数据（转换次数、功能使用统计、匿名崩溃报告）——仅用于改进产品</p>
    </div>
    <div class="row">
      <span class="mark">❌</span>
      <p><b>我们不收集：</b>您的视频内容、转写文字、讲义内容、个人身份信息</p>
    </div>

    <p class="local">您的视频全程本地处理，永不上传。</p>

    {#if err}<p class="err">✗ {err}，请重试</p>{/if}

    <div class="foot">
      <button class="ghost" disabled={busy} onclick={() => choose(false)}>不同意（功能正常，仅不发送统计）</button>
      <button class="primary" disabled={busy} onclick={() => choose(true)}>同意并继续</button>
    </div>
  </div>
</div>

<style>
  .mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 100;
          display: flex; align-items: center; justify-content: center; }
  .dialog { width: 480px; max-width: calc(100vw - 48px); background: var(--bg);
            border: 1px solid var(--line); border-radius: 14px; padding: 22px 24px;
            box-shadow: 0 12px 40px rgba(0,0,0,.18); }
  h3 { margin: 0 0 16px; font-size: 16px; font-weight: 600; }
  .row { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 12px; }
  .mark { flex: none; font-size: 14px; line-height: 1.5; }
  .row p { margin: 0; font-size: 13px; line-height: 1.6; color: var(--ink); }
  .local { margin: 14px 0 0; font-size: 13px; font-weight: 500; color: var(--accent-dk); }
  .err { color: var(--red); font-size: 12.5px; margin: 10px 0 0; }
  .foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
  .ghost { background: var(--card); color: var(--ink); border: 1px solid var(--line);
           border-radius: 10px; padding: 8px 14px; font-size: 12.5px; cursor: pointer; }
  .ghost:hover { border-color: var(--faint); }
  .ghost:disabled { opacity: .5; cursor: default; }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 8px 22px; font-weight: 600; cursor: pointer; }
  .primary:hover { background: var(--accent-dk); }
  .primary:disabled { opacity: .5; cursor: default; }
</style>
