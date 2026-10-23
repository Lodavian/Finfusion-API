import ctypes as ct
from ctypes import wintypes as wt
import struct
import zlib
def capture_own_window(root, path):
    user, gdi = ct.windll.user32, ct.windll.gdi32
    user.GetParent.argtypes, user.GetParent.restype = [wt.HWND], wt.HWND
    user.GetWindowDC.argtypes, user.GetWindowDC.restype = [wt.HWND], wt.HDC
    user.GetWindowRect.argtypes = [wt.HWND, ct.POINTER(wt.RECT)]
    user.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    user.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [wt.HDC], wt.HDC
    gdi.CreateCompatibleBitmap.argtypes, gdi.CreateCompatibleBitmap.restype = [wt.HDC, ct.c_int, ct.c_int], wt.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [wt.HDC, wt.HANDLE], wt.HANDLE
    gdi.DeleteObject.argtypes = [wt.HANDLE]
    gdi.DeleteDC.argtypes = [wt.HDC]
    gdi.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ct.c_void_p, ct.c_void_p, wt.UINT]
    hwnd = int(root)
    rect = wt.RECT()
    if not user.GetWindowRect(hwnd, ct.byref(rect)):
        raise RuntimeError('Cannot get own window bounds')
    width, height = rect.right - rect.left, rect.bottom - rect.top
    source = user.GetWindowDC(hwnd)
    dc = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    previous = gdi.SelectObject(dc, bitmap)
    try:
        if not user.PrintWindow(hwnd, dc, 2):
            raise RuntimeError('Own window rendering failed')
        gdi.SelectObject(dc, previous)
        previous = None
        info = ct.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
        pixels = ct.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(dc, bitmap, 0, height, pixels, info, 0) != height:
            raise RuntimeError('Own window pixels unavailable')
        raw = pixels.raw
        rows = bytearray()
        for row in range(height):
            rows.append(0)
            for col in range(width):
                index = (row * width + col) * 4
                rows.extend((raw[index+2], raw[index+1], raw[index], 255))
        def chunk(kind, content):
            return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind+content))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
    finally:
        if previous:
            gdi.SelectObject(dc, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)
        user.ReleaseDC(hwnd, source)
