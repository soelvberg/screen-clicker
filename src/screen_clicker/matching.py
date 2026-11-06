from __future__ import annotations

import re
from dataclasses import dataclass

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass(frozen=True)
class Word:
    text: str
    box: Box


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass(frozen=True)
class Match:
    target: str
    box: Box
    line_text: str


def normalize(text: str) -> str:
    return _NON_WORD.sub("", text.casefold())


def _union(words: list[Word]) -> Box:
    x1 = min(w.box.x for w in words)
    y1 = min(w.box.y for w in words)
    x2 = max(w.box.x + w.box.w for w in words)
    y2 = max(w.box.y + w.box.h for w in words)
    return Box(x1, y1, x2 - x1, y2 - y1)


def find_matches(lines: list[Line], targets: list[str]) -> list[Match]:
    """Find whole-word, case-insensitive occurrences of each target, in target order."""
    found: list[Match] = []
    for target in targets:
        wanted = [t for t in (normalize(p) for p in target.split()) if t]
        if not wanted:
            continue
        n = len(wanted)
        for line in lines:
            tokens = [(normalize(w.text), w) for w in line.words]
            tokens = [(t, w) for t, w in tokens if t]
            for i in range(len(tokens) - n + 1):
                if [t for t, _ in tokens[i : i + n]] == wanted:
                    found.append(Match(target, _union([w for _, w in tokens[i : i + n]]), line.text))
    return found
