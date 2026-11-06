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

# Shell processes are ancestors of everything launched from Explorer; don't treat them as "our" window.
_SHELL_NAMES = {"explorer.exe", "services.exe", "svchost.exe", "wininit.exe"}


@dataclass(frozen=True)
class ForegroundProcess:
    pid: int
    name: str
    monitor: dict[str, int] | None = None


def _monitor_of(hwnd: int) -> dict[str, int] | None:
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    hmon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTOPRIMARY)
    if not hmon or not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


def foreground_process() -> ForegroundProcess | None:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return ForegroundProcess(pid.value, psutil.Process(pid.value).name(), _monitor_of(hwnd))
    except psutil.Error:
        return None


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
