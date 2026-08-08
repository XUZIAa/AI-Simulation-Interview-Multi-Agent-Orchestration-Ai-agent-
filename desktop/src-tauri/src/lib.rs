mod sidecar;

use std::sync::Arc;

use tauri::{Manager, RunEvent, WindowEvent};

use sidecar::{backend_info, backend_start, backend_stop, Backend};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            app.manage(Arc::new(Backend::default()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_start,
            backend_info,
            backend_stop
        ])
        .on_window_event(|window, event| {
            // 窗口关掉就得把后端一起收走，否则 Python 会留在后台占着麦克风
            if matches!(event, WindowEvent::Destroyed) {
                if let Some(state) = window.app_handle().try_state::<Arc<Backend>>() {
                    state.shutdown();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Tauri 应用构建失败")
        .run(|app, event| {
            if matches!(event, RunEvent::Exit) {
                if let Some(state) = app.try_state::<Arc<Backend>>() {
                    state.shutdown();
                }
            }
        });
}
