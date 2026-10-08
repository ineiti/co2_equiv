import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class EstimateError(Exception):
    pass


def _strip_think_block(content: str) -> str:
    """Drop a leading <think>...</think> block some reasoning models (e.g.
    Qwen3) emit before the JSON answer. Some chat templates seed the
    generation with an opening tag that never appears in the returned
    content, so only the closing tag shows up - take everything after the
    last </think> rather than matching a full opening/closing pair.
    An unclosed <think> (truncated output) has no JSON to recover, so it
    is left as-is and fails JSON parsing as before."""
    before, found, after = content.rpartition("</think>")
    return after if found else content


def _validate_shape(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got: {data!r}")
    if set(data.keys()) == {"co2"} and data["co2"] == "unknown":
        return data
    if set(data.keys()) == {"calc", "co2"} and all(isinstance(v, str) for v in data.values()):
        return data
    raise ValueError(f"unexpected shape: {data!r}")


async def _call_once(
    text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient
) -> dict:
    response = await client.post(
        llm_url,
        json={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        },
        timeout=180.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError(f"expected string content, got: {content!r}")
    data = json.loads(_strip_think_block(content))
    return _validate_shape(data)


async def _stream_once(
    text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient
) -> AsyncIterator[tuple[str, str | dict]]:
    content_parts: list[str] = []
    async with client.stream(
        "POST",
        llm_url,
        json={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "stream": True,
        },
        timeout=180.0,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            delta = chunk["choices"][0]["delta"]
            reasoning_delta = delta.get("reasoning_content")
            if reasoning_delta:
                yield ("reasoning", reasoning_delta)
            content_delta = delta.get("content")
            if content_delta:
                content_parts.append(content_delta)
                yield ("answer", content_delta)

    full_content = "".join(content_parts)
    data = json.loads(_strip_think_block(full_content))
    yield ("result", _validate_shape(data))


async def stream_estimate(
    text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient
) -> AsyncIterator[tuple[str, str | dict | None]]:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async for event in _stream_once(text, llm_url, system_prompt, client):
                yield event
            return
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            last_error = exc
            if attempt == 0:
                yield ("restart", None)
    yield ("error", f"LLM call failed after retry: {last_error}")


async def warmup_cache(
    llm_url: str,
    system_prompt: str,
    client: httpx.AsyncClient,
    retry_delay: float = 5.0,
    max_attempts: int = 12,
) -> None:
    """Prime the llm server's prompt cache with the system prompt so the
    first real request doesn't pay to reprocess it from scratch."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post(
                llm_url,
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "warmup"},
                    ],
                    "max_tokens": 1,
                },
                timeout=600.0,
            )
            response.raise_for_status()
            logger.info("llm cache warmup succeeded on attempt %d", attempt)
            return
        except httpx.HTTPError as exc:
            logger.info("llm cache warmup attempt %d/%d failed: %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)
    logger.warning("llm cache warmup gave up after %d attempts", max_attempts)


async def get_estimate(
    text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient
) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return await _call_once(text, llm_url, system_prompt, client)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            last_error = exc
    raise EstimateError(f"LLM call failed after retry: {last_error}") from last_error
