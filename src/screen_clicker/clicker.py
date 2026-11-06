from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_MOUSEEVENTF_ABSOLUTE = 0x8000
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77
_SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 78, 79


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


# MOUSEINPUT is the largest member of the INPUT union, so it alone gives the correct size.
class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]


_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT


def _send(flags: int, dx: int = 0, dy: int = 0) -> None:
    inp = _INPUT(_INPUT_MOUSE, _MOUSEINPUT(dx, dy, 0, flags, 0, 0))
    if _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _move(x: int, y: int) -> None:
    vx = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    vy = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    vw = max(2, _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN))
    vh = max(2, _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN))
    dx = round((x - vx) * 65535 / (vw - 1))
    dy = round((y - vy) * 65535 / (vh - 1))
    _send(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK, dx, dy)
    _user32.SetCursorPos(x, y)


def click(x: int, y: int, restore: bool = True) -> None:
    previous = cursor_pos() if restore else None
    _move(x, y)
    time.sleep(0.04)
    _send(_MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.06)
    _send(_MOUSEEVENTF_LEFTUP)
    if previous:
        time.sleep(0.05)
        _move(*previous)
