// src/lib/opener.ts
// openPath 统一出口：权限/系统层失败必须可见，不能静默吞掉（曾因此「点了没反应」）。
import { openPath as op } from "@tauri-apps/plugin-opener";

export async function openPath(path: string): Promise<void> {
  try {
    await op(path);
  } catch (e: unknown) {
    alert(`无法打开文件夹：${String(e instanceof Error ? e.message : e)}`);
  }
}
