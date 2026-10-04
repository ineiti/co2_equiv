import httpx
import pytest
import respx

from app.llm_client import EstimateError, get_estimate

LLM_URL = "http://llm:8080/v1/chat/completions"


def _openai_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
@respx.mock
async def test_valid_json_passthrough():
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response('{"calc": "x", "co2": "4.3kg"}'))
    )
    async with httpx.AsyncClient() as client:
        result = await get_estimate("drove 25km", LLM_URL, "system prompt", client)
    assert result == {"calc": "x", "co2": "4.3kg"}


@pytest.mark.asyncio
@respx.mock
async def test_unknown_passthrough():
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response('{"co2": "unknown"}'))
    )
    async with httpx.AsyncClient() as client:
        result = await get_estimate("hello", LLM_URL, "system prompt", client)
    assert result == {"co2": "unknown"}


@pytest.mark.asyncio
@respx.mock
async def test_malformed_then_valid_retries_once():
    route = respx.post(LLM_URL)
    route.side_effect = [
        httpx.Response(200, json=_openai_response("not json")),
        httpx.Response(200, json=_openai_response('{"calc": "x", "co2": "1kg"}')),
    ]
    async with httpx.AsyncClient() as client:
        result = await get_estimate("test", LLM_URL, "system prompt", client)
    assert result == {"calc": "x", "co2": "1kg"}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_malformed_twice_raises():
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response("not json")))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_unreachable_raises():
    respx.post(LLM_URL).mock(side_effect=httpx.ConnectError("boom"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_wrong_shape_retries_then_raises():
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response('{"foo": "bar"}')))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)
