import pytest

from screen_clicker import config
from screen_clicker.config import ConfigError, Region, Target, parse_region


def test_region_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config.Config(targets=[Target("Play", region=Region(60, 75, 40, 25)), Target("Ok")])
    config.save(cfg, path)
    assert config.load(path) == cfg


def test_parse_region():
    assert parse_region("") is None
    assert parse_region(None) is None
    assert parse_region(" 60, 75 ,40,25") == Region(60, 75, 40, 25)
    assert parse_region([0, 0, 100, 100]) == Region(0, 0, 100, 100)
    for bad in ("1,2,3", "a,b,c,d", "-1,0,10,10", "50,50,60,10", "0,0,0,10", 5):
        with pytest.raises(ConfigError):
            parse_region(bad)


def test_region_contains():
    r = Region(60, 75, 40, 25)
    assert r.contains(80, 90)
    assert not r.contains(50, 90)
    assert not r.contains(80, 50)


def test_default_file_created_and_loaded(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config.load(path)
    assert path.exists()
    assert cfg.interval_seconds == 1.0
    assert cfg.targets == []
    assert cfg.process_patterns == []


def test_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config.Config(targets=[Target("Play"), Target("Return to lobby", enabled=False)], process_patterns=["game*"])
    config.save(cfg, path)
    assert config.load(path) == cfg


def test_string_targets_and_int_interval():
    cfg = config.from_dict({"targets": ["play", {"text": "ok", "enabled": False}], "interval_seconds": 2})
    assert cfg.targets == [Target("play"), Target("ok", False)]
    assert cfg.interval_seconds == 2.0


@pytest.mark.parametrize(
    "data",
    [
        {"interval_seconds": 0},
        {"interval_seconds": "fast"},
        {"cooldown_seconds": -1},
        {"restore_mouse": "yes"},
        {"targets": [42]},
        {"process_patterns": "game*"},
        {"max_ocr_height": 10},
    ],
)
def test_invalid(data):
    with pytest.raises(ConfigError):
        config.from_dict(data)
