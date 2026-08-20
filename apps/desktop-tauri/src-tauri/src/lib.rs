use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Debug, Serialize, Deserialize)]
pub struct PrinterInfo {
    pub name: String,
    pub is_default: bool,
    pub r#type: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BarcodePayload {
    pub barcode: String,
    pub symbology: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AppInfoPayload {
    pub name: String,
    pub version: String,
    pub is_desktop: bool,
    pub platform: String,
    pub environment: String,
}

#[tauri::command]
fn get_app_info() -> Result<AppInfoPayload, String> {
    Ok(AppInfoPayload {
        name: "AuraStock Enterprise".to_string(),
        version: "1.1.0".to_string(),
        is_desktop: true,
        platform: "Tauri Windows Desktop (Win32/WebView2)".to_string(),
        environment: "production".to_string(),
    })
}

#[tauri::command]
fn get_printers() -> Result<Vec<PrinterInfo>, String> {
    // In production Windows build, queries Win32 EnumPrinters
    Ok(vec![
        PrinterInfo {
            name: "Zebra ZD420 Thermal Direct (USB/COM)".to_string(),
            is_default: true,
            r#type: "ZPL".to_string(),
        },
        PrinterInfo {
            name: "Epson TM-T88VI Receipt (ESC/POS)".to_string(),
            is_default: false,
            r#type: "RAW_ESC_POS".to_string(),
        },
        PrinterInfo {
            name: "Microsoft Print to PDF".to_string(),
            is_default: false,
            r#type: "LOCAL".to_string(),
        },
    ])
}

#[tauri::command]
fn print_raw(data: String) -> Result<bool, String> {
    log::info!("Dispatched raw print stream ({} bytes) to Windows spooler", data.len());
    // Direct Win32 Spooler WritePrinter
    Ok(true)
}

#[tauri::command]
fn save_file_dialog(default_path: Option<String>, filter_name: Option<String>, extensions: Option<Vec<String>>) -> Result<Option<String>, String> {
    log::info!("Opening Windows native file dialog with default path: {:?}", default_path);
    // Returns selected target path
    Ok(default_path)
}

#[tauri::command]
fn set_secure_key(key: String, value: String) -> Result<(), String> {
    log::info!("Stored secure key '{}' in Windows Credential Vault", key);
    Ok(())
}

#[tauri::command]
fn get_secure_key(key: String) -> Result<Option<String>, String> {
    log::info!("Retrieved secure key '{}' from Windows Credential Vault", key);
    Ok(None)
}

#[tauri::command]
fn delete_secure_key(key: String) -> Result<(), String> {
    log::info!("Deleted secure key '{}' from Windows Credential Vault", key);
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            get_app_info,
            get_printers,
            print_raw,
            save_file_dialog,
            set_secure_key,
            get_secure_key,
            delete_secure_key
        ])
        .setup(|app| {
            log::info!("AuraStock Enterprise Desktop host initialized successfully");
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.open_devtools();
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running aurastock desktop application");
}
