# Streamed Reasoning Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the LLM's real `reasoning_content` streaming live in the UI while an estimate is in flight, instead of (or before) the current static "Thinking..." animation, so the wait feels transparent.

**Architecture:** A new `POST /api/estimate/stream` SSE endpoint in FastAPI opens a `stream: true` request to llama-server, re-emits `reasoning`/`result`/`restart`/`error` events to the browser, and the frontend consumes them via `fetch` + `ReadableStream` to fill a collapsible reasoning panel, falling back to today's static animation if no reasoning arrives quickly. The existing non-streaming `/api/estimate` is untouched.

**Tech Stack:** FastAPI `StreamingResponse`, httpx `client.stream()` (SSE line iteration), vanilla JS `ReadableStream`/`TextDecoder`, nginx `proxy_buffering off`, Vitest, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-08-streamed-reasoning-display-design.md`

## Global Constraints

- The existing `POST /api/estimate` and `GET /api/history` endpoints, and the `?text=` auto-run share-link flow (`runFromQueryParam` in `index.js`), must keep working exactly as today — no behavior change, no reasoning panel for that flow (per spec Scope).
- Only Gemma's `reasoning_content` is treated as real reasoning; no model-specific logic beyond "show what the server sends" (per spec Scope).
- The existing static loading animation (`#loading`) shows immediately when a request starts and stays visible until either a `reasoning` event arrives (swaps to the live panel) or the result/error renders — so a response with no reasoning at all is indistinguishable from today's behavior, satisfying the spec's fallback requirement without an artificial delay (per spec Scope and Frontend changes).
- `nginx.conf`'s `/api/estimate/stream` location must disable proxy buffering; `/api/estimate` and `/api/history` must keep today's buffered behavior unchanged (per spec nginx section).
- `frontend/dev-server.mjs`'s proxy must stream the backend response through as it arrives for `/api/estimate/stream`, while `/api/estimate` and `/api/history` continue to work (per spec nginx section).
- On a mid-stream failure, the retry must itself stream (not block silently); the frontend must be told to clear the panel via a `restart` event before the retry's own `reasoning` events arrive (per spec Backend changes and Error handling).
- History is saved under the same condition as today: `"calc" in result and _CO2_PATTERN.match(result["co2"])`, applied once when a `result` event is produced (per spec `main.py` section).

## Review Focus

