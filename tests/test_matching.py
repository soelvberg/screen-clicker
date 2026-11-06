from screen_clicker.matching import Box, Line, Word, find_matches


def line(*texts: str, y: int = 0) -> Line:
    return Line(tuple(Word(t, Box(i * 100, y, 80, 20)) for i, t in enumerate(texts)))


def test_case_insensitive_and_punctuation():
    lines = [line("PLAY!")]
    assert [m.target for m in find_matches(lines, ["play"])] == ["play"]


def test_no_partial_word_match():
    lines = [line("PLAYER"), line("Playlist")]
    assert find_matches(lines, ["play"]) == []


def test_multi_word_sequence_and_box_union():
    lines = [line("Return", "to", "Lobby", y=50)]
    (m,) = find_matches(lines, ["return to lobby"])
    assert m.box == Box(0, 50, 280, 20)
    assert m.box.center == (140, 60)


def test_multi_word_must_be_contiguous():
    lines = [line("Return", "now", "to", "Lobby")]
    assert find_matches(lines, ["return to lobby"]) == []


def test_target_order_is_priority():
    lines = [line("Play"), line("Return", "to", "lobby")]
    assert [m.target for m in find_matches(lines, ["return to lobby", "play"])] == ["return to lobby", "play"]


def test_extra_whitespace_in_target():
    assert len(find_matches([line("Play")], ["  play  "])) == 1


def test_empty_target_ignored():
    assert find_matches([line("Play")], ["", "!!"]) == []
