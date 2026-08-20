import subprocess
import shutil
import os

def check_tools():
    tools = ["node", "npm", "rustc", "cargo", "rustup", "winget", "cl", "link", "msbuild"]
    print("=== TOOLCHAIN STATUS ===")
    for t in tools:
        path = shutil.which(t)
        if path:
            try:
                res = subprocess.run([t, "--version"], capture_output=True, text=True, timeout=5)
                v = (res.stdout or res.stderr).strip().split("\n")[0]
            except Exception as e:
                v = f"Found at {path} (version check note: {e})"
            print(f"[FOUND] {t:10s} -> {path} ({v})")
        else:
            print(f"[MISSING] {t:10s}")

    vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if os.path.exists(vswhere):
        print(f"[FOUND] vswhere -> {vswhere}")
        res = subprocess.run([vswhere, "-products", "*", "-property", "installationPath"], capture_output=True, text=True)
        print(f"VS Installations:\n{res.stdout.strip()}")
    else:
        print("[MISSING] vswhere")

if __name__ == "__main__":
    check_tools()
