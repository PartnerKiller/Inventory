import os
import subprocess
import time

def diagnose():
    exe = r"C:\TestAuraStockApp\aurastock.exe"
    env = os.environ.copy()
    env["RUST_LOG"] = "trace"
    env["RUST_BACKTRACE"] = "1"
    env["WEBVIEW2_LOG_VERBOSITY"] = "3"

    print("Launching:", exe)
    p = subprocess.Popen(
        [exe],
        cwd=r"C:\TestAuraStockApp",
        env=env
    )

    print("Launched PID:", p.pid)
    time.sleep(3)

    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    
    found = []
    def enum_cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == p.pid:
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            vis = user32.IsWindowVisible(hwnd)

            found.append({
                "hwnd": hwnd,
                "title": buff.value,
                "class": class_buff.value,
                "visible": vis,
                "rect": (w, h, rect.left, rect.top)
            })
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    print(f"Windows belonging to PID {p.pid}:")
    for w in found:
        print(f"  - HWND: {w['hwnd']} | Visible: {w['visible']} | Title: '{w['title']}' | Class: '{w['class']}' | Dims: {w['rect']}")

    log_path = os.path.expandvars(r"%LOCALAPPDATA%\com.aurastock.inventory\logs\AuraStock.log")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        print("\nLast 15 lines of AuraStock.log:")
        for l in lines[-15:]:
            print("  ", l.strip())

    time.sleep(2)
    p.kill()

if __name__ == "__main__":
    diagnose()
