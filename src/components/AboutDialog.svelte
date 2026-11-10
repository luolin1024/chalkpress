<!-- src/components/AboutDialog.svelte -->
<!-- 关于对话框：定位一句话 / GitHub / 反馈 / 商业授权。链接经 openUrl 交系统浏览器打开。 -->
<script lang="ts">
  import { openUrl } from "../lib/opener";

  let { ver = "", onDone }: { ver?: string; onDone: () => void } = $props();

  const REPO = "https://github.com/luolin1024/chalkpress";

  async function go(url: string) {
    await openUrl(url);
    onDone();
  }
</script>

<div class="mask" role="presentation">
  <div class="dialog" role="dialog" aria-modal="true" aria-label="关于 Chalkpress">
    <div class="head">
      <svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
        <rect width="64" height="64" rx="14" fill="#4f5bd5"/>
        <path d="M22 12 h14 l8 8 v30 a4 4 0 0 1 -4 4 h-18 a4 4 0 0 1 -4 -4 v-34 a4 4 0 0 1 4 -4 z" fill="#f6f3e7"/>
        <path d="M36 12 l8 8 h-8 z" fill="#c6ccee"/>
        <path d="M27 25 l14 8 -14 8 z" fill="#4f5bd5"/>
      </svg>
      <div class="who">
        <h3>Chalkpress {ver}</h3>
        <p class="tag">把讲座视频变成一册可检索、可打印的讲义 PDF</p>
        <p class="sub">30 分钟的课 → 5 分钟读完 · 全程本地处理，视频永不上传</p>
      </div>
    </div>

    <div class="links">
      <button class="item" onclick={() => go(REPO)}>
        <span class="k">GitHub</span>
        <span class="v">github.com/luolin1024/chalkpress ↗</span>
      </button>
      <button class="item" onclick={() => go(`${REPO}/issues`)}>
        <span class="k">问题反馈</span>
        <span class="v">GitHub Issues ↗</span>
      </button>
      <button class="item" onclick={() => go("mailto:2493468168@qq.com")}>
        <span class="k">商业授权</span>
        <span class="v">2493468168@qq.com ↗</span>
      </button>
    </div>

    <p class="license">个人与教育用途永久免费（PolyForm Noncommercial 1.0）；培训机构 / 企业商用需商业授权。应用内「设置 → 反馈」可直达开发者。</p>

    <div class="foot">
      <button class="primary" onclick={onDone}>关闭</button>
    </div>
  </div>
</div>

<style>
  .mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 100;
          display: flex; align-items: center; justify-content: center; }
  .dialog { width: 480px; max-width: calc(100vw - 48px); background: var(--bg);
            border: 1px solid var(--line); border-radius: 14px; padding: 22px 24px;
            box-shadow: 0 12px 40px rgba(0,0,0,.18); }
  .head { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 16px; }
  .logo { width: 44px; height: 44px; flex: none; border-radius: 10px; }
  h3 { margin: 0 0 4px; font-size: 16px; font-weight: 600; }
  .tag { margin: 0; font-size: 13px; color: var(--ink); font-weight: 500; }
  .sub { margin: 4px 0 0; font-size: 12px; color: var(--ink2); }
  .links { display: flex; flex-direction: column; gap: 6px; margin: 0 0 14px; }
  .item { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
          border: 1px solid var(--line); background: var(--card); border-radius: 9px;
          padding: 9px 12px; cursor: pointer; font-size: 12.5px; }
  .item:hover { border-color: var(--faint); }
  .k { flex: none; font-weight: 600; color: var(--ink); }
  .v { color: var(--ink2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .license { margin: 0 0 4px; font-size: 11.5px; line-height: 1.6; color: var(--faint); }
  .foot { display: flex; justify-content: flex-end; margin-top: 14px; }
  .primary { background: var(--accent); color: #fff; border: 0; border-radius: 10px;
             padding: 8px 22px; font-weight: 600; cursor: pointer; }
  .primary:hover { background: var(--accent-dk); }
</style>
