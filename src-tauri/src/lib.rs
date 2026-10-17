// chalkpress 桌面壳：Rust 侧接管 core（sidecar）子进程生命周期与 stdio 行协议 IPC。
// 前端 → invoke(core_request) → Rust 管道直连 → core stdin/stdout（JSON lines，id 关联）；
// 事件经 app.emit("core-event") 推给前端。
// 不走 WebView fetch / plugin-shell：系统代理与安全软件会吞回环请求、事件投递跨平台不可靠。
// （core 亦保留回环 HTTP 模式供 CLI/测试：设置 CHALKPRESS_IPC_PORT 即启用。）
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};

const REQUEST_TIMEOUT_MS: u64 = 30_000;

struct CoreState {
    stdin: Mutex<Option<ChildStdin>>,
    pending: Mutex<HashMap<u64, mpsc::SyncSender<Value>>>,
    next_id: AtomicU64,
}

type SharedCore = Arc<CoreState>;

fn json_escape(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

/// 与主程序同目录的 core sidecar（打包态由 Tauri externalBin 落位）。
fn core_path() -> Result<std::path::PathBuf, String> {
    let dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .ok_or("无法定位应用目录")?;
    // Windows 上 Tauri externalBin 落位为 chalkpress-core.exe
    #[cfg(windows)]
    let p = dir.join("chalkpress-core.exe");
    #[cfg(not(windows))]
    let p = dir.join("chalkpress-core");
    if p.is_file() {
        Ok(p)
    } else {
        Err(format!("sidecar 不存在：{}", p.display()))
    }
}

fn spawn_core() -> Result<Child, String> {
    let mut cmd = Command::new(core_path()?);
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    // core 是控制台子系统程序，Windows 下不设此标志会弹出黑色控制台窗口
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn().map_err(|e| format!("拉起 core 失败：{e}"))
}

fn write_line(state: &SharedCore, line: &str) -> Result<(), String> {
    let guard = state
        .stdin
        .lock()
        .map_err(|_| "core stdin 锁不可用".to_string())?;
    let mut stdin = guard.as_ref().ok_or("core stdin 未初始化")?;
    stdin.write_all(line.as_bytes()).map_err(|e| format!("写入失败：{e}"))?;
    stdin.write_all(b"\n").map_err(|e| format!("写入失败：{e}"))?;
    stdin.flush().map_err(|e| format!("flush 失败：{e}"))
}

/// core stdout 读取线程：按 id 分发响应到等待方，事件经 emit 推给前端。
fn pump(mut stdout: BufReader<impl std::io::Read>, app: AppHandle, state: SharedCore) {
    eprintln!("[ipc] pump thread started");
    let mut line = String::new();
    loop {
        line.clear();
        match stdout.read_line(&mut line) {
            Ok(0) => break, // EOF：core 退出
            Ok(_) => {}
            Err(_) => break,
        }
        let raw = line.trim();
        if raw.is_empty() {
            continue;
        }
        let Ok(v) = serde_json::from_str::<Value>(raw) else { continue };
        let Some(id) = v.get("id").and_then(Value::as_u64) else {
            // 事件：转发前端（_seq 由 core 维护，前端按序消费）
            let _ = app.emit("core-event", v);
            continue;
        };
        if let Some(tx) = state.pending.lock().ok().and_then(|mut p| p.remove(&id)) {
            let _ = tx.send(v);
        }
    }
    eprintln!("[ipc] pump exited (core eof)");
    let _ = app.emit("core-exit", ());
}

fn core_spawn_inner(app: AppHandle, state: &SharedCore) -> Result<(), String> {
    let mut guard = state.stdin.lock().map_err(|_| "锁不可用".to_string())?;
    if guard.is_some() {
        return Ok(());  // 已运行
    }
    eprintln!("[ipc] spawning core");
    let mut child = spawn_core()?;
    let stdin = child.stdin.take().ok_or("无法接管 core stdin")?;
    let stdout = child.stdout.take().ok_or("无法接管 core stdout")?;
    *guard = Some(stdin);
    let state_for_pump = state.clone();
    std::thread::spawn(move || pump(BufReader::new(stdout), app, state_for_pump));
    Ok(())
}

#[tauri::command]
fn core_spawn(app: AppHandle, state: tauri::State<SharedCore>) -> Result<(), String> {
    core_spawn_inner(app, &state)
}

#[tauri::command]
fn ping() -> String {
    eprintln!("[ipc] ping invoked");
    "pong".to_string()
}

/// 前端 RPC：写入一行请求，等待同 id 响应。返回 Value（含 result 或 error）。
/// 必须为 async：Tauri 的同步命令在主线程执行，阻塞等待会冻结整个 WebView。
#[tauri::command]
async fn core_request(
    state: tauri::State<'_, SharedCore>,
    method: String,
    params: String,
    timeout_ms: Option<u64>,
) -> Result<Value, String> {
    let id = state.next_id.fetch_add(1, Ordering::Relaxed) + 1;
    let (tx, rx) = mpsc::sync_channel::<Value>(1);
    state
        .pending
        .lock()
        .map_err(|_| "锁不可用".to_string())?
        .insert(id, tx);
    let body = format!(
        "{{\"id\":{},\"method\":\"{}\",\"params\":{}}}",
        id,
        json_escape(&method),
        if params.trim().is_empty() { "{}".to_string() } else { params }
    );
    if let Err(e) = write_line(&state, &body) {
        state.pending.lock().ok().and_then(|mut p| p.remove(&id));
        return Err(e);
    }
    eprintln!("[ipc] → id={id} {method}");
    let timeout = Duration::from_millis(timeout_ms.unwrap_or(REQUEST_TIMEOUT_MS));
    match rx.recv_timeout(timeout) {
        Ok(v) => {
            eprintln!("[ipc] ← id={id} ok");
            Ok(v)
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
            state.pending.lock().ok().and_then(|mut p| p.remove(&id));
            eprintln!("[ipc] ← id={id} timeout");
            Err(format!("{method} 请求超时"))
        }
        Err(_) => {
            eprintln!("[ipc] ← id={id} channel closed");
            Err("core 响应通道关闭".to_string())
        }
    }
}

pub fn run() {
    let state: SharedCore = Arc::new(CoreState {
        stdin: Mutex::new(None),
        pending: Mutex::new(HashMap::new()),
        next_id: AtomicU64::new(0),
    });
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(state.clone())
        .invoke_handler(tauri::generate_handler![ping, core_spawn, core_request])
        .setup(move |app| {
            let handle = app.handle().clone();
            // 启动即拉起 core；失败不阻塞窗口（前端 startCore 会重试）
            let _ = core_spawn_inner(handle, &state);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
