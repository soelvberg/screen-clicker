from __future__ import annotations

from rich.text import Text
from textual.color import Color
from textual.widget import Widget

BIG = r"""
███████╗ ██████╗██████╗ ███████╗███████╗███╗   ██╗     ██████╗██╗     ██╗ ██████╗██╗  ██╗███████╗██████╗
██╔════╝██╔════╝██╔══██╗██╔════╝██╔════╝████╗  ██║    ██╔════╝██║     ██║██╔════╝██║ ██╔╝██╔════╝██╔══██╗
███████╗██║     ██████╔╝█████╗  █████╗  ██╔██╗ ██║    ██║     ██║     ██║██║     █████╔╝ █████╗  ██████╔╝
╚════██║██║     ██╔══██╗██╔══╝  ██╔══╝  ██║╚██╗██║    ██║     ██║     ██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
███████║╚██████╗██║  ██║███████╗███████╗██║ ╚████║    ╚██████╗███████╗██║╚██████╗██║  ██╗███████╗██║  ██║
╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝     ╚═════╝╚══════╝╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
""".strip("\n").splitlines()

SMALL = r"""
 ___  ___ ___ ___ ___ _  _    ___ _    ___ ___ _  _____ ___
/ __|/ __| _ \ __| __| \| |  / __| |  |_ _/ __| |/ / __| _ \
\__ \ (__|   / _|| _|| .` | | (__| |__ | | (__| ' <| _||   /
|___/\___|_|_\___|___|_|\_|  \___|____|___\___|_|\_\___|_|_\
""".strip("\n").splitlines()

TINY = ["▌ SCREEN CLICKER ▐"]

STOPS = [Color.parse(c) for c in ("#00f5d4", "#00bbf9", "#9b5de5", "#f15bb5", "#fee440")]


def _gradient(t: float) -> str:
    t = t % 1.0
    pos = t * len(STOPS)
    i = int(pos)
    return STOPS[i % len(STOPS)].blend(STOPS[(i + 1) % len(STOPS)], pos - i).hex


class Logo(Widget):
    """ASCII logo with a slowly flowing color gradient; picks a font that fits."""

    DEFAULT_CSS = "Logo { height: auto; width: 1fr; }"

    def __init__(self, subtitle: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._subtitle = subtitle
        self._phase = 0.0

    def on_mount(self) -> None:
        self.set_interval(1 / 12, self._advance)

    def _advance(self) -> None:
        self._phase = (self._phase + 0.006) % 1.0
        self.refresh()

    def _art(self, width: int | None = None) -> list[str]:
        width = width or self.size.width or 200
        for art in (BIG, SMALL):
            if max(map(len, art)) <= width:
                return art
        return TINY

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(self._art(width)) + (1 if self._subtitle else 0)

    def render(self) -> Text:
        art = self._art()
        span = max(map(len, art)) * 1.6
        text = Text(no_wrap=True, overflow="crop")
        for row, line in enumerate(art):
            for col, ch in enumerate(line):
                if ch == " ":
                    text.append(" ")
                else:
                    text.append(ch, style=f"bold {_gradient(col / span + row * 0.015 - self._phase)}")
            text.append("\n")
        if self._subtitle:
            text.append(self._subtitle, style="dim italic")
        return text
