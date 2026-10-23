import ctypes
import os
import winreg

APP_MUTEX = "Local\\Finfusion.Client.V1"
RUNTIME_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def prerequisites():
    version = None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for flag in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + RUNTIME_ID, 0, winreg.KEY_READ | flag) as key:
                    candidate = winreg.QueryValueEx(key, "pv")[0]
                    if candidate and candidate != "0.0.0.0":
                        version = candidate
            except OSError:
                pass
    release = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            release = winreg.QueryValueEx(key, "Release")[0]
    except OSError:
        pass
    return {"webview2": version, "netRelease": release}


class AppMutex:
    def __init__(self):
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = (ctypes.c_void_p,)

    def acquire(self):
        self.handle = self.kernel.CreateMutexW(None, False, APP_MUTEX)
        return bool(self.handle) and ctypes.get_last_error() != 183

    def release(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, "Finfusion Client", 0x10)
