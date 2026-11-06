from screen_clicker.config import Region, Target
from screen_clicker.engine import in_regions
from screen_clicker.matching import Box, Line, Word, find_matches

# Window at (1000, 500), 1000 x 800 px.
FRAME = (1000, 500, 1000, 800)


def word(text: str, x: int, y: int) -> Line:
    return Line((Word(text, Box(x - 20, y - 10, 40, 20)),))


def test_region_picks_the_right_play():
    lines = [word("Play", 1100, 600), word("PLAY", 1850, 1200)]  # top-left (10%,12.5%), bottom-right (85%,87.5%)
    targets = [Target("play", region=Region(60, 75, 40, 25))]
    kept = in_regions(find_matches(lines, ["play"]), targets, FRAME)
    assert [m.box.center for m in kept] == [(1850, 1200)]


def test_no_region_keeps_all():
    lines = [word("Play", 1100, 600), word("Play", 1850, 1200)]
    assert len(in_regions(find_matches(lines, ["play"]), [Target("play")], FRAME)) == 2


def test_region_only_applies_to_its_target():
    lines = [word("Play", 1100, 600), word("Ok", 1100, 600)]
    targets = [Target("play", region=Region(60, 75, 40, 25)), Target("ok")]
    kept = in_regions(find_matches(lines, ["play", "ok"]), targets, FRAME)
    assert [m.target for m in kept] == ["ok"]
