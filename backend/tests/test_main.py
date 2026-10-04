from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
