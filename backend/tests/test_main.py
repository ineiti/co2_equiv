from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.history import load_history
from app.main import _maybe_save_history, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_history_path(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr("app.main.EMPTY_HISTORY_PATH", str(tmp_path / "history_empty.json"))


def test_maybe_save_history_routes_unknown_to_empty_history(tmp_path):
    _maybe_save_history("hello", {"co2": "unknown"})
    assert load_history(str(tmp_path / "history.json")) == []
    [entry] = load_history(str(tmp_path / "history_empty.json"))
    assert entry["text"] == "hello"
    assert entry["co2"] == "unknown"


def test_estimate_stream_emits_reasoning_then_result():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("reasoning", "thinking")
        yield ("result", {"calc": "x", "co2": "4.3kg"})

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream("POST", "/api/estimate/stream", json={"text": "drove 25km"}) as response:
            lines = list(response.iter_lines())

    assert lines == [
        "event: reasoning",
        'data: "thinking"',
        "",
        "event: result",
        'data: {"calc": "x", "co2": "4.3kg"}',
        "",
    ]


def test_estimate_stream_emits_answer_event():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("answer", '{"co2":')
        yield ("answer", ' "unknown"}')
        yield ("result", {"co2": "unknown"})

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream("POST", "/api/estimate/stream", json={"text": "hello"}) as response:
            lines = list(response.iter_lines())

    assert lines == [
        "event: answer",
        'data: "{\\"co2\\":"',
        "",
        "event: answer",
        'data: " \\"unknown\\"}"',
        "",
        "event: result",
        'data: {"co2": "unknown"}',
        "",
    ]


def test_estimate_stream_saves_history_on_result():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("result", {"calc": "x", "co2": "4.3kg"})

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream(
            "POST", "/api/estimate/stream", json={"text": "drove 25km"}
        ) as response:
            list(response.iter_lines())

    [entry] = client.get("/api/history").json()
    assert entry["co2"] == "4.3kg"


def test_estimate_stream_save_false_does_not_record_history():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("result", {"calc": "x", "co2": "4.3kg"})

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream(
            "POST", "/api/estimate/stream", json={"text": "drove 25km", "save": False}
        ) as response:
            list(response.iter_lines())

    assert client.get("/api/history").json() == []


def test_estimate_stream_emits_error_event():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("reasoning", "oops")
        yield ("restart", None)
        yield ("error", "LLM call failed after retry: boom")

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream("POST", "/api/estimate/stream", json={"text": "drove 25km"}) as response:
            lines = list(response.iter_lines())

    assert "event: restart" in lines
    assert "event: error" in lines


def test_estimate_stream_empty_text_returns_422():
    response = client.post("/api/estimate/stream", json={"text": ""})
    assert response.status_code == 422


def test_estimate_stream_missing_text_returns_422():
    response = client.post("/api/estimate/stream", json={})
    assert response.status_code == 422


def test_get_history_returns_empty_list_when_no_history():
    response = client.get("/api/history")
    assert response.status_code == 200
    assert response.json() == []


def test_valid_estimate_is_recorded_in_history():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "4.3kg"})):
        client.post("/api/estimate", json={"text": "drove 25km"})

    response = client.get("/api/history")
    assert response.status_code == 200
    [entry] = response.json()
    assert entry["text"] == "drove 25km"
    assert entry["calc"] == "x"
    assert entry["co2"] == "4.3kg"
    assert "timestamp" in entry


def test_unknown_estimate_is_routed_to_empty_history(tmp_path):
    empty_path = tmp_path / "history_empty.json"

    with patch("app.main.get_estimate", new=AsyncMock(return_value={"co2": "unknown"})):
        client.post("/api/estimate", json={"text": "hello"})

    assert client.get("/api/history").json() == []
    [entry] = load_history(str(empty_path))
    assert entry["text"] == "hello"
    assert entry["co2"] == "unknown"


def test_unparseable_co2_is_routed_to_empty_history(tmp_path):
    empty_path = tmp_path / "history_empty.json"

    with patch(
        "app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "~4kg"})
    ):
        client.post("/api/estimate", json={"text": "drove 25km"})

    assert client.get("/api/history").json() == []
    [entry] = load_history(str(empty_path))
    assert entry["text"] == "drove 25km"
    assert entry["co2"] == "~4kg"


def test_empty_history_not_recorded_when_save_false(tmp_path):
    empty_path = tmp_path / "history_empty.json"

    with patch("app.main.get_estimate", new=AsyncMock(return_value={"co2": "unknown"})):
        client.post("/api/estimate", json={"text": "hello", "save": False})

    assert load_history(str(empty_path)) == []


def test_history_endpoint_returns_only_last_10_entries():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "1kg"})):
        for i in range(15):
            client.post("/api/estimate", json={"text": str(i)})

    response = client.get("/api/history")
    texts = [entry["text"] for entry in response.json()]
    assert texts == [str(i) for i in range(14, 4, -1)]


def test_save_false_does_not_record_history():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "4.3kg"})):
        response = client.post("/api/estimate", json={"text": "drove 25km", "save": False})

    assert response.status_code == 200
    assert response.json() == {"calc": "x", "co2": "4.3kg"}
    assert client.get("/api/history").json() == []


def test_estimate_succeeds_even_if_history_write_fails():
    with (
        patch("app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "4.3kg"})),
        patch("app.main.append_history", side_effect=OSError("boom")),
    ):
        response = client.post("/api/estimate", json={"text": "drove 25km"})
    assert response.status_code == 200
    assert response.json() == {"calc": "x", "co2": "4.3kg"}


def test_valid_estimate():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "4.3kg"})):
        response = client.post("/api/estimate", json={"text": "drove 25km"})
    assert response.status_code == 200
    assert response.json() == {"calc": "x", "co2": "4.3kg"}


def test_unknown_estimate():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"co2": "unknown"})):
        response = client.post("/api/estimate", json={"text": "hello"})
    assert response.status_code == 200
    assert response.json() == {"co2": "unknown"}


def test_llm_failure_returns_502():
    from app.llm_client import EstimateError

    with patch("app.main.get_estimate", new=AsyncMock(side_effect=EstimateError("boom"))):
        response = client.post("/api/estimate", json={"text": "drove 25km"})
    assert response.status_code == 502
    assert response.json() == {"error": "estimate unavailable"}


def test_empty_text_returns_422():
    response = client.post("/api/estimate", json={"text": ""})
    assert response.status_code == 422


def test_missing_text_returns_422():
    response = client.post("/api/estimate", json={})
    assert response.status_code == 422


def test_startup_triggers_llm_cache_warmup():
    with patch("app.main.warmup_cache", new=AsyncMock()) as mock_warmup:
        with TestClient(app):
            pass
    mock_warmup.assert_called_once()
