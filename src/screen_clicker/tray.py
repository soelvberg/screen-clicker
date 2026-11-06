from __future__ import annotations

import logging
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

from .engine import Engine, Event, State, StatusEvent

log = logging.getLogger("screen_clicker")

_COLORS = {
    State.RUNNING: "#00f5a0",
    State.WAITING: "#7f8aa3",
    State.PAUSED: "#ffb000",
    State.ERROR: "#ff4365",
    State.STARTING: "#00f5d4",
    State.STOPPED: "#7f8aa3",
}


def make_icon(color: str, size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, w = size // 2, max(2, size // 12)
    d.ellipse((w, w, size - w, size - w), outline=color, width=w)
    d.ellipse((c - size // 8, c - size // 8, c + size // 8, c + size // 8), fill=color)
    for a, b in (((c, 0), (c, size // 4)), ((c, size * 3 // 4), (c, size)),
                 ((0, c), (size // 4, c)), ((size * 3 // 4, c), (size, c))):
        d.line((a, b), fill=color, width=w)
    return img


class Tray:
    def __init__(self, engine: Engine, on_quit: Callable[[], None]) -> None:
        self._engine = engine
        self._on_quit = on_quit
        self._state = State.STARTING
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"Screen Clicker - {self._state.value}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Paused", self._toggle, checked=lambda _: self._engine.paused, default=True),
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon("screen-clicker", make_icon(_COLORS[self._state]), "Screen Clicker", menu)
        engine.subscribe(self._on_event)

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            log.debug("Tray stop failed", exc_info=True)

    def _toggle(self, *_: object) -> None:
        self._engine.toggle_pause()

    def _quit(self, *_: object) -> None:
        self._on_quit()

    def _on_event(self, event: Event) -> None:
        if isinstance(event, StatusEvent) and event.state != self._state:
            self._state = event.state
            self._icon.icon = make_icon(_COLORS[event.state])
            self._icon.title = f"Screen Clicker - {event.state.value}"
            self._icon.update_menu()
