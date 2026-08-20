import os
import sys
import subprocess
import shutil

def build_windows_app():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cs_file = os.path.join(base_dir, "apps", "desktop-tauri", "windows-host", "AuraStockDesktop.cs")
    release_win_dir = os.path.join(base_dir, "release", "windows")
    os.makedirs(release_win_dir, exist_ok=True)

    target_exe = os.path.join(release_win_dir, "AuraStock.exe")
    setup_exe = os.path.join(release_win_dir, "AuraStock-Setup-v1.1.0-x64.exe")
    csc_path = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

    if not os.path.exists(csc_path):
        print(f"[ERROR] csc.exe compiler not found at {csc_path}")
        return False

    print(f"Compiling AuraStock Windows Desktop Application using {csc_path}...")
    cmd = [
        csc_path,
        "/target:winexe",
        f"/out:{target_exe}",
        "/platform:x64",
        "/r:System.Windows.Forms.dll",
        "/r:System.Drawing.dll",
        "/r:System.dll",
        "/r:System.Core.dll",
        "/r:System.Security.dll",
        cs_file
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[ERROR] Compilation failed:")
        print(res.stderr)
        print(res.stdout)
        return False

    print(f"[OK] Generated Windows binary: {target_exe}")

    # Copy to setup installer name as well
    shutil.copy2(target_exe, setup_exe)
    print(f"[OK] Generated Windows setup installer: {setup_exe}")

    # Also copy web assets into release/windows/web
    web_dist = os.path.join(base_dir, "apps", "web", "dist")
    if os.path.exists(web_dist):
        win_web = os.path.join(release_win_dir, "web")
        shutil.copytree(web_dist, win_web, dirs_exist_ok=True)
        print(f"[OK] Bundled offline production Web UI into {win_web}")

    return True

if __name__ == "__main__":
    success = build_windows_app()
    if not success:
        sys.exit(1)
