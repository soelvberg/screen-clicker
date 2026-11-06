from __future__ import annotations

import logging
from collections.abc import Callable

from pynput import keyboard

log = logging.getLogger("screen_clicker")

_MODIFIERS = {"ctrl", "alt", "shift", "cmd", "win"}


def to_pynput(spec: str) -> str:
    """Convert e.g. 'ctrl+shift+p' or 'F8' to pynput's '<ctrl>+<shift>+p' / '<f8>' format."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")
    out = []
    for part in parts:
        if part == "win":
            part = "cmd"
        out.append(part if len(part) == 1 else f"<{part}>")
    return "+".join(out)


class Hotkey:
    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self._listener = keyboard.GlobalHotKeys({to_pynput(spec): callback})
        self._listener.daemon = True
        self.spec = spec

    def start(self) -> None:
        self._listener.start()
        log.info("Hotkey '%s' toggles pause", self.spec)

    def stop(self) -> None:
        self._listener.stop()


def start_hotkey(spec: str, callback: Callable[[], None]) -> Hotkey | None:
    try:
        hotkey = Hotkey(spec, callback)
        hotkey.start()
        return hotkey
    except Exception as exc:
        log.error("Invalid hotkey '%s': %s", spec, exc)
        return None
