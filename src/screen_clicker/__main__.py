from __future__ import annotations

import argparse
import ctypes
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Absolute imports so this file also works as the PyInstaller entry script.
from screen_clicker import config, elevate
from screen_clicker.config import ConfigError

log = logging.getLogger("screen_clicker")


def _set_dpi_aware() -> None:
    # Per-monitor v2, so screen capture and mouse coordinates use the same physical pixels.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)


def _default_config_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "config.yaml"


def _message_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Screen Clicker", 0x10)


def _setup_logging(cfg: config.Config, base_dir: Path) -> None:
    log.setLevel(logging.INFO)
    log_file = base_dir / cfg.logging.file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    log.addHandler(handler)


def _run_headless(engine, cfg: config.Config) -> None:
    from screen_clicker.hotkey import start_hotkey
    from screen_clicker.tray import Tray

    # Drop the console window; the tray icon is the UI in this mode.
    ctypes.windll.kernel32.FreeConsole()
    done = threading.Event()
    tray = Tray(engine, done.set)
    hotkey = start_hotkey(cfg.hotkey_pause, engine.toggle_pause)
    tray.start()
    engine.start()
    log.info("Running headless")
    try:
        done.wait()
    finally:
        if hotkey:
            hotkey.stop()
        tray.stop()
        engine.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="screen-clicker", description="OCR-driven auto clicker.")
    parser.add_argument("-c", "--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument("--headless", action="store_true", help="Run without the TUI (tray icon only)")
    args = parser.parse_args(argv)

    _set_dpi_aware()
    config_path = (args.config or _default_config_path()).resolve()
    try:
        cfg = config.load(config_path)
    except ConfigError as exc:
        msg = f"Config error in {config_path}:\n{exc}"
        _message_box(msg) if args.headless else print(msg, file=sys.stderr)
        return 2

    if cfg.run_as_admin and not elevate.is_admin():
        forwarded = ["--config", str(config_path)] + (["--headless"] if args.headless else [])
        if elevate.relaunch_as_admin(forwarded):
            return 0
        print("Elevation was declined; continuing without admin rights.", file=sys.stderr)

    base_dir = config_path.parent
    _setup_logging(cfg, base_dir)

    from screen_clicker.engine import Engine

    engine = Engine(cfg, base_dir)
    if args.headless:
        _run_headless(engine, cfg)
    else:
        from screen_clicker.tui.app import ScreenClickerApp

        ScreenClickerApp(engine, cfg, config_path).run()
    log.info("Exited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
