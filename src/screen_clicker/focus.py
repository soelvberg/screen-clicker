from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from fnmatch import fnmatchcase

import psutil

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
_MONITOR_DEFAULTTOPRIMARY = 1


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetConsoleWindow.restype = wintypes.HWND
_dwmapi = ctypes.WinDLL("dwmapi")
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_GW_OWNER = 4
_GA_ROOTOWNER = 3
_MIN_REGION = 32

# Shell processes are ancestors of everything launched from Explorer; don't treat them as "our" window.
_SHELL_NAMES = {"explorer.exe", "services.exe", "svchost.exe", "wininit.exe"}


@dataclass(frozen=True)
class ForegroundProcess:
    pid: int
    name: str
    hwnd: int = 0
    region: dict[str, int] | None = None


def _monitor_rect(hwnd: int) -> wintypes.RECT | None:
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    hmon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTOPRIMARY)
    if not hmon or not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return None
    return info.rcMonitor


def _window_rect(hwnd: int) -> wintypes.RECT | None:
    rect = wintypes.RECT()
    # Extended frame bounds exclude the invisible resize borders that GetWindowRect includes.
    if _dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    ) == 0 or _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect
    return None


def window_region(hwnd: int) -> dict[str, int] | None:
    """Visible part of the window on its monitor, or None if minimized / off-screen."""
    win, mon = _window_rect(hwnd), _monitor_rect(hwnd)
    if not win or not mon:
        return None
    left, top = max(win.left, mon.left), max(win.top, mon.top)
    right, bottom = min(win.right, mon.right), min(win.bottom, mon.bottom)
    if right - left < _MIN_REGION or bottom - top < _MIN_REGION:
        return None
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def foreground_process() -> ForegroundProcess | None:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        name = psutil.Process(pid.value).name()
    except psutil.Error:
        return None
    return ForegroundProcess(pid.value, name, hwnd, window_region(hwnd))


def own_window_handles() -> frozenset[int]:
    """Our console window and the terminal window that hosts it (e.g. Windows Terminal)."""
    console = _kernel32.GetConsoleWindow()
    if not console:
        return frozenset()
    handles = {console, _user32.GetWindow(console, _GW_OWNER), _user32.GetAncestor(console, _GA_ROOTOWNER)}
    return frozenset(h for h in handles if h)


def own_process_ids() -> frozenset[int]:
    """PIDs of this process and its launching terminal, so we never click our own UI."""
    pids = {os.getpid()}
    try:
        for parent in psutil.Process().parents():
            if parent.name().lower() in _SHELL_NAMES:
                break
            pids.add(parent.pid)
    except psutil.Error:
        pass
    return frozenset(pids)


def matches(name: str | None, patterns: list[str]) -> bool:
    if not patterns:
        return True
    if not name:
        return False
    lowered = name.lower()
    return any(fnmatchcase(lowered, p.lower()) for p in patterns)
