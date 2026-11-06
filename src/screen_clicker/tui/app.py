from __future__ import annotations

import copy
import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Digits,
    Footer,
    Input,
    Label,
    OptionList,
    RichLog,
    Sparkline,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from .. import __version__, config, focus
from ..config import Config, ConfigError, Target, parse_region
from ..engine import ClickEvent, Engine, Event, ScanEvent, State, StatusEvent
from ..hotkey import Hotkey, start_hotkey
from ..matching import Line, normalize
from ..tray import Tray
from .logo import Logo

log = logging.getLogger("screen_clicker")

NEON = Theme(
    name="neon",
    primary="#00f5d4",
    secondary="#f15bb5",
    accent="#fee440",
    warning="#ffb000",
    error="#ff4365",
    success="#00f5a0",
    foreground="#e6edf7",
    background="#0b0f1a",
    surface="#111827",
    panel="#1a2238",
    dark=True,
)
THEMES = ["neon", "tokyo-night", "dracula", "catppuccin-mocha", "nord", "gruvbox", "textual-light"]

_STATE_CLASS = {
    State.STARTING: "-starting",
    State.RUNNING: "-running",
    State.WAITING: "-waiting",
    State.PAUSED: "-paused",
    State.ERROR: "-error",
    State.STOPPED: "-error",
}
_STATE_ICON = {
    State.STARTING: "◌",
    State.RUNNING: "●",
    State.WAITING: "◍",
    State.PAUSED: "⏸",
    State.ERROR: "✖",
    State.STOPPED: "■",
}
_LEVEL_STYLE = {
    logging.DEBUG: "dim",
    logging.INFO: "cyan",
    logging.WARNING: "yellow",
    logging.ERROR: "bold red",
    logging.CRITICAL: "bold white on red",
}


class EngineMessage(Message):
    def __init__(self, event: Event) -> None:
        super().__init__()
        self.event = event


class LogMessage(Message):
    def __init__(self, record: logging.LogRecord, text: str) -> None:
        super().__init__()
        self.record = record
        self.text = text


class TuiLogHandler(logging.Handler):
    def __init__(self, app: App) -> None:
        super().__init__(logging.INFO)
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._app.post_message(LogMessage(record, record.getMessage()))
        except Exception:
            self.handleError(record)


class StatCard(Vertical):
    def __init__(self, title: str, value: str = "0", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._value = value

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="title")
        yield Digits(self._value)

    def set(self, value: str) -> None:
        self.query_one(Digits).update(value)


def _union_center(line: Line) -> tuple[int, int]:
    x1 = min(w.box.x for w in line.words)
    y1 = min(w.box.y for w in line.words)
    x2 = max(w.box.x + w.box.w for w in line.words)
    y2 = max(w.box.y + w.box.h for w in line.words)
    return (x1 + x2) // 2, (y1 + y2) // 2


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


