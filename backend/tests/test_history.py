import stat

from app.history import append_history, load_history


def test_load_history_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "history.json"
    assert load_history(str(path)) == []


def test_append_history_creates_file_with_entry(tmp_path):
    path = tmp_path / "history.json"
    entry = {"text": "drove 25km", "calc": "x", "co2": "4.3kg", "timestamp": "2026-10-04T00:00:00"}

    result = append_history(str(path), entry)

    assert result == [entry]
    assert load_history(str(path)) == [entry]


def test_append_history_prepends_newest_first(tmp_path):
    path = tmp_path / "history.json"
    first = {"text": "first", "calc": "a", "co2": "1kg", "timestamp": "t1"}
    second = {"text": "second", "calc": "b", "co2": "2kg", "timestamp": "t2"}

    append_history(str(path), first)
    result = append_history(str(path), second)

    assert result == [second, first]
    assert load_history(str(path)) == [second, first]


def test_append_history_keeps_all_entries(tmp_path):
    path = tmp_path / "history.json"
    for i in range(25):
        entry = {"text": str(i), "calc": "c", "co2": "1kg", "timestamp": str(i)}
        result = append_history(str(path), entry)

    assert len(result) == 25
    assert result[0]["text"] == "24"
    assert result[-1]["text"] == "0"


def test_load_history_corrupt_file_returns_empty_list(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not valid json")

    assert load_history(str(path)) == []


def test_append_history_writes_world_readable_file(tmp_path):
    path = tmp_path / "history.json"
    entry = {"text": "drove 25km", "calc": "x", "co2": "4.3kg", "timestamp": "2026-10-04T00:00:00"}

    append_history(str(path), entry)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o644
