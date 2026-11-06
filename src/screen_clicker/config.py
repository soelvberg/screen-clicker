from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_YAML = """\
# Screen Clicker configuration

# Seconds between screen scans.
interval_seconds: 1.0

# Minimum seconds before the same target can be clicked again.
cooldown_seconds: 5.0

# Texts to click when visible (case-insensitive, whole words).
# Order is priority: the first visible target is clicked.
targets: []
#  - text: return to lobby
#  - text: play
#    enabled: true

# Only act when the foreground process matches one of these globs
# (case-insensitive). Empty = any window.
process_patterns: []
#  - fortnite*

# Windows OCR language tag (must be installed in Windows).
ocr_language: en

# Screens taller than this are downscaled before OCR (speed vs. accuracy).
max_ocr_height: 1440

# Move the mouse back to where it was after clicking.
restore_mouse: true

# Global hotkey to pause/resume, e.g. f8 or ctrl+shift+p.
hotkey_pause: f8

# Relaunch elevated via UAC (only needed if the target app runs as admin).
run_as_admin: false

logging:
  file: logs/screen-clicker.log
  save_click_screenshots: true
  screenshot_dir: logs/clicks
"""


class ConfigError(ValueError):
    pass


@dataclass
class Target:
    text: str
    enabled: bool = True


@dataclass
class LoggingConfig:
    file: str = "logs/screen-clicker.log"
    save_click_screenshots: bool = True
    screenshot_dir: str = "logs/clicks"


@dataclass
class Config:
    interval_seconds: float = 1.0
    cooldown_seconds: float = 5.0
    targets: list[Target] = field(default_factory=list)
    process_patterns: list[str] = field(default_factory=list)
    ocr_language: str = "en"
    max_ocr_height: int = 1440
    restore_mouse: bool = True
    hotkey_pause: str = "f8"
    run_as_admin: bool = False
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _get(data: dict[str, Any], key: str, kind: type, default: Any) -> Any:
    value = data.get(key, default)
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
        raise ConfigError(f"'{key}' must be of type {kind.__name__}, got {value!r}")
    return value


def _parse_target(item: Any) -> Target:
    if isinstance(item, str):
        return Target(item.strip())
    if isinstance(item, dict) and isinstance(item.get("text"), str):
        return Target(item["text"].strip(), bool(item.get("enabled", True)))
    raise ConfigError(f"Invalid target entry: {item!r}")


def from_dict(data: dict[str, Any]) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping")
    defaults = Config()
    log_data = data.get("logging") or {}
    if not isinstance(log_data, dict):
        raise ConfigError("'logging' must be a mapping")
    targets = [_parse_target(t) for t in (data.get("targets") or [])]
    patterns = data.get("process_patterns") or []
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ConfigError("'process_patterns' must be a list of strings")
    cfg = Config(
        interval_seconds=_get(data, "interval_seconds", float, defaults.interval_seconds),
        cooldown_seconds=_get(data, "cooldown_seconds", float, defaults.cooldown_seconds),
        targets=[t for t in targets if t.text],
        process_patterns=[p.strip() for p in patterns if p.strip()],
        ocr_language=_get(data, "ocr_language", str, defaults.ocr_language),
        max_ocr_height=_get(data, "max_ocr_height", int, defaults.max_ocr_height),
        restore_mouse=_get(data, "restore_mouse", bool, defaults.restore_mouse),
        hotkey_pause=_get(data, "hotkey_pause", str, defaults.hotkey_pause),
        run_as_admin=_get(data, "run_as_admin", bool, defaults.run_as_admin),
        logging=LoggingConfig(
            file=_get(log_data, "file", str, defaults.logging.file),
            save_click_screenshots=_get(
                log_data, "save_click_screenshots", bool, defaults.logging.save_click_screenshots
            ),
            screenshot_dir=_get(log_data, "screenshot_dir", str, defaults.logging.screenshot_dir),
        ),
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.interval_seconds < 0.1:
        raise ConfigError("'interval_seconds' must be at least 0.1")
    if cfg.cooldown_seconds < 0:
        raise ConfigError("'cooldown_seconds' must be >= 0")
    if cfg.max_ocr_height < 240:
        raise ConfigError("'max_ocr_height' must be at least 240")
    if not cfg.ocr_language.strip():
        raise ConfigError("'ocr_language' must not be empty")
    if not cfg.hotkey_pause.strip():
        raise ConfigError("'hotkey_pause' must not be empty")


def to_dict(cfg: Config) -> dict[str, Any]:
    return {
        "interval_seconds": cfg.interval_seconds,
        "cooldown_seconds": cfg.cooldown_seconds,
        "targets": [{"text": t.text, "enabled": t.enabled} for t in cfg.targets],
        "process_patterns": list(cfg.process_patterns),
        "ocr_language": cfg.ocr_language,
        "max_ocr_height": cfg.max_ocr_height,
        "restore_mouse": cfg.restore_mouse,
        "hotkey_pause": cfg.hotkey_pause,
        "run_as_admin": cfg.run_as_admin,
        "logging": {
            "file": cfg.logging.file,
            "save_click_screenshots": cfg.logging.save_click_screenshots,
            "screenshot_dir": cfg.logging.screenshot_dir,
        },
    }


def load(path: Path) -> Config:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_YAML, encoding="utf-8")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    return from_dict(data)


def save(cfg: Config, path: Path) -> None:
    validate(cfg)
    text = yaml.safe_dump(to_dict(cfg), sort_keys=False, allow_unicode=True)
    path.write_text("# Screen Clicker configuration\n" + text, encoding="utf-8")