class ScreenClickerApp(App):
    CSS_PATH = "theme.tcss"
    TITLE = "Screen Clicker"
    BINDINGS = [
        Binding("space", "toggle_pause", "Pause/Resume"),
        Binding("a", "add_target", "Add target"),
        Binding("t", "next_theme", "Theme"),
        Binding("ctrl+s", "save_settings", "Save settings", show=False),
        Binding("escape", "blur", "Unfocus", show=False),
        Binding("f1", "tab('dash')", "Dash"),
        Binding("f2", "tab('targets')", "Targets"),
        Binding("f3", "tab('focus')", "Focus"),
        Binding("f4", "tab('preview')", "Preview"),
        Binding("f5", "tab('settings')", "Settings"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, engine: Engine, cfg: Config, config_path: Path) -> None:
        super().__init__()
        self.engine = engine
        self.cfg = copy.deepcopy(cfg)
        self.config_path = config_path
        self._latency: deque[float] = deque([0.0], maxlen=80)
        self._history: deque[ClickEvent] = deque(maxlen=100)
        self._recent: deque[str] = deque(maxlen=12)
        self._state: State | None = None
        self._fg: str | None = None
        self._hotkey: Hotkey | None = None
        self._tray: Tray | None = None
        self._log_handler = TuiLogHandler(self)

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Logo(subtitle=f"  OCR-driven auto clicker  ·  v{__version__}", id="logo")
            with Vertical(id="statusbox"):
                yield Static("◌ STARTING", id="pill", classes="-starting")
                yield Static("", id="fg")
                yield Static("", id="clock")
        with TabbedContent(id="tabs", initial="dash"):
            with TabPane("◉ Dashboard", id="dash"):
                with Horizontal(id="cards"):
                    yield StatCard("SCANS", id="c-scans")
                    yield StatCard("CLICKS", id="c-clicks")
                    yield StatCard("AVG OCR MS", id="c-ocr")
                    yield StatCard("UPTIME", "00:00", id="c-uptime")
                with Horizontal(id="dash-mid"):
                    with Vertical(classes="panel", id="p-latency"):
                        yield Sparkline(list(self._latency), id="spark")
                        yield DataTable(id="dash-targets", cursor_type="none", zebra_stripes=True)
                    with Vertical(classes="panel", id="p-history"):
                        yield DataTable(id="history", cursor_type="none", zebra_stripes=True)
                yield RichLog(id="log", wrap=True, max_lines=1000)
            with TabPane("◎ Targets", id="targets"):
                with Horizontal(classes="inputrow"):
                    yield Input(placeholder="Text to click, e.g.  return to lobby", id="target-input")
                    yield Input(placeholder="Region % (optional)  l,t,w,h", id="region-input")
                    yield Button("＋ Add", id="target-add", variant="primary")
                yield DataTable(id="targets-table", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="btnrow"):
                    yield Button("Toggle", id="target-toggle")
                    yield Button("▲ Up", id="target-up")
                    yield Button("▼ Down", id="target-down")
                    yield Button("⌗ Set region", id="target-region")
                    yield Button("✖ Remove", id="target-remove", variant="error")
                yield Static(
                    "Case-insensitive, whole words. Top of the list wins when several are visible. "
                    "[b]Enter[/b] toggles the selected row.\n"
                    "Region = left,top,width,height in % of the window, e.g. [b]60,75,40,25[/b] for the "
                    "bottom-right corner. Only text centered inside it counts. "
                    "[b]Set region[/b] applies the region field to the selected row (empty clears it). "
                    "The OCR Preview shows where text sits in %.",
                    classes="hint",
                )
            with TabPane("⌖ Focus", id="focus"):
                with Horizontal(classes="inputrow"):
                    yield Input(placeholder="Process glob, e.g.  game*.exe", id="pattern-input")
                    yield Button("＋ Add", id="pattern-add", variant="primary")
                with Horizontal(id="focus-body"):
                    with Vertical(classes="panel", id="p-patterns"):
                        yield DataTable(id="patterns-table", cursor_type="row", zebra_stripes=True)
                        yield Button("✖ Remove", id="pattern-remove", variant="error")
                    with Vertical(classes="panel", id="p-recent"):
                        yield OptionList(id="recent")
                yield Static(
                    "Clicks only happen while the foreground window belongs to a matching process. "
                    "Empty list = any window. Select a recent process to add it.",
                    classes="hint",
                )
            with TabPane("⌕ OCR Preview", id="preview"):
                yield Static(
                    "Text the OCR reads from the foreground window while this tab is open (no clicking from preview). "
                    "Switch to the target window for a moment and come back; the last result stays here.",
                    classes="hint",
                )
                yield DataTable(id="preview-table", cursor_type="row", zebra_stripes=True)
            with TabPane("⚙ Settings", id="settings"):
                with VerticalScroll(id="settings-form"):
                    yield from self._setting("Scan interval (s)", Input(id="s-interval", type="number"))
                    yield from self._setting("Cooldown per target (s)", Input(id="s-cooldown", type="number"))
                    yield from self._setting("OCR language", Input(id="s-lang"))
                    yield from self._setting("Max OCR height (px)", Input(id="s-maxh", type="integer"))
                    yield from self._setting("Pause hotkey", Input(id="s-hotkey"))
                    yield from self._setting("Restore mouse after click", Switch(id="s-restore"))
                    yield from self._setting("Save click screenshots", Switch(id="s-shots"))
                    yield from self._setting("Run as administrator", Switch(id="s-admin"))
                    with Horizontal(classes="btnrow"):
                        yield Button("💾 Save", id="settings-save", variant="success")
                        yield Button("↺ Revert", id="settings-revert")
                    yield Static(f"Config file: {self.config_path}", classes="hint")
        yield Footer()

    @staticmethod
    def _setting(label: str, widget) -> ComposeResult:
        with Horizontal(classes="setting"):
            yield Label(label)
            yield widget

    def on_mount(self) -> None:
        self.register_theme(NEON)
        self.theme = "neon"

        self.query_one("#p-latency").border_title = "OCR latency · targets"
        self.query_one("#p-history").border_title = "Click history"
        self.query_one("#log").border_title = "Event log"
        self.query_one("#p-patterns").border_title = "Process patterns"
        self.query_one("#p-recent").border_title = "Recent foreground processes"

        self.query_one("#dash-targets", DataTable).add_columns("Target", "On", "Hits")
        self.query_one("#history", DataTable).add_columns("Time", "Target", "Position", "Process")
        self.query_one("#targets-table", DataTable).add_columns("#", "Text", "Region %", "Enabled", "Hits")
        self.query_one("#patterns-table", DataTable).add_columns("Pattern", "Matches now")
        self.query_one("#preview-table", DataTable).add_columns("Text", "X %", "Y %", "Target")

        self._refresh_targets()
        self._refresh_patterns()
        self._load_settings_form()

        logging.getLogger("screen_clicker").addHandler(self._log_handler)
        if log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
        self.engine.subscribe(lambda ev: self.post_message(EngineMessage(ev)))
        self._hotkey = start_hotkey(self.cfg.hotkey_pause, self.engine.toggle_pause)
        self._tray = Tray(self.engine, lambda: self.call_from_thread(self.exit))
        self._tray.start()
        self.engine.start()

        self.set_interval(1, self._tick)
        self._tick()
        log.info("Config: %s", self.config_path)

    def on_unmount(self) -> None:
        logging.getLogger("screen_clicker").removeHandler(self._log_handler)
        if self._hotkey:
            self._hotkey.stop()
        if self._tray:
            self._tray.stop()
        self.engine.stop()

    # ---------- periodic / engine events ----------

    def _tick(self) -> None:
        self.query_one("#clock", Static).update(datetime.now().strftime("%a %d %b  %H:%M:%S"))
        self.query_one("#c-uptime", StatCard).set(_fmt_uptime(time.monotonic() - self.engine.stats.started))

    def on_engine_message(self, message: EngineMessage) -> None:
        ev = message.event
        if isinstance(ev, StatusEvent):
            self._show_status(ev)
        elif isinstance(ev, ScanEvent):
            self._show_scan(ev)
        elif isinstance(ev, ClickEvent):
            self._show_click(ev)

    def _show_status(self, ev: StatusEvent) -> None:
        if ev.state != self._state:
            self._state = ev.state
            pill = self.query_one("#pill", Static)
            pill.update(f"{_STATE_ICON[ev.state]} {ev.state.value}")
            for cls in set(_STATE_CLASS.values()):
                pill.remove_class(cls)
            pill.add_class(_STATE_CLASS[ev.state])
            self.sub_title = ev.state.value
        if ev.process != self._fg:
            self._fg = ev.process
            self.query_one("#fg", Static).update(f"⌖ {ev.process or '—'}")
            self._refresh_patterns()
            own = ev.detail == "own window in front"
            if ev.process and not own and ev.process not in self._recent:
                self._recent.appendleft(ev.process)
                recent = self.query_one("#recent", OptionList)
                recent.clear_options()
                recent.add_options(Option(name, id=name) for name in self._recent)

    def _show_scan(self, ev: ScanEvent) -> None:
        stats = self.engine.stats
        self._latency.append(ev.duration_ms)
        self.query_one("#spark", Sparkline).data = list(self._latency)
        self.query_one("#c-scans", StatCard).set(str(stats.scans))
        self.query_one("#c-ocr", StatCard).set(f"{stats.avg_ocr_ms:.0f}")
        if self.query_one(TabbedContent).active == "preview":
            hits = {m.line_text: m.target for m in ev.matches}
            table = self.query_one("#preview-table", DataTable)
            table.clear()
            for line in ev.lines[:300]:
                if not line.words:
                    continue
                px, py = ev.percent(*_union_center(line))
                target = hits.get(line.text)
                text = Text(line.text, style="bold reverse" if target else "")
                table.add_row(text, f"{px:.0f}", f"{py:.0f}", Text(target or "", style="bold green"))

    def _show_click(self, ev: ClickEvent) -> None:
        self._history.appendleft(ev)
        self.query_one("#c-clicks", StatCard).set(str(self.engine.stats.clicks))
        table = self.query_one("#history", DataTable)
        table.clear()
        for c in self._history:
            table.add_row(f"{c.at:%H:%M:%S}", Text(c.target, style="bold"), f"{c.x},{c.y}", c.process or "—")
        self._refresh_targets()
        self.notify(f"Clicked “{ev.target}”", title="Screen Clicker", timeout=3)

    def on_log_message(self, message: LogMessage) -> None:
        rec = message.record
        line = Text()
        line.append(datetime.fromtimestamp(rec.created).strftime("%H:%M:%S "), style="dim")
        line.append(f"{rec.levelname:<7} ", style=_LEVEL_STYLE.get(rec.levelno, ""))
        line.append(message.text)
        self.query_one("#log", RichLog).write(line)
        if rec.levelno >= logging.ERROR:
            self.notify(message.text, severity="error", timeout=8)

    # ---------- config helpers ----------

    def _commit(self) -> bool:
        try:
            config.save(self.cfg, self.config_path)
        except (ConfigError, OSError) as exc:
            self.notify(str(exc), severity="error")
            return False
        self.engine.update_config(self.cfg)
        return True

    def _refresh_targets(self) -> None:
        hits = self.engine.stats.hits
        on = Text("● on", style="bold green")
        off = Text("○ off", style="dim")
        main = self.query_one("#targets-table", DataTable)
        cursor = main.cursor_row
        main.clear()
        dash = self.query_one("#dash-targets", DataTable)
        dash.clear()
        for i, t in enumerate(self.cfg.targets, 1):
            n = str(hits.get(t.text.casefold(), 0))
            region = Text(str(t.region), style="bold magenta") if t.region else Text("anywhere", style="dim")
            main.add_row(str(i), t.text, region, on if t.enabled else off, n)
            dash.add_row(t.text, on if t.enabled else off, n)
        if self.cfg.targets:
            main.move_cursor(row=min(cursor, len(self.cfg.targets) - 1))

    def _refresh_patterns(self) -> None:
        table = self.query_one("#patterns-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for p in self.cfg.process_patterns:
            hit = focus.matches(self._fg, [p])
            table.add_row(p, Text("✔ yes", style="bold green") if hit else Text("—", style="dim"))
        if self.cfg.process_patterns:
            table.move_cursor(row=min(cursor, len(self.cfg.process_patterns) - 1))

    def _selected(self, table_id: str, items: list) -> int | None:
        table = self.query_one(table_id, DataTable)
        if not items or table.cursor_row < 0 or table.cursor_row >= len(items):
            return None
        return table.cursor_row

    # ---------- targets ----------

    @on(Button.Pressed, "#target-add")
    @on(Input.Submitted, "#target-input")
    @on(Input.Submitted, "#region-input")
    def _add_target(self) -> None:
        inp = self.query_one("#target-input", Input)
        region_inp = self.query_one("#region-input", Input)
        text = " ".join(inp.value.split())
        if not normalize(text):
            self.notify("Enter some text first", severity="warning")
            return
        if any(t.text.casefold() == text.casefold() for t in self.cfg.targets):
            self.notify(f"“{text}” is already a target", severity="warning")
            return
        try:
            region = parse_region(region_inp.value)
        except ConfigError as exc:
            self.notify(str(exc), severity="error")
            return
        self.cfg.targets.append(Target(text, region=region))
        if self._commit():
            inp.value = ""
            region_inp.value = ""
            self._refresh_targets()
            log.info("Added target '%s'%s", text, f" in region {region}" if region else "")

    @on(Button.Pressed, "#target-region")
    def _set_target_region(self) -> None:
        i = self._selected("#targets-table", self.cfg.targets)
        if i is None:
            self.notify("Select a target first", severity="warning")
            return
        region_inp = self.query_one("#region-input", Input)
        try:
            region = parse_region(region_inp.value)
        except ConfigError as exc:
            self.notify(str(exc), severity="error")
            return
        t = self.cfg.targets[i]
        t.region = region
        if self._commit():
            region_inp.value = ""
            self._refresh_targets()
            log.info("Region for '%s': %s", t.text, region or "anywhere")

    @on(Button.Pressed, "#target-toggle")
    @on(DataTable.RowSelected, "#targets-table")
    def _toggle_target(self) -> None:
        i = self._selected("#targets-table", self.cfg.targets)
        if i is None:
            return
        t = self.cfg.targets[i]
        t.enabled = not t.enabled
        if self._commit():
            self._refresh_targets()

    @on(Button.Pressed, "#target-up")
    def _target_up(self) -> None:
        self._move_target(-1)

    @on(Button.Pressed, "#target-down")
    def _target_down(self) -> None:
        self._move_target(1)

    def _move_target(self, delta: int) -> None:
        i = self._selected("#targets-table", self.cfg.targets)
        if i is None or not 0 <= i + delta < len(self.cfg.targets):
            return
        ts = self.cfg.targets
        ts[i], ts[i + delta] = ts[i + delta], ts[i]
        if self._commit():
            self._refresh_targets()
            self.query_one("#targets-table", DataTable).move_cursor(row=i + delta)

    @on(Button.Pressed, "#target-remove")
    def _remove_target(self) -> None:
        i = self._selected("#targets-table", self.cfg.targets)
        if i is None:
            return
        removed = self.cfg.targets.pop(i)
        if self._commit():
            self._refresh_targets()
            log.info("Removed target '%s'", removed.text)

    # ---------- focus patterns ----------

    def _add_pattern(self, pattern: str) -> None:
        pattern = pattern.strip().lower()
        if not pattern:
            self.notify("Enter a process pattern first", severity="warning")
            return
        if pattern in (p.lower() for p in self.cfg.process_patterns):
            self.notify(f"“{pattern}” already exists", severity="warning")
            return
        self.cfg.process_patterns.append(pattern)
        if self._commit():
            self._refresh_patterns()
            log.info("Added process pattern '%s'", pattern)

    @on(Button.Pressed, "#pattern-add")
    @on(Input.Submitted, "#pattern-input")
    def _add_pattern_from_input(self) -> None:
        inp = self.query_one("#pattern-input", Input)
        before = len(self.cfg.process_patterns)
        self._add_pattern(inp.value)
        if len(self.cfg.process_patterns) > before:
            inp.value = ""

    @on(OptionList.OptionSelected, "#recent")
    def _add_recent(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._add_pattern(event.option.id)

    @on(Button.Pressed, "#pattern-remove")
    def _remove_pattern(self) -> None:
        i = self._selected("#patterns-table", self.cfg.process_patterns)
        if i is None:
            return
        removed = self.cfg.process_patterns.pop(i)
        if self._commit():
            self._refresh_patterns()
            log.info("Removed process pattern '%s'", removed)

    # ---------- settings ----------

    def _load_settings_form(self) -> None:
        c = self.cfg
        self.query_one("#s-interval", Input).value = f"{c.interval_seconds:g}"
        self.query_one("#s-cooldown", Input).value = f"{c.cooldown_seconds:g}"
        self.query_one("#s-lang", Input).value = c.ocr_language
        self.query_one("#s-maxh", Input).value = str(c.max_ocr_height)
        self.query_one("#s-hotkey", Input).value = c.hotkey_pause
        self.query_one("#s-restore", Switch).value = c.restore_mouse
        self.query_one("#s-shots", Switch).value = c.logging.save_click_screenshots
        self.query_one("#s-admin", Switch).value = c.run_as_admin

    @on(Button.Pressed, "#settings-revert")
    def _revert_settings(self) -> None:
        self._load_settings_form()
        self.notify("Settings reverted")

    @on(Button.Pressed, "#settings-save")
    def action_save_settings(self) -> None:
        new = copy.deepcopy(self.cfg)
        try:
            new.interval_seconds = float(self.query_one("#s-interval", Input).value)
            new.cooldown_seconds = float(self.query_one("#s-cooldown", Input).value)
            new.max_ocr_height = int(self.query_one("#s-maxh", Input).value)
        except ValueError:
            self.notify("Interval, cooldown and max height must be numbers", severity="error")
            return
        new.ocr_language = self.query_one("#s-lang", Input).value.strip()
        new.hotkey_pause = self.query_one("#s-hotkey", Input).value.strip()
        new.restore_mouse = self.query_one("#s-restore", Switch).value
        new.logging.save_click_screenshots = self.query_one("#s-shots", Switch).value
        new.run_as_admin = self.query_one("#s-admin", Switch).value
        try:
            config.validate(new)
        except ConfigError as exc:
            self.notify(str(exc), severity="error")
            return

        old = self.cfg
        self.cfg = new
        if not self._commit():
            self.cfg = old
            return
        if new.hotkey_pause != old.hotkey_pause:
            if self._hotkey:
                self._hotkey.stop()
            self._hotkey = start_hotkey(new.hotkey_pause, self.engine.toggle_pause)
        if new.run_as_admin != old.run_as_admin:
            self.notify("Admin setting takes effect on next start", severity="warning")
        self.notify("Settings saved", title="⚙ Settings")
        log.info("Settings saved")

    # ---------- actions ----------

    def action_toggle_pause(self) -> None:
        self.engine.toggle_pause()

    def action_add_target(self) -> None:
        self.query_one(TabbedContent).active = "targets"
        self.query_one("#target-input", Input).focus()

    def action_next_theme(self) -> None:
        i = THEMES.index(self.theme) if self.theme in THEMES else -1
        self.theme = THEMES[(i + 1) % len(THEMES)]
        self.notify(f"Theme: {self.theme}", timeout=2)

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab
        self.set_focus(None)

    def action_blur(self) -> None:
        self.set_focus(None)

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        self.engine.preview = event.pane.id == "preview"
        if self.engine.preview:
            log.info("OCR preview on (scanning regardless of focus)")
