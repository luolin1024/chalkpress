<!-- src/components/TasksPage.svelte -->
<!-- 任务列表页：上方数据看板（转换量 + 节省时间），下方历史记录管理。 -->
<script lang="ts">
  import { onMount } from "svelte";
  import HistoryCard from "./HistoryCard.svelte";
  import { request, startCore } from "../lib/ipc";

  type Item = { video: string; name: string; outdir: string; pages: number;
                summary: boolean; finished_at: number; exists: boolean;
                status?: string; duration?: number };

  // 估算口径：阅读一页讲义约 15 秒；老记录无视频时长时按每页对应 90 秒视频估算
  const READ_SECONDS_PER_PAGE = 15;
  const FALLBACK_VIDEO_SECONDS_PER_PAGE = 90;

  let stats = $state<{ videos: number; pages: number; summaries: number;
                       videoSeconds: number; savedSeconds: number } | null>(null);

  function fmtHm(sec: number): string {
    if (sec <= 0) return "0 分钟";
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return h ? `${h} 小时 ${m} 分钟` : `${m} 分钟`;
  }

  async function load() {
    // 子组件先于父 onMount 挂载：先等 core 就绪（同 HistoryCard 的处理）
    try { await startCore(); } catch { /* 拉取失败按空看板展示 */ }
    try {
      const { history } = await request<{ history: Item[] }>("history.list");
      const done = history.filter((h) => (h.status ?? "done") === "done");
      const pages = done.reduce((n, h) => n + (h.pages || 0), 0);
      const videoSeconds = done.reduce(
        (n, h) => n + (h.duration || (h.pages || 0) * FALLBACK_VIDEO_SECONDS_PER_PAGE), 0);
      stats = {
        videos: done.length,
        pages,
        summaries: done.filter((h) => h.summary).length,
        videoSeconds,
        savedSeconds: Math.max(0, videoSeconds - pages * READ_SECONDS_PER_PAGE),
      };
    } catch {
      stats = { videos: 0, pages: 0, summaries: 0, videoSeconds: 0, savedSeconds: 0 };
    }
  }
  onMount(load);
</script>

<section class="hero">
  {#if stats}
    <div class="card">
      <h3>数据看板</h3>
      <div class="tiles">
        <div class="tile"><b>{stats.videos}</b><span>转换视频</span></div>
        <div class="tile"><b>{stats.pages}</b><span>讲义页数</span></div>
        <div class="tile"><b>{stats.summaries}</b><span>AI 总结</span></div>
        <div class="tile"><b>{fmtHm(stats.videoSeconds)}</b><span>累计视频时长</span></div>
      </div>
      {#if stats.savedSeconds > 0}
        <p class="save">
          🎓 视频转讲义后，按每页阅读 15 秒估算，已为你省下约
          <b>{fmtHm(stats.savedSeconds)}</b> 的观看时间
        </p>
      {/if}
    </div>
  {/if}
  <HistoryCard onChanged={load} />
</section>

<style>
  .hero { display: flex; flex-direction: column; gap: 14px; margin-top: 6vh; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
          padding: 20px; }
  h3 { margin: 0 0 4px; }
  .tiles { display: flex; gap: 28px; margin: 12px 0; flex-wrap: wrap; }
  .tile b { font-size: 22px; display: block; }
  .tile span { color: var(--ink2); font-size: 12px; }
  .save { margin: 6px 0 0; color: var(--ink2); font-size: 13px; }
  .save b { color: var(--accent-dk); }
</style>
