from pathlib import Path

import pytest

from app.system_prompt import load_system_prompt


def test_loads_repo_root_system_prompt():
    content = load_system_prompt()
    assert "carbon footprint estimator" in content
    assert content == content.strip()


def test_raises_if_missing(tmp_path):
    missing = tmp_path / "does-not-exist.md"
    with pytest.raises(FileNotFoundError):
        load_system_prompt(str(missing))


def test_loads_explicit_path(tmp_path):
    custom = tmp_path / "custom.md"
    custom.write_text("hello world  \n\n")
    assert load_system_prompt(str(custom)) == "hello world"
