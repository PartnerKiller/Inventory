import subprocess
import time
import os
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

windows_found = []
def enum_windows_callback(hwnd, lparam):
    if user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            
            windows_found.append((pid.value, buff.value, hwnd, (w, h, rect.left, rect.top)))
    return True

def main():
    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    print("=== ALL VISIBLE APPLICATION WINDOWS ===")
    for pid, title, hwnd, dims in windows_found:
        if any(term in title.lower() for term in ["aurastock", "tauri", "inventory", "edge", "devtools"]):
            print(f"PID: {pid} | Title: \"{title}\" | HWND: {hwnd} | Dimensions: {dims}")

if __name__ == "__main__":
    main()
