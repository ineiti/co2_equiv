import json

import httpx
import pytest
import respx

from app.llm_client import EstimateError, get_estimate, warmup_cache

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
async def test_strips_think_block_before_json():
    content = '<think>\nsome reasoning here\n</think>\n{"calc": "x", "co2": "4.3kg"}'
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response(content)))
    async with httpx.AsyncClient() as client:
        result = await get_estimate("drove 25km", LLM_URL, "system prompt", client)
    assert result == {"calc": "x", "co2": "4.3kg"}


@pytest.mark.asyncio
@respx.mock
async def test_strips_up_to_last_closing_think_tag_with_no_opening_tag():
    # Some chat templates seed the generation with an opening <think> that
    # never appears in the returned content, so only the closing tag shows up.
    content = 'reasoning continues\n</think>\n{"calc": "x", "co2": "1kg"}'
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response(content)))
    async with httpx.AsyncClient() as client:
        result = await get_estimate("test", LLM_URL, "system prompt", client)
    assert result == {"calc": "x", "co2": "1kg"}


@pytest.mark.asyncio
@respx.mock
async def test_empty_think_block_before_json():
    content = '<think>\n\n</think>{"co2": "unknown"}'
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response(content)))
    async with httpx.AsyncClient() as client:
        result = await get_estimate("hello", LLM_URL, "system prompt", client)
    assert result == {"co2": "unknown"}


@pytest.mark.asyncio
@respx.mock
async def test_unclosed_think_block_retries_then_raises():
    # Truncated output (e.g. hit a token/context limit mid-thought): there is
    # no closing tag, so no JSON can be recovered from the content.
    content = "<think>\nreasoning that never finishes"
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response(content)))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_reasoning_content_field_ignored_when_content_is_clean_json():
    response = {
        "choices": [
            {
                "message": {
                    "content": '{"calc": "x", "co2": "1kg"}',
                    "reasoning_content": "some separate reasoning",
                }
            }
        ]
    }
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=response))
    async with httpx.AsyncClient() as client:
        result = await get_estimate("test", LLM_URL, "system prompt", client)
    assert result == {"calc": "x", "co2": "1kg"}


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


@pytest.mark.asyncio
@respx.mock
async def test_non_string_co2_retries_then_raises():
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response('{"calc": "x", "co2": 4.3}'))
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_extra_fields_retries_then_raises():
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(
            200, json=_openai_response('{"calc": "x", "co2": "1kg", "z": 1}')
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_non_dict_json_retries_then_raises():
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json=_openai_response("[1, 2]")))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_empty_choices_retries_then_raises():
    respx.post(LLM_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_null_content_retries_then_raises():
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)


@pytest.mark.asyncio
@respx.mock
async def test_warmup_cache_sends_system_prompt_with_minimal_generation():
    route = respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response("anything"))
    )
    async with httpx.AsyncClient() as client:
        await warmup_cache(LLM_URL, "system prompt", client)

    assert route.call_count == 1
    sent = json.loads(route.calls[0].request.content)
    assert sent["messages"][0] == {"role": "system", "content": "system prompt"}
    assert sent["max_tokens"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_warmup_cache_retries_until_llm_responds():
    route = respx.post(LLM_URL)
    route.side_effect = [
        httpx.ConnectError("boom"),
        httpx.Response(200, json=_openai_response("anything")),
    ]
    async with httpx.AsyncClient() as client:
        await warmup_cache(LLM_URL, "system prompt", client, retry_delay=0)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_warmup_cache_retries_on_5xx_while_model_is_loading():
    route = respx.post(LLM_URL)
    route.side_effect = [
        httpx.Response(503, json={"error": "loading model"}),
        httpx.Response(200, json=_openai_response("anything")),
    ]
    async with httpx.AsyncClient() as client:
        await warmup_cache(LLM_URL, "system prompt", client, retry_delay=0)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_warmup_cache_gives_up_after_max_retries():
    route = respx.post(LLM_URL).mock(side_effect=httpx.ConnectError("boom"))
    async with httpx.AsyncClient() as client:
        await warmup_cache(LLM_URL, "system prompt", client, retry_delay=0, max_attempts=3)

    assert route.call_count == 3
