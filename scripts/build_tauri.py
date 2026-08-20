import os
import sys
import subprocess
import shutil

def build_tauri_release():
    real_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    base_dir = r"D:\aurastock_build"
    if not os.path.exists(base_dir):
        # Create junction if needed
        subprocess.run(["powershell", "-Command", f"New-Item -ItemType Junction -Path '{base_dir}' -Target '{real_dir}'"])

    tauri_dir = os.path.join(base_dir, "apps", "desktop-tauri")
    web_dir = os.path.join(real_dir, "apps", "web")
    
    cargo_bin = r"C:\Users\sayan\.cargo\bin"
    mingw_bin = r"C:\Users\sayan\AppData\Local\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT.LLVM_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin"
    env = os.environ.copy()
    env["PATH"] = cargo_bin + os.pathsep + mingw_bin + os.pathsep + env.get("PATH", "")

    # 1. Build web distribution
    print("\n[1/3] Building Web Production SPA Assets...")
    res_web = subprocess.run(["npm.cmd", "run", "build"], cwd=web_dir, env=env, capture_output=True, text=True)
    if res_web.returncode != 0:
        print("[ERROR] Web build failed:")
        print(res_web.stderr or res_web.stdout)
        return False
    print("[OK] Web production distribution built.")

    # 2. Build Tauri release
    print("\n[2/3] Compiling Native Tauri Rust Binary & Installer Bundle...")
    res_tauri = subprocess.run(["npx.cmd", "@tauri-apps/cli", "build"], cwd=tauri_dir, env=env, capture_output=True, text=True)
    if res_tauri.returncode != 0:
        print("[ERROR] Tauri build failed:")
        print(res_tauri.stderr)
        print(res_tauri.stdout)
        return False
    print("[OK] Native Tauri binary & bundle compiled.")

    # 3. Locate generated binary and installer
    target_dir = os.path.join(tauri_dir, "target", "release")
    candidates = [
        os.path.join(target_dir, "AuraStock.exe"),
        os.path.join(target_dir, "aurastock.exe"),
        os.path.join(target_dir, "aurastock-desktop.exe")
    ]
    target_bin = None
    for c in candidates:
        if os.path.exists(c):
            target_bin = c
            break

    if not target_bin:
        print(f"[ERROR] Could not find compiled binary in {target_dir}")
        return False

    size = os.path.getsize(target_bin)
    print(f"\n[3/3] Found Genuine Native Windows Binary: {target_bin} ({size:,} bytes)")

    # Stage into release/windows
    rel_win = os.path.join(base_dir, "release", "windows")
    os.makedirs(rel_win, exist_ok=True)
    dest_exe = os.path.join(rel_win, "AuraStock.exe")
    shutil.copy2(target_bin, dest_exe)
    print(f"[OK] Staged genuine native executable to: {dest_exe}")

    loader_dll = os.path.join(target_dir, "WebView2Loader.dll")
    if os.path.exists(loader_dll):
        shutil.copy2(loader_dll, os.path.join(rel_win, "WebView2Loader.dll"))
        print("[OK] Staged WebView2Loader.dll")

    # Check for bundle installers (NSIS/MSI)
    bundle_dir = os.path.join(target_dir, "bundle")
    if os.path.exists(bundle_dir):
        for root, _, files in os.walk(bundle_dir):
            for f in files:
                if f.endswith((".exe", ".msi")):
                    src_f = os.path.join(root, f)
                    dest_f = os.path.join(rel_win, f)
                    shutil.copy2(src_f, dest_f)
                    print(f"[OK] Staged genuine installer: {dest_f} ({os.path.getsize(src_f):,} bytes)")

    return True

if __name__ == "__main__":
    success = build_tauri_release()
    if not success:
        sys.exit(1)
