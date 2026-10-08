from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_history_path(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.HISTORY_PATH", str(tmp_path / "history.json"))


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


def test_unknown_estimate_is_not_recorded_in_history():
    with patch("app.main.get_estimate", new=AsyncMock(return_value={"co2": "unknown"})):
        client.post("/api/estimate", json={"text": "hello"})

    response = client.get("/api/history")
    assert response.json() == []


def test_unparseable_co2_is_not_recorded_in_history():
    with patch(
        "app.main.get_estimate", new=AsyncMock(return_value={"calc": "x", "co2": "~4kg"})
    ):
        client.post("/api/estimate", json={"text": "drove 25km"})

    response = client.get("/api/history")
    assert response.json() == []


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
