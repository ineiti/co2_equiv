from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "SYSTEM_PROMPT.md"


def load_system_prompt(path: str | None = None) -> str:
    target = Path(path) if path is not None else DEFAULT_PATH
    return target.read_text(encoding="utf-8").strip()
