//! Python 后端子进程的生命周期管理。
//!
//! 后端承担音频链路、编排引擎与数据库，必须常驻。它启动后会在 stdout 打一行
//! 握手信息告知实际端口与本次会话的 token —— 端口由系统分配，写死会撞车。

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::async_runtime::spawn_blocking;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const HANDSHAKE_PREFIX: &str = "INTERVIEWER_RPC ";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Endpoint {
    pub host: String,
    pub port: u16,
    pub token: String,
}

impl Endpoint {
    pub fn http_base(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
    pub fn ws_events(&self) -> String {
        format!("ws://{}:{}/events?token={}", self.host, self.port, self.token)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct BackendInfo {
    pub http_base: String,
    pub ws_events: String,
    pub token: String,
}

impl From<&Endpoint> for BackendInfo {
    fn from(e: &Endpoint) -> Self {
        Self {
            http_base: e.http_base(),
            ws_events: e.ws_events(),
            token: e.token.clone(),
        }
    }
}

/// 进程句柄与连接信息。前端随时可能刷新，信息要能重复取用。
#[derive(Default)]
pub struct Backend {
    endpoint: Mutex<Option<Endpoint>>,
    child: Mutex<Option<CommandChild>>,
}

impl Backend {
    pub fn info(&self) -> Option<BackendInfo> {
        self.endpoint.lock().ok()?.as_ref().map(BackendInfo::from)
    }

    /// 结束子进程。窗口关闭时必须调用，否则 Python 会变成孤儿进程继续占着麦克风。
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
        if let Ok(mut guard) = self.endpoint.lock() {
            *guard = None;
        }
    }
}

/// 拉起后端并等它报出连接信息。
///
/// 开发态走 uv 直接跑源码，打包态走随包分发的可执行文件；两者的差异只在这里。
pub async fn launch(app: AppHandle) -> Result<BackendInfo, String> {
    let state = app.state::<Arc<Backend>>();
    if let Some(info) = state.info() {
        return Ok(info);
    }

    let shell = app.shell();
    let command = if cfg!(debug_assertions) {
        let project_root = std::env::current_dir()
            .map_err(|e| format!("读取工作目录失败: {e}"))?
            .parent()
            .ok_or("找不到项目根目录")?
            .to_path_buf();
        shell
            .command("uv")
            .args(["run", "python", "-m", "interviewer.backend", "--port", "0"])
            .current_dir(project_root)
            // Windows 上 Python 的标准流默认走 GBK，这边按 UTF-8 读会得到乱码
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
    } else {
        // 后端带着 numpy、sounddevice 等一堆动态库，只能以目录形态分发：
        // 单文件模式每次启动都要解压，会白等好几秒。
        let dir = app
            .path()
            .resource_dir()
            .map_err(|e| format!("定位资源目录失败: {e}"))?
            .join("backend");
        let exe = dir.join("interviewer-backend.exe");
        if !exe.exists() {
            return Err(format!("随包后端缺失: {}", exe.display()));
        }
        shell
            .command(exe.to_string_lossy().to_string())
            .args(["--port", "0"])
            .current_dir(dir)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
    };

    let (mut rx, child) = command
        .spawn()
        .map_err(|e| format!("启动后端进程失败: {e}"))?;

    if let Ok(mut guard) = state.child.lock() {
        *guard = Some(child);
    }

    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let mut stderr_tail: Vec<String> = Vec::new();

    while Instant::now() < deadline {
        let event = match tokio::time::timeout(Duration::from_secs(5), rx.recv()).await {
            Ok(Some(ev)) => ev,
            Ok(None) => break,
            Err(_) => continue,
        };
        match event {
            CommandEvent::Stdout(bytes) => {
                let line = String::from_utf8_lossy(&bytes).to_string();
                for part in line.lines() {
                    if let Some(payload) = part.trim().strip_prefix(HANDSHAKE_PREFIX) {
                        let endpoint: Endpoint = serde_json::from_str(payload)
                            .map_err(|e| format!("握手信息无法解析: {e} / 原文: {payload}"))?;
                        let info = BackendInfo::from(&endpoint);
                        if let Ok(mut guard) = state.endpoint.lock() {
                            *guard = Some(endpoint);
                        }
                        // 握手之后仍要持续排空管道，否则子进程写满 stdout 会被阻塞
                        drain(app.clone(), rx);
                        return Ok(info);
                    }
                }
            }
            CommandEvent::Stderr(bytes) => {
                let text = String::from_utf8_lossy(&bytes).to_string();
                for part in text.lines() {
                    stderr_tail.push(part.to_string());
                }
                if stderr_tail.len() > 40 {
                    let cut = stderr_tail.len() - 40;
                    stderr_tail.drain(0..cut);
                }
            }
            CommandEvent::Terminated(status) => {
                return Err(format!(
                    "后端进程提前退出（code={:?}）。最后输出：\n{}",
                    status.code,
                    stderr_tail.join("\n")
                ));
            }
            _ => {}
        }
    }

    state.shutdown();
    Err(format!(
        "后端在 {} 秒内没有报出连接信息。最后输出：\n{}",
        STARTUP_TIMEOUT.as_secs(),
        stderr_tail.join("\n")
    ))
}

/// 持续读取子进程输出：转发日志、感知退出。
fn drain(app: AppHandle, mut rx: tauri::async_runtime::Receiver<CommandEvent>) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stderr(bytes) => {
                    let text = String::from_utf8_lossy(&bytes).to_string();
                    for line in text.lines() {
                        if !line.trim().is_empty() {
                            let _ = app.emit("backend-log", line.to_string());
                        }
                    }
                }
                CommandEvent::Terminated(status) => {
                    let _ = app.emit("backend-exit", status.code);
                    if let Some(state) = app.try_state::<Arc<Backend>>() {
                        state.shutdown();
                    }
                    return;
                }
                _ => {}
            }
        }
    });
}

#[tauri::command]
pub async fn backend_start(app: AppHandle) -> Result<BackendInfo, String> {
    launch(app).await
}

#[tauri::command]
pub fn backend_info(app: AppHandle) -> Option<BackendInfo> {
    app.state::<Arc<Backend>>().info()
}

#[tauri::command]
pub async fn backend_stop(app: AppHandle) -> Result<(), String> {
    let state = app.state::<Arc<Backend>>().inner().clone();
    spawn_blocking(move || state.shutdown())
        .await
        .map_err(|e| format!("停止后端失败: {e}"))
}
