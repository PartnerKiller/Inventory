import ctypes
from ctypes import wintypes
import time
import os
import subprocess
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

def capture_aurastock_window():
    exe = r"C:\TestAuraStockApp\aurastock.exe"
    p = subprocess.Popen([exe], cwd=r"C:\TestAuraStockApp")
    print("Launched PID:", p.pid)
    time.sleep(3)

    target_hwnd = None
    def enum_cb(hwnd, lparam):
        nonlocal target_hwnd
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == p.pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            if "AuraStock" in buff.value:
                target_hwnd = hwnd
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    if not target_hwnd:
        print("Could not find AuraStock window handle.")
        p.kill()
        return

    print("Found target HWND:", target_hwnd)

    rect = wintypes.RECT()
    user32.GetWindowRect(target_hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    print(f"Window size: {w} x {h}")

    # Capture DC
    hwnd_dc = user32.GetWindowDC(target_hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bitmap)

    # PrintWindow (PW_RENDERFULLCONTENT = 2)
    res = user32.PrintWindow(target_hwnd, mem_dc, 2)
    if not res:
        res = user32.PrintWindow(target_hwnd, mem_dc, 0)
    print("PrintWindow result:", res)

    # Convert to PIL Image
    bmpinfo = ctypes.create_string_buffer(40) # BITMAPINFOHEADER
    # struct: biSize(4), biWidth(4), biHeight(4), biPlanes(2), biBitCount(2), biCompression(4), biSizeImage(4), biXPelsPerMeter(4), biYPelsPerMeter(4), biClrUsed(4), biClrImportant(4)
    import struct
    struct.pack_into("<IiiHHIIIIII", bmpinfo, 0, 40, w, -h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, bmpinfo, 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    
    artifact_dir = r"C:\Users\sayan\.gemini\antigravity\brain\38289c6a-f7cf-430f-8fbd-64a3ae219b28"
    out_path = os.path.join(artifact_dir, "aurastock_window_capture.png")
    img.save(out_path)
    print(f"Screenshot saved to: {out_path}")

    # Inspect colors: check if all pixels are black/blank or if UI elements exist
    colors = img.getcolors(maxcolors=w*h)
    print(f"Unique colors count: {len(colors)}")
    top_colors = sorted(colors, key=lambda x: x[0], reverse=True)[:5]
    print("Top colors (count, RGBA):")
    for cnt, col in top_colors:
        pct = (cnt / (w * h)) * 100
        print(f"  {pct:.1f}% -> {col}")

    # Clean up
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(target_hwnd, hwnd_dc)

    time.sleep(1)
    p.kill()

if __name__ == "__main__":
    capture_aurastock_window()
