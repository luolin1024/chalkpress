<!-- src/components/HistoryCard.svelte -->
<!-- 转换历史档案：跨会话保留"转过什么"（含暂停/失败动态），独立于任务队列（删任务不清历史）。 -->
<script lang="ts">
  import { onMount } from "svelte";
  import { openPath } from "../lib/opener";
  import { request, startCore } from "../lib/ipc";

  type Item = { video: string; name: string; outdir: string; pages: number;
                summary: boolean; finished_at: number; exists: boolean; status?: string };

  const CHIP: Record<string, string> = { paused: "已暂停", failed: "失败" };
  const st = (h: Item): string => h.status ?? "done";

  let items = $state<Item[] | null>(null);

  async function load() {
    // 子组件先于父 onMount 挂载：core 可能尚未启动，先等就绪再拉取
    try { await startCore(); } catch { /* 启动失败时下面照常抛错置空 */ }
    try {
      items = (await request<{ history: Item[] }>("history.list")).history;
    } catch {
      items = [];
    }
  }
  let { onChanged }: { onChanged?: () => void } = $props();
  async function clearAll() {
    if (!confirm("清空历史记录？（不会删除已生成的讲义文件）")) return;
    try {
      await request("history.clear");
      await load();
      onChanged?.();
    } catch { /* 清理失败不影响展示 */ }
  }
  async function del(h: Item) {
    if (!confirm(`删除「${h.name}」的转换记录？（不会删除已生成的讲义文件）`)) return;
    try {
      await request("history.delete", { video: h.video, finished_at: h.finished_at });
      await load();
      onChanged?.();
    } catch { /* 删除失败不影响展示 */ }
  }
  onMount(load);
</script>

{#if items && items.length}
  <section class="hist">
    <div class="card">
      <div class="head">
        <h4>历史记录 <span class="count">{items.length}</span></h4>
        <button class="del" onclick={clearAll}>清空记录</button>
      </div>
      {#each items as h (h.video + h.finished_at)}
        <div class="row">
          {#if CHIP[st(h)]}<span class="chip {st(h)}">{CHIP[st(h)]}</span>{/if}
          <span class="meta">
            <span class="name">{h.name}</span>
            <span class="info">
              {new Date(h.finished_at * 1000).toLocaleString()} · {h.pages} 页{#if h.summary} · AI 总结 ✓{/if}
              {#if !h.exists}<span class="gone">· 产物已删除</span>{/if}
            </span>
          </span>
          {#if h.exists}
            <button class="open" title={h.outdir} onclick={() => openPath(h.outdir)}>打开</button>
          {/if}
          <button class="del" title="删除该条记录" onclick={() => del(h)}>✕</button>
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  .hist { width: 100%; margin-top: 0; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
          padding: 4px 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; padding: 9px 0; }
  h4 { margin: 0; font-size: 13px; font-weight: 600; }
  .count { color: var(--ink2); font-weight: 500; font-size: 12px; margin-left: 2px; }
  .del { border: 0; background: transparent; color: var(--ink2); cursor: pointer;
         font-size: 12px; padding: 4px 10px; border-radius: 6px; }
  .del:hover { color: var(--red); background: var(--bg); }
  .row { display: flex; align-items: center; gap: 10px; padding: 9px 0;
         border-top: 1px solid var(--line); }
  .chip { flex: none; font-size: 11px; border-radius: 99px; padding: 1px 9px; }
  .chip.paused { color: #8a6d1a; border: 1px solid #efe3bd; background: #fbf4dd; }
  .chip.failed { color: var(--red); border: 1px solid #f0d3d1; background: #fbeeee; }
  .meta { flex: 1; min-width: 0; }
  .name { display: block; font-size: 13px; font-weight: 500;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .info { display: block; color: var(--ink2); font-size: 11.5px; margin-top: 1px; }
  .gone { color: var(--faint); }
  .open { flex: none; height: 28px; padding: 0 12px; border: 1px solid var(--line);
          background: var(--card); border-radius: 7px; cursor: pointer; font-size: 12px; color: var(--ink); }
  .open:hover { border-color: var(--faint); }
</style>
