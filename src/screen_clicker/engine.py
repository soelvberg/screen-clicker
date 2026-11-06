from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import ImageDraw

from . import clicker, focus
from .config import Config, Target
from .detector import Detector, OcrUnavailable, ScanResult
from .matching import Line, Match, find_matches

log = logging.getLogger("screen_clicker")


class State(Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING FOR FOCUS"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class StatusEvent:
    state: State
    process: str | None
    detail: str = ""


@dataclass(frozen=True)
class ScanEvent:
    duration_ms: float
    lines: tuple[Line, ...]
    matches: tuple[Match, ...]
    frame: tuple[int, int, int, int] = (0, 0, 1, 1)  # scanned window: left, top, width, height

    def percent(self, x: int, y: int) -> tuple[float, float]:
        left, top, width, height = self.frame
        return (x - left) * 100 / width, (y - top) * 100 / height


@dataclass(frozen=True)
class ClickEvent:
    at: datetime
    target: str
    x: int
    y: int
    process: str | None


Event = StatusEvent | ScanEvent | ClickEvent


def in_regions(matches: list[Match], targets: list[Target], frame: tuple[int, int, int, int]) -> list[Match]:
    """Keep matches whose center lies in the region of a target with that text (no region = anywhere)."""
    left, top, width, height = frame
    kept = []
    for m in matches:
        x, y = m.box.center
        px, py = (x - left) * 100 / width, (y - top) * 100 / height
        if any(t.text == m.target and (t.region is None or t.region.contains(px, py)) for t in targets):
            kept.append(m)
    return kept


@dataclass
class Stats:
    scans: int = 0
    clicks: int = 0
    total_ocr_ms: float = 0.0
    hits: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    @property
    def avg_ocr_ms(self) -> float:
        return self.total_ocr_ms / self.scans if self.scans else 0.0


class Engine:
    def __init__(self, cfg: Config, base_dir: Path) -> None:
        self._cfg = copy.deepcopy(cfg)
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = False
        self._listeners: list[Callable[[Event], None]] = []
        self._last_click: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._own_pids = focus.own_process_ids()
        self._own_hwnds = focus.own_window_handles()
        self.preview = False
        self.stats = Stats()
        self.state = State.STARTING

    # -- public API (any thread) --

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        log.info("Paused" if paused else "Resumed")
        self._wake.set()

    def toggle_pause(self) -> bool:
        self.set_paused(not self._paused)
        return self._paused

    def update_config(self, cfg: Config) -> None:
        with self._lock:
            self._cfg = copy.deepcopy(cfg)
        self._wake.set()

    # -- engine thread --

    def _emit(self, event: Event) -> None:
        if isinstance(event, StatusEvent):
            self.state = event.state
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                log.exception("Event listener failed")

    def _config(self) -> Config:
        with self._lock:
            return self._cfg

    def _run(self) -> None:
        detector: Detector | None = None
        detector_key: tuple[str, int] | None = None
        try:
            while not self._stop.is_set():
                cfg = self._config()
                started = time.monotonic()

                key = (cfg.ocr_language, cfg.max_ocr_height)
                if key != detector_key:
                    if detector:
                        detector.close()
                    detector, detector_key = None, key
                    try:
                        detector = Detector(*key)
                        log.info("OCR engine ready (language=%s)", cfg.ocr_language)
                    except OcrUnavailable as exc:
                        log.error("%s", exc)
                        self._emit(StatusEvent(State.ERROR, None, str(exc)))

                if detector:
                    self._tick(cfg, detector)

                self._wake.wait(max(0.05, cfg.interval_seconds - (time.monotonic() - started)))
                self._wake.clear()
        except Exception as exc:
            log.exception("Engine crashed")
            self._emit(StatusEvent(State.ERROR, None, str(exc)))
        finally:
            if detector:
                detector.close()
            self._emit(StatusEvent(State.STOPPED, None))

    def _tick(self, cfg: Config, detector: Detector) -> None:
        fg = focus.foreground_process()
        name = fg.name if fg else None
        own_window = fg is not None and (fg.pid in self._own_pids or fg.hwnd in self._own_hwnds)
        focused = not own_window and focus.matches(name, cfg.process_patterns)

        if self._paused:
            self._emit(StatusEvent(State.PAUSED, name))
        elif own_window:
            self._emit(StatusEvent(State.WAITING, name, "own window in front"))
        elif not focused:
            self._emit(StatusEvent(State.WAITING, name))
        else:
            self._emit(StatusEvent(State.RUNNING, name))

        can_click = focused and not self._paused
        # Only read the foreground window, so text in other windows (including our own UI) is never clicked.
        if not (can_click or (self.preview and not own_window)) or not fg or not fg.region:
            return

        result = detector.scan(fg.region)
        targets = [t for t in cfg.targets if t.enabled]
        r = fg.region
        frame = (r["left"], r["top"], r["width"], r["height"])
        matches = in_regions(find_matches(result.lines, [t.text for t in targets]), targets, frame)
        self.stats.scans += 1
        self.stats.total_ocr_ms += result.duration_ms
        self._emit(ScanEvent(result.duration_ms, tuple(result.lines), tuple(matches), frame))

        if not can_click:
            return
        now = time.monotonic()
        for match in matches:
            key = match.target.casefold()
            if now - self._last_click.get(key, -1e9) < cfg.cooldown_seconds:
                continue
            x, y = match.box.center
            clicker.click(x, y, restore=cfg.restore_mouse)
            self._last_click[key] = now
            self.stats.clicks += 1
            self.stats.hits[key] = self.stats.hits.get(key, 0) + 1
            log.info("Clicked '%s' at (%d, %d) in %s", match.target, x, y, name)
            event = ClickEvent(datetime.now(), match.target, x, y, name)
            self._emit(event)
            if cfg.logging.save_click_screenshots:
                self._save_screenshot(cfg, result, match, event)
            break

    def _save_screenshot(self, cfg: Config, result: ScanResult, match: Match, event: ClickEvent) -> None:
        try:
            out_dir = self._base_dir / cfg.logging.screenshot_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            img = result.image()
            ox, oy = result.origin
            b = match.box
            draw = ImageDraw.Draw(img)
            draw.rectangle((b.x - ox - 6, b.y - oy - 6, b.x - ox + b.w + 6, b.y - oy + b.h + 6), outline="#ff2d95", width=4)
            safe = "".join(c if c.isalnum() else "_" for c in match.target)[:40]
            img.save(out_dir / f"{event.at:%Y%m%d-%H%M%S}-{safe}.png")
        except Exception:
            log.exception("Failed to save click screenshot")
