from screen_clicker.focus import matches


def test_empty_patterns_match_anything():
    assert matches("anything.exe", [])
    assert matches(None, [])


def test_glob_is_case_insensitive():
    assert matches("FortniteClient-Win64-Shipping.exe", ["fortnite*"])
    assert matches("notepad.exe", ["NOTEPAD*"])


def test_no_match():
    assert not matches("chrome.exe", ["fortnite*", "notepad*"])
    assert not matches(None, ["notepad*"])
