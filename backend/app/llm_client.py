import json

import httpx


class EstimateError(Exception):
    pass


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
        timeout=30.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError(f"expected string content, got: {content!r}")
    data = json.loads(content)
    return _validate_shape(data)


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
