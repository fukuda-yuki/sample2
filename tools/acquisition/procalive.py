"""Process-alive helper for detached chains on Windows (no tasklist/stdout dependency)."""
import ctypes
from ctypes import wintypes
_k = ctypes.WinDLL('kernel32', use_last_error=True)
_k.OpenProcess.restype = wintypes.HANDLE
_k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
_k.CloseHandle.argtypes = (wintypes.HANDLE,)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000; STILL_ACTIVE = 259; ERROR_ACCESS_DENIED = 5

def alive(pid):
    h = _k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # exists but not queryable
    try:
        code = wintypes.DWORD()
        if not _k.GetExitCodeProcess(h, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        _k.CloseHandle(h)