- A `reasoning_content` chunk containing JSON-unsafe characters (quotes, newlines, emoji) must survive the FastAPI → browser SSE hop and the browser's parsing without corrupting the panel text or breaking subsequent events — reasonable expectation: arbitrary model text, not just ASCII words, displays correctly.
- An SSE event split across two `fetch` stream chunks (e.g. a chunk boundary lands in the middle of a `data: ...` line) must not drop or mis-parse data — reasonable expectation: network chunking is a transport detail invisible to the user.
- A completely empty `text` plus `save: false` (today's validated-but-edge-case input) must behave identically to the non-streaming endpoint for the same input — reasonable expectation: the two endpoints agree on request validation.
- If llama-server's streaming connection drops mid-stream with no final `[DONE]` (e.g. the container restarts), the endpoint must still end the SSE response (with an `error` event) rather than hang the request open forever — reasonable expectation: a backend crash shows an error, not an infinite spinner.
- Two reasoning chunks arriving back-to-back with no event boundary between them in one `fetch` read (llama-server may batch multiple SSE lines into one TCP packet) must both be parsed, not just the first — reasonable expectation: no reasoning text is silently lost under load.

---

## File Structure

- `backend/app/llm_client.py` — add `stream_estimate()`; extract nothing here (existing `_strip_think_block`/`_validate_shape` are reused as-is).
- `backend/app/main.py` — add `POST /api/estimate/stream`; extract a `_maybe_save_history(result, text)` helper used by both the existing `/api/estimate` and the new endpoint, so the save condition isn't duplicated.
- `backend/tests/test_llm_client.py` — add tests for `stream_estimate`.
- `backend/tests/test_main.py` — add tests for the new endpoint.
- `frontend/co2.js` — add `parseSseChunk()`.
- `frontend/co2.test.js` — add tests for `parseSseChunk()`.
- `frontend/index.html` — add the reasoning panel markup.
- `frontend/index.css` — add the reasoning panel styles.
- `frontend/index.js` — wire the panel to the new streaming fetch in `runEstimate`.
- `frontend/dev-server.mjs` — fix `proxyToBackend` to stream instead of buffer.
- `frontend/nginx.conf` — add the unbuffered location for `/api/estimate/stream`.

---

## Task 1: `stream_estimate` in the backend LLM client

**Files:**

- Modify: `backend/app/llm_client.py`
- Test: `backend/tests/test_llm_client.py`

**Interfaces:**

- Consumes: `_strip_think_block(content: str) -> str`, `_validate_shape(data: object) -> dict` (both already defined in this file, unchanged).
- Produces: `async def stream_estimate(text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient) -> AsyncIterator[tuple[str, str | dict | None]]`. Yields `("reasoning", delta_text: str)` zero or more times, then exactly one of `("result", parsed: dict)` or `("error", message: str)`. May yield `("restart", None)` once, between a failed first attempt and a retry, before any further `("reasoning", ...)` yields from the retry.

- [ ] **Step 1: Write the failing test for the success path**

Add to `backend/tests/test_llm_client.py`:

```python
def _sse_response(*deltas: dict) -> httpx.Response:
    lines = []
    for delta in deltas:
        lines.append(f"data: {json.dumps({'choices': [{'delta': delta}]})}\n\n")
    lines.append("data: [DONE]\n\n")
    return httpx.Response(200, content="".join(lines).encode())


@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_yields_reasoning_then_result():
    respx.post(LLM_URL).mock(
        return_value=_sse_response(
            {"reasoning_content": "Thinking"},
            {"reasoning_content": " about it"},
            {"content": '{"calc": "x", "co2": "4.3kg"}'},
        )
    )
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("drove 25km", LLM_URL, "system prompt", client)]
    assert events == [
        ("reasoning", "Thinking"),
        ("reasoning", " about it"),
        ("result", {"calc": "x", "co2": "4.3kg"}),
    ]
```

Add `from app.llm_client import stream_estimate` to the imports at the top of the file (alongside the existing `EstimateError, get_estimate, warmup_cache` import), and add `import json` if not already present (it already is, line 1).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_yields_reasoning_then_result -v'`
Expected: FAIL with `ImportError: cannot import name 'stream_estimate'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/llm_client.py`, after `_call_once`:

```python
from collections.abc import AsyncIterator


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
```

Note: `_stream_once` is itself a generator, so a failure partway through (e.g. after some `reasoning` events were already yielded to `stream_estimate`'s caller) is only caught by `stream_estimate`'s `try/except` because Python re-raises the generator's exception at the `async for` consuming it — this is standard generator-exception propagation, no special handling needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_yields_reasoning_then_result -v'`
Expected: PASS

- [ ] **Step 5: Write the failing test for content with no reasoning**

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_with_no_reasoning_content():
    respx.post(LLM_URL).mock(
        return_value=_sse_response({"content": '{"co2": "unknown"}'})
    )
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events == [("result", {"co2": "unknown"})]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_with_no_reasoning_content -v'`
Expected: PASS (no code change needed — `delta.get("reasoning_content")` is falsy/absent, so no `reasoning` event is yielded)

- [ ] **Step 7: Write the failing test for the restart-then-success path**

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_restarts_on_malformed_then_succeeds():
    route = respx.post(LLM_URL)
    route.side_effect = [
        _sse_response({"reasoning_content": "oops"}, {"content": "not json"}),
        _sse_response({"reasoning_content": "retry"}, {"content": '{"co2": "unknown"}'}),
    ]
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events == [
        ("reasoning", "oops"),
        ("restart", None),
        ("reasoning", "retry"),
        ("result", {"co2": "unknown"}),
    ]
    assert route.call_count == 2
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_restarts_on_malformed_then_succeeds -v'`
Expected: PASS

- [ ] **Step 9: Write the failing test for failure on both attempts**

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_fails_after_retry():
    respx.post(LLM_URL).mock(return_value=_sse_response({"content": "not json"}))
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events[-2] == ("restart", None)
    assert events[-1][0] == "error"
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_fails_after_retry -v'`
Expected: PASS

- [ ] **Step 11: Write the failing test for a connection error with no bytes at all**

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_unreachable_retries_then_errors():
    respx.post(LLM_URL).mock(side_effect=httpx.ConnectError("boom"))
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events[-1][0] == "error"
    assert events.count(("restart", None)) == 1
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_unreachable_retries_then_errors -v'`
Expected: PASS

- [ ] **Step 13: Write the failing test for JSON-unsafe characters in reasoning text**

Model reasoning text can contain quotes, newlines, and non-ASCII characters (it's natural-language output, not a controlled format) — this must survive the chunk → `json.dumps` (in Task 2) → wire → `JSON.parse` (in Task 5) round trip intact. At this layer, confirm `stream_estimate` yields the raw delta unmodified, with no escaping/mangling:

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_preserves_special_characters_in_reasoning():
    tricky_text = 'He said "340 km" → 0.15/km\nnewline, emoji 🚗'
    respx.post(LLM_URL).mock(
        return_value=_sse_response(
            {"reasoning_content": tricky_text},
            {"content": '{"co2": "unknown"}'},
        )
    )
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events[0] == ("reasoning", tricky_text)
```

- [ ] **Step 14: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_preserves_special_characters_in_reasoning -v'`
Expected: PASS (no code change needed — the delta string is yielded as-is; this test pins that behavior so a future change can't silently break it)

- [ ] **Step 15: Write the failing test for a dropped connection mid-stream**

Distinct from Step 11's "never connects at all": here, some `reasoning` chunks arrive, then the connection ends abruptly with no `[DONE]` sentinel and no final `content` — e.g. the llama-server container restarts mid-generation. `aiter_lines()` simply ends when the underlying stream closes, so `_stream_once` falls through its `async for` loop with `content_parts` empty, and `"".join([])` is `""`, which fails `json.loads` — this should be caught and retried like any other malformed-content case, not hang or crash:

```python
@pytest.mark.asyncio
@respx.mock
async def test_stream_estimate_connection_drops_mid_stream():
    respx.post(LLM_URL).mock(
        return_value=_sse_response({"reasoning_content": "partial thought, then..."})
        # no [DONE], no content chunk — simulates the connection ending early
    )
    async with httpx.AsyncClient() as client:
        events = [e async for e in stream_estimate("hello", LLM_URL, "system prompt", client)]
    assert events[0] == ("reasoning", "partial thought, then...")
    assert events[-1][0] == "error"
```

Note: `_sse_response`'s helper always appends `"data: [DONE]\n\n"` (see Step 1) — for this test, build the response body directly instead of using the helper, omitting the `[DONE]` line, to accurately simulate a dropped connection:

```python
def _sse_response_no_done(*deltas: dict) -> httpx.Response:
    lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas]
    return httpx.Response(200, content="".join(lines).encode())
```

Add this helper next to `_sse_response` (Step 1) and use it in place of `_sse_response` in this test's `respx.post(...).mock(...)` call.

- [ ] **Step 16: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_llm_client.py::test_stream_estimate_connection_drops_mid_stream -v'`
Expected: PASS

- [ ] **Step 17: Run the full backend test suite**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest -v'`
Expected: all PASS (new tests plus all pre-existing ones)

- [ ] **Step 18: Commit**

```bash
git add backend/app/llm_client.py backend/tests/test_llm_client.py
git commit -m "feat(llm): add stream_estimate for live reasoning output"
```

---

## Task 2: `_maybe_save_history` helper and the `/api/estimate/stream` endpoint

**Files:**

- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main.py`

**Interfaces:**

- Consumes: `stream_estimate` from Task 1 (`backend/app/llm_client.py`), `append_history(path: str, entry: dict, max_entries: int = 20) -> list` (`backend/app/history.py`, unchanged), `_CO2_PATTERN` (already defined in `main.py`, unchanged).
- Produces: `_maybe_save_history(text: str, result: dict) -> None` (module-level function in `main.py`, used by both endpoints). The route `POST /api/estimate/stream` returning `text/event-stream`.

- [ ] **Step 1: Write the failing test for the helper's extraction (regression test on existing behavior)**

Add to `backend/tests/test_main.py`, right after the imports:

```python
from app.main import _maybe_save_history
```

```python
def test_maybe_save_history_skips_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.HISTORY_PATH", str(tmp_path / "history.json"))
    _maybe_save_history("hello", {"co2": "unknown"})
    assert load_history(str(tmp_path / "history.json")) == []
```

Add `from app.history import load_history` to the test file's imports if not already present (check first — it is not currently imported there).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_maybe_save_history_skips_unknown -v'`
Expected: FAIL with `ImportError: cannot import name '_maybe_save_history'`

- [ ] **Step 3: Extract the helper and wire up the streaming endpoint**

In `backend/app/main.py`, replace the body of `estimate()` (currently lines 46-66) and add the new imports/endpoint. Read the current file first to confirm line numbers still match (Task 1 did not touch this file), then apply:

Replace:

```python
from app.llm_client import EstimateError, get_estimate, warmup_cache
```

with:

```python
from app.llm_client import EstimateError, get_estimate, stream_estimate, warmup_cache
```

Add near the top, after the `_CO2_PATTERN` definition:

```python
def _maybe_save_history(text: str, result: dict) -> None:
    if "calc" not in result or not _CO2_PATTERN.match(result["co2"]):
        return
    entry = {
        "text": text,
        "calc": result["calc"],
        "co2": result["co2"],
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        append_history(HISTORY_PATH, entry)
    except OSError:
        logger.exception("failed to write history entry")
```

Replace the body of `estimate()`:

```python
@app.post("/api/estimate")
async def estimate(request: EstimateRequest):
    async with httpx.AsyncClient() as client:
        try:
            result = await get_estimate(request.text, LLM_URL, SYSTEM_PROMPT, client)
        except EstimateError:
            raise HTTPException(status_code=502, detail="estimate unavailable")

    if request.save:
        _maybe_save_history(request.text, result)

    return result
```

Add the new endpoint after `estimate()`, before `@app.get("/api/history")`:

```python
import json as _json
from fastapi.responses import StreamingResponse


@app.post("/api/estimate/stream")
async def estimate_stream(request: EstimateRequest):
    async def event_source():
        async with httpx.AsyncClient() as client:
            async for event_type, data in stream_estimate(
                request.text, LLM_URL, SYSTEM_PROMPT, client
            ):
                if event_type == "reasoning":
                    yield f"event: reasoning\ndata: {_json.dumps(data)}\n\n"
                elif event_type == "restart":
                    yield "event: restart\ndata: null\n\n"
                elif event_type == "result":
                    if request.save:
                        _maybe_save_history(request.text, data)
                    yield f"event: result\ndata: {_json.dumps(data)}\n\n"
                elif event_type == "error":
                    yield f"event: error\ndata: {_json.dumps(data)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

(`_json.dumps` is used for the module-level `json` import name clash avoidance — check the top of `main.py` first: it does not currently import `json` at all, only `re`, so a plain `import json` at the top of the file, alongside the existing `import re`, is cleaner than the aliased inline import above. Use that instead: add `import json` to the existing import block at the top of the file and call it `json.dumps(...)` in the endpoint, not `_json`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_maybe_save_history_skips_unknown -v'`
Expected: PASS

- [ ] **Step 5: Write the failing test for the streaming endpoint's full event sequence**

```python
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_estimate_stream_emits_reasoning_then_result -v'`
Expected: PASS

- [ ] **Step 7: Write the failing test for history being saved from the result event**

```python
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
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_estimate_stream_saves_history_on_result -v'`
Expected: PASS

- [ ] **Step 9: Write the failing test for `save: false` not recording history on the streaming endpoint**

```python
def test_estimate_stream_save_false_does_not_record_history():
    async def fake_stream_estimate(text, llm_url, system_prompt, client):
        yield ("result", {"calc": "x", "co2": "4.3kg"})

    with patch("app.main.stream_estimate", new=fake_stream_estimate):
        with client.stream(
            "POST", "/api/estimate/stream", json={"text": "drove 25km", "save": False}
        ) as response:
            list(response.iter_lines())

    assert client.get("/api/history").json() == []
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_estimate_stream_save_false_does_not_record_history -v'`
Expected: PASS

- [ ] **Step 11: Write the failing test for the error event**

```python
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
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_estimate_stream_emits_error_event -v'`
Expected: PASS

- [ ] **Step 13: Write the failing test for request-validation parity between the two endpoints**

The streaming endpoint reuses the same `EstimateRequest` Pydantic model as `/api/estimate`, so empty text should be rejected identically on both — pin this so the two endpoints can't silently drift apart:

```python
def test_estimate_stream_empty_text_returns_422():
    response = client.post("/api/estimate/stream", json={"text": ""})
    assert response.status_code == 422


def test_estimate_stream_missing_text_returns_422():
    response = client.post("/api/estimate/stream", json={})
    assert response.status_code == 422
```

- [ ] **Step 14: Run test to verify it passes**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest tests/test_main.py::test_estimate_stream_empty_text_returns_422 tests/test_main.py::test_estimate_stream_missing_text_returns_422 -v'`
Expected: PASS (no code change needed — FastAPI validates `EstimateRequest` before the route body runs, same as `/api/estimate`; this test pins that both routes share the behavior rather than one drifting if the model ever changes)

- [ ] **Step 15: Run the full backend test suite**

Run: `cd backend && devbox run -- bash -c '. $VENV_DIR/bin/activate && pytest -v'`
Expected: all PASS, including every pre-existing test in `test_main.py` and `test_llm_client.py` (the helper extraction must not change `/api/estimate`'s behavior)

- [ ] **Step 16: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py
git commit -m "feat(api): add POST /api/estimate/stream SSE endpoint"
```

---

## Task 3: `parseSseChunk` pure function in the frontend

**Files:**

- Modify: `frontend/co2.js`
- Test: `frontend/co2.test.js`

**Interfaces:**

- Produces: `export function parseSseChunk(buffer: string): { events: Array<{ type: string, data: string }>, remainder: string }`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/co2.test.js`:

```javascript
import { parseSseChunk } from './co2.js';

describe('parseSseChunk', () => {
  it('parses a single complete event', () => {
    const result = parseSseChunk('event: reasoning\ndata: hello\n\n');
    expect(result.events).toEqual([{ type: 'reasoning', data: 'hello' }]);
    expect(result.remainder).toBe('');
  });

  it('parses multiple complete events in one buffer', () => {
    const result = parseSseChunk('event: reasoning\ndata: one\n\nevent: reasoning\ndata: two\n\n');
    expect(result.events).toEqual([
      { type: 'reasoning', data: 'one' },
      { type: 'reasoning', data: 'two' },
    ]);
    expect(result.remainder).toBe('');
  });

  it('leaves an incomplete trailing event in remainder', () => {
    const result = parseSseChunk('event: reasoning\ndata: one\n\nevent: reasoning\ndata: tw');
    expect(result.events).toEqual([{ type: 'reasoning', data: 'one' }]);
    expect(result.remainder).toBe('event: reasoning\ndata: tw');
  });

  it('completes an event split across two calls when remainder is prepended', () => {
    const first = parseSseChunk('event: reasoning\ndata: hel');
    expect(first.events).toEqual([]);
    expect(first.remainder).toBe('event: reasoning\ndata: hel');

    const second = parseSseChunk(first.remainder + 'lo\n\n');
    expect(second.events).toEqual([{ type: 'reasoning', data: 'hello' }]);
    expect(second.remainder).toBe('');
  });

  it('ignores a buffer with no complete event', () => {
    const result = parseSseChunk('event: result');
    expect(result.events).toEqual([]);
    expect(result.remainder).toBe('event: result');
  });

  it('returns no events for an empty buffer', () => {
    const result = parseSseChunk('');
    expect(result.events).toEqual([]);
    expect(result.remainder).toBe('');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && devbox run -- npm test`
Expected: FAIL — `parseSseChunk is not a function` (or similar import error)

- [ ] **Step 3: Write the implementation**

Add to `frontend/co2.js`, after `normalizeMastodonInstance`:

```javascript
export function parseSseChunk(buffer) {
  const events = [];
  let remainder = buffer;

  while (true) {
    const boundary = remainder.indexOf('\n\n');
    if (boundary === -1) break;

    const rawEvent = remainder.slice(0, boundary);
    remainder = remainder.slice(boundary + 2);

    let type = null;
    let data = null;
    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event: ')) type = line.slice('event: '.length);
      else if (line.startsWith('data: ')) data = line.slice('data: '.length);
    }
    if (type !== null && data !== null) {
      events.push({ type, data });
    }
  }

  return { events, remainder };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && devbox run -- npm test`
Expected: PASS (all `parseSseChunk` tests, plus every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
git add frontend/co2.js frontend/co2.test.js
git commit -m "feat(frontend): add parseSseChunk for SSE stream parsing"
```

---

## Task 4: Reasoning panel markup and styles

**Files:**

- Modify: `frontend/index.html`
- Modify: `frontend/index.css`

**Interfaces:**

- Produces: new DOM elements with the following IDs, consumed by Task 5: `#reasoning-panel` (container, hidden by default), `#reasoning-toggle` (button, collapses/expands), `#reasoning-text` (element that reasoning text is appended into).

- [ ] **Step 1: Add the markup**

In `frontend/index.html`, insert a new block immediately after the existing `<div id="loading" hidden>...</div>` block (currently lines 21-26), before `<div id="result" hidden>`:

```html
<div id="reasoning-panel" hidden>
  <button type="button" id="reasoning-toggle">✨ Reasoning (live)</button>
  <pre id="reasoning-text"></pre>
</div>
```

- [ ] **Step 2: Add the styles**

In `frontend/index.css`, add after the `@keyframes bounce` block (currently ending at line 64):

```css
#reasoning-panel {
  margin-top: 1rem;
  border: 1px solid rgba(128, 128, 128, 0.3);
  border-radius: 4px;
  overflow: hidden;
  transition:
    max-height 0.3s ease,
    opacity 0.3s ease;
  max-height: 200px;
}

#reasoning-panel.collapsed {
  max-height: 0;
  opacity: 0;
  border-width: 0;
  margin-top: 0;
}

#reasoning-toggle {
  width: 100%;
  text-align: left;
  background: rgba(128, 128, 128, 0.1);
  border: none;
  padding: 0.5rem 0.8rem;
  font-size: 0.85rem;
  cursor: pointer;
  opacity: 0.8;
}

#reasoning-text {
  margin: 0;
  padding: 0.6rem 0.8rem;
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  opacity: 0.75;
  white-space: pre-wrap;
  max-height: 150px;
  overflow-y: auto;
}
```

- [ ] **Step 3: Manually verify the panel renders (no JS wiring yet, so it stays hidden)**

Run: `devbox run front` (in one terminal), open `http://localhost:8081`.
Expected: page loads unchanged from before (the panel has `hidden` set, so it's invisible); no console errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/index.css
git commit -m "feat(frontend): add reasoning panel markup and styles"
```

---

## Task 5: Wire the reasoning panel into `runEstimate`

**Files:**

- Modify: `frontend/index.js`

**Interfaces:**

- Consumes: `parseSseChunk` (Task 3, `frontend/co2.js`), `#reasoning-panel`/`#reasoning-toggle`/`#reasoning-text` (Task 4, `frontend/index.html`).
- Produces: `runEstimate(text, { save, showReasoning = true })` — the spec requires the `?text=` share-link flow (`runFromQueryParam`) to not show the reasoning panel, so `showReasoning` gates it; `runFromQueryParam`'s existing call site is updated to pass `showReasoning: false`.

- [ ] **Step 1: Add the new DOM references**

In `frontend/index.js`, add to the existing block of `document.getElementById` calls (currently lines 13-29), after the `loading` line:

```javascript
const reasoningPanel = document.getElementById('reasoning-panel');
const reasoningToggle = document.getElementById('reasoning-toggle');
const reasoningText = document.getElementById('reasoning-text');
```

Add the import at the top of the file (currently lines 1-8):

```javascript
import {
  parseCo2,
  toDistances,
  formatHistoryTimestamp,
  buildShareUrl,
  buildShareText,
  normalizeMastodonInstance,
  parseSseChunk,
} from './co2.js';
```

- [ ] **Step 2: Add the toggle handler and a reset helper**

Add after the `showState` function (currently ending at line 79):

```javascript
let reasoningCollapsed = false;

function resetReasoningPanel() {
  reasoningText.textContent = '';
  reasoningPanel.hidden = true;
  reasoningPanel.classList.remove('collapsed');
  reasoningCollapsed = false;
}

function appendReasoning(delta) {
  if (reasoningPanel.hidden) {
    reasoningPanel.hidden = false;
  }
  reasoningText.textContent += delta;
  reasoningText.scrollTop = reasoningText.scrollHeight;
}

function collapseReasoningPanel() {
  if (!reasoningPanel.hidden && !reasoningCollapsed) {
    reasoningPanel.classList.add('collapsed');
    reasoningCollapsed = true;
  }
}

reasoningToggle.addEventListener('click', () => {
  reasoningPanel.classList.toggle('collapsed');
  reasoningCollapsed = reasoningPanel.classList.contains('collapsed');
});
```

- [ ] **Step 3: Replace `submitEstimate`/`runEstimate` with the streaming version**

Replace the existing `submitEstimate` and `runEstimate` functions (currently lines 81-127) with:

```javascript
async function consumeEventStream(response, handlers) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, remainder } = parseSseChunk(buffer);
    buffer = remainder;
    for (const event of events) {
      handlers[event.type]?.(JSON.parse(event.data));
    }
  }
}

function renderResult(text, data, save) {
  const kg = parseCo2(data.co2);

  if (kg === null) {
    calcText.textContent = '';
    co2Text.textContent = "Couldn't estimate that — try describing it differently.";
    planeDistance.textContent = '';
    carDistance.textContent = '';
    trainDistance.textContent = '';
    currentShare = null;
    shareButtons.hidden = true;
    showState({ showResult: true });
    return;
  }

  const distances = toDistances(kg);
  calcText.textContent = data.calc ?? '';
  co2Text.textContent = `${kg}kg CO2e`;
  planeDistance.textContent = formatDistance(distances.plane);
  carDistance.textContent = formatDistance(distances.car);
  trainDistance.textContent = formatDistance(distances.train);
  currentShare = { text, co2: data.co2 };
  shareButtons.hidden = false;
  showState({ showResult: true });
  if (save) {
    addToHistory({ text, calc: data.calc, co2: data.co2, timestamp: new Date().toISOString() });
  }
}

async function runEstimate(text, { save, showReasoning = true }) {
  showState({ showLoading: true });
  resetReasoningPanel();

  try {
    const response = await fetch('/api/estimate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, save }),
    });
    if (!response.ok) {
      throw new Error(`request failed: ${response.status}`);
    }

    await consumeEventStream(response, {
      reasoning: (delta) => {
        if (!showReasoning) return;
        loading.hidden = true;
        appendReasoning(delta);
      },
      restart: () => {
        if (!showReasoning) return;
        resetReasoningPanel();
        loading.hidden = false;
      },
      result: (data) => {
        collapseReasoningPanel();
        renderResult(text, data, save);
      },
      error: () => {
        throw new Error('stream reported an error');
      },
    });
  } catch (err) {
    showState({ showFetchError: true });
  }
}
```

Note: `reasoning` events carry a plain string as their JSON payload (e.g. `data: "hello"`), so `JSON.parse(event.data)` yields that string directly — this matches what `main.py`'s `json.dumps(data)` produces for a `str` `data` argument in the `reasoning` branch.

The `error` handler throwing inside the `handlers[event.type]?.(...)` call is caught by the surrounding `try/catch` in `runEstimate`, which is what routes it to `showState({ showFetchError: true })` — confirm this by reading the test in Step 5 of this task.

`showReasoning` defaults to `true` so the normal form-submit path (Step 6 below) needs no change at its call site; only `runFromQueryParam` passes `false`, per the spec's requirement that the share-link flow has no reasoning panel. When `showReasoning` is `false`, the backend still streams `reasoning`/`restart` events exactly as normal (no request-shape difference) — the frontend simply ignores them, so `#loading` stays visible for the whole wait, identical to today's behavior for that flow.

- [ ] **Step 4: Update `runFromQueryParam` to opt out of the reasoning panel**

In `frontend/index.js`, find the existing `runFromQueryParam` function (currently near the end of the file, calling `runEstimate(text, { save: false })`) and change that call to:

```javascript
runEstimate(text, { save: false, showReasoning: false });
```

- [ ] **Step 5: Manually verify end-to-end**

Run: `devbox run llm` (terminal 1), `devbox run backend` (terminal 2), `devbox run front` (terminal 3). Open `http://localhost:8081`, submit "drove 25 km to work".
Expected: the reasoning panel appears and fills with live text within a second or two (cold request), then collapses when the result card renders with distances and share buttons, matching today's final appearance.

- [ ] **Step 6: Manually verify the `?text=` share-link flow is unaffected**

Open `http://localhost:8081/?text=drove%2025km`.
Expected: same behavior as before this change — the input pre-fills, `#loading`'s generic animation shows for the whole wait (no reasoning panel ever appears, per Step 4's `showReasoning: false`), then the result renders.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.js
git commit -m "feat(frontend): stream live reasoning into the UI during an estimate"
```

---

## Task 6: Unbuffered proxying in nginx and the dev server

**Files:**

- Modify: `frontend/nginx.conf`
- Modify: `frontend/dev-server.mjs`

**Interfaces:**

- Consumes: nothing new.
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Add the unbuffered nginx location**

In `frontend/nginx.conf`, add a new `location` block before the existing `location /api/` block (so nginx's longest-prefix-wins behavior picks this one for the streaming path specifically):

```nginx
    location /api/estimate/stream {
        set $backend_upstream http://backend:8000;
        proxy_pass $backend_upstream$request_uri;
        proxy_set_header Host $host;
        proxy_read_timeout 200s;
        proxy_buffering off;
        proxy_cache off;
    }

```

Insert it immediately above the line `location /api/ {`.

- [ ] **Step 2: Fix `proxyToBackend` to stream instead of buffer**

In `frontend/dev-server.mjs`, replace the `proxyToBackend` function (currently lines 28-50):

```javascript
async function proxyToBackend(req, res) {
  const target = `${BACKEND_URL}${req.url}`;
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;

  let backendRes;
  try {
    backendRes = await fetch(target, {
      method: req.method,
      headers: { ...req.headers, host: undefined },
      body,
    });
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'backend unavailable' }));
    return;
  }

  res.writeHead(backendRes.status, {
    'Content-Type': backendRes.headers.get('content-type') ?? 'application/octet-stream',
  });
  for await (const chunk of backendRes.body) {
    res.write(chunk);
  }
  res.end();
}
```

(This removes the `responseBody`/`arrayBuffer()` buffering entirely and streams every response the same way — both `/api/estimate` and `/api/estimate/stream` now write chunks as they arrive. A non-streaming JSON response is also just one "chunk" in practice, so this does not change `/api/estimate`'s or `/api/history`'s observed behavior.)

- [ ] **Step 3: Manually verify streaming still works through the dev proxy**

With all three dev servers running (`devbox run llm`, `devbox run backend`, `devbox run front`), open `http://localhost:8081`, submit a query, and confirm the reasoning panel fills in incrementally (not all at once at the end) — this is the concrete check that `dev-server.mjs` is no longer buffering.

- [ ] **Step 4: Manually verify the non-streaming endpoints still work through the dev proxy**

Submit another query and confirm the final result (distances, share buttons) still renders correctly, and open the "Recent estimates" history section to confirm `GET /api/history` still works.

- [ ] **Step 5: Run the full frontend test suite**

Run: `cd frontend && devbox run -- npm test`
Expected: all PASS (this task touches no tested logic, but confirms nothing broke)

- [ ] **Step 6: Commit**

```bash
git add frontend/nginx.conf frontend/dev-server.mjs
git commit -m "fix(frontend): stream proxy responses instead of buffering"
```

---

## Task 7: Full-stack manual verification and docs

**Files:**

- Modify: `AGENTS.md` (append a note, following its existing "Additional non-obvious things found while building this" convention).

**Interfaces:**

- Consumes: the complete feature from Tasks 1-6.
- Produces: nothing (final task).

- [ ] **Step 1: Run the full backend and frontend test suites together**

Run: `devbox run test`
Expected: all PASS.

- [ ] **Step 2: Manually verify the Docker Compose path (production-equivalent nginx)**

Run: `docker compose up --build` (requires `.env` with a valid `MODEL_URL`, or rely on `.env.example`'s defaults plus an already-downloaded model at `./data/llm/model.gguf`). Open `http://localhost:8081` (or `${FRONTEND_PORT}`).
Expected: reasoning streams live through the real nginx container (not just the dev server), confirming `proxy_buffering off` is effective in the actual production-equivalent proxy path, not only in local dev.

- [ ] **Step 3: Manually verify the no-reasoning fallback**

Temporarily point the backend at a model/server with no `reasoning_content` (e.g. the Apertus benchmark server from `benchmarks/results/`, run via the commands in `benchmarks/README.md`, with `LLM_URL` pointed at it instead of the Gemma server). Submit a query.
Expected: the reasoning panel never appears (no `reasoning` event ever arrives), and the existing generic "Thinking..." animation is what the user sees for the whole wait, then the result renders normally — confirms the feature is purely additive and never regresses the no-reasoning case.

- [ ] **Step 4: Add the AGENTS.md note**

Append to `AGENTS.md`, in the "Additional non-obvious things found while building this" section:

```markdown
- `POST /api/estimate/stream` (added for the live reasoning panel) commits
  to its first attempt once any `reasoning` chunk has reached the
  client — a mid-stream failure triggers a `restart` SSE event and a
  fresh retry, rather than the silent single retry `/api/estimate` does.
  The frontend's `runEstimate` in `index.js` treats `restart` as "clear
  the panel and keep waiting," not as a final error.
- `frontend/dev-server.mjs`'s backend proxy streams response chunks
  through as they arrive (no longer buffers via `arrayBuffer()`) so that
  `devbox run front` exercises the same incremental-rendering behavior
  as the real nginx container's `proxy_buffering off` on
  `/api/estimate/stream`.
```

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "docs: note streaming retry behavior and dev-server proxy fix"
```
