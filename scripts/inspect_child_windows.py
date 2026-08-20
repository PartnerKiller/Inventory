import ctypes
from ctypes import wintypes
import subprocess
import time
import os

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

def inspect_children():
    exe = r"C:\TestAuraStockApp\aurastock.exe"
    p = subprocess.Popen([exe], cwd=r"C:\TestAuraStockApp")
    print("Launched PID:", p.pid)
    time.sleep(3)

    all_windows = []
    def enum_all(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
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

        all_windows.append({
            "hwnd": hwnd,
            "pid": pid.value,
            "title": buff.value,
            "class": class_buff.value,
            "visible": vis,
            "rect": (w, h, rect.left, rect.top)
        })
        return True

    user32.EnumWindows(WNDENUMPROC(enum_all), 0)

    print("\n--- Top-level windows for Tauri/WebView2 processes ---")
    for w in all_windows:
        if w["pid"] == p.pid or "Edge" in w["class"] or "Chrome" in w["class"] or "Tauri" in w["class"]:
            print(f"HWND: {w['hwnd']} | PID: {w['pid']} | Class: '{w['class']}' | Title: '{w['title']}' | Visible: {w['visible']} | Dims: {w['rect']}")

            # Enumerate children of this window
            children = []
            def enum_child(chwnd, lparam):
                clength = user32.GetWindowTextLengthW(chwnd)
                cbuff = ctypes.create_unicode_buffer(clength + 1)
                user32.GetWindowTextW(chwnd, cbuff, clength + 1)

                cclass = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(chwnd, cclass, 256)

                crect = wintypes.RECT()
                user32.GetWindowRect(chwnd, ctypes.byref(crect))
                cw = crect.right - crect.left
                ch = crect.bottom - crect.top
                cvis = user32.IsWindowVisible(chwnd)
                children.append((chwnd, cclass.value, cbuff.value, cvis, (cw, ch, crect.left, crect.top)))
                return True

            user32.EnumChildWindows(w["hwnd"], WNDENUMPROC(enum_child), 0)
            if children:
                print(f"   -> {len(children)} Child Windows:")
                for chwnd, cclass, ctitle, cvis, cdims in children:
                    print(f"      [Child HWND {chwnd}] Class: '{cclass}' | Title: '{ctitle}' | Visible: {cvis} | Dims: {cdims}")

    time.sleep(1)
    p.kill()

if __name__ == "__main__":
    inspect_children()
