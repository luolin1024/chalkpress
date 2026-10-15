import { check, Update } from "@tauri-apps/plugin-updater";

export async function autoUpdate(): Promise<string | null> {
  try {
    const u: Update | null = await check();
    if (!u) return null;
    await u.downloadAndInstall();
    return u.version;
  } catch (e) {
    console.error("updater:", e);
    return null;
  }
}

/** 手动检查更新（设置页按钮）：返回人话状态。有新版则下载安装，重启生效。 */
export async function checkUpdate(): Promise<string> {
  try {
    const u: Update | null = await check();
    if (!u) return "当前已是最新版本";
    const v = u.version;
    await u.downloadAndInstall();
    return `已更新到 v${v}，重启应用后生效`;
  } catch (e) {
    return `检查失败：${String(e)}`;
  }
}
