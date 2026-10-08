# Streamed reasoning display

## Goal

While waiting for an estimate, show the model's real reasoning as it is
generated, instead of a static "Thinking..." animation, so the wait feels
transparent and the user is more patient with multi-second cold requests.

## Scope

- New streaming endpoint and frontend consumption for the normal
  form-submit flow.
- The existing `POST /api/estimate` (non-streaming) stays as-is, still
  used by the `?text=` auto-run share-link flow (`runFromQueryParam` in
  `index.js`), which does not get a reasoning panel.
- Only Gemma's `reasoning_content` stream is treated as real reasoning.
  If a model/response has none, the UI falls back to today's generic
  loading animation — this feature is purely additive, never worse than
  today.

## Data flow

llama-server already supports `"stream": true` on
`/v1/chat/completions`, returning Server-Sent Events where each chunk's
`delta` holds either `reasoning_content` or `content` (confirmed by
direct probe against the current Gemma GGUF). `reasoning_content` chunks
arrive first; `content` chunks (the final JSON answer) arrive after
reasoning ends.

```
browser --POST(SSE)--> nginx --proxy(unbuffered)--> FastAPI
  --POST(stream=true)--> llama-server
```

FastAPI re-emits a simplified SSE stream to the browser with three event
types:

- `event: reasoning` — one per reasoning token/chunk, `data` is the raw
  text delta.
- `event: result` — once, after the stream ends and the accumulated
  `content` has been parsed and validated exactly as `_call_once` does
  today. `data` is the same JSON object `/api/estimate` returns.
- `event: error` — once, if the upstream call fails or the accumulated
  content fails JSON/shape validation after both attempts (see Retries).

The browser never sees llama-server's raw chunk format directly — FastAPI
reduces it to these three events so the frontend doesn't depend on
llama-server's wire format.

## Backend changes

### `backend/app/llm_client.py`

Add `stream_estimate(text, llm_url, system_prompt, client) -> AsyncIterator[tuple[str, str | dict]]`:

- POSTs to `llm_url` with `"stream": true`.
- Iterates the response's SSE lines, parses each `data: {...}` JSON
  chunk, and for each one with a non-null `delta.reasoning_content`,
  yields `("reasoning", delta_text)`.
- Accumulates `delta.content` chunks internally (not yielded
  individually — the frontend doesn't need token-by-token granularity
  for the final JSON, only the finished object).
- After the stream ends (`data: [DONE]` or the connection closes),
  applies `_strip_think_block` + `json.loads` + `_validate_shape` to the
  accumulated content, same as `_call_once` today. In practice,
  llama-server's streamed chunks already separate `reasoning_content`
  from `content` (confirmed by direct probe), so the accumulated
  content never contains a `<think>` block and `_strip_think_block` is
  a no-op here — kept for parity with `_call_once` and in case a future
  model streams reasoning inline inside `content` instead.
- On success, yields `("result", parsed_dict)`.
- On any failure (HTTP error, JSON parse error, shape validation error),
  retries the whole call once, exactly like `get_estimate` does today —
  the retry opens a fresh `stream: true` request and streams its own
  `reasoning` chunks the same way the first attempt did (it is not a
  silent/blocking retry). But since reasoning chunks from the failed
  attempt were already yielded to the caller, yields `("restart", None)`
  immediately before re-attempting, so the caller (the endpoint) knows
  to tell the frontend to clear the reasoning panel before the retry's
  own `reasoning` events start appending to it.
- If the retry also fails, yields `("error", str(last_error))` and
  stops.

`get_estimate` (used by the non-streaming endpoint) and `warmup_cache`
are unchanged.

### `backend/app/main.py`

Add `POST /api/estimate/stream`, same `EstimateRequest` body as
`/api/estimate`. Returns a `StreamingResponse` with
`media_type="text/event-stream"`. The handler calls
`stream_estimate`, writing each yielded event as:

```
event: <reasoning|result|restart|error>
data: <text, for reasoning — or JSON, for result/error>

```

(SSE format: blank line terminates each event.) When a `result` event is
produced, the same history-save logic currently inline in `estimate()`
runs (the `_CO2_PATTERN` + `"calc" in result` check, then
`append_history`), reusing the existing helper rather than duplicating
the condition.

No change to `/api/estimate`, `/api/history`, or the lifespan warmup.

## nginx

`frontend/nginx.conf`'s `/api/` location currently has no buffering
directives, so nginx buffers the full proxied response by default —
streaming would be invisible to the browser until the backend finished,
same as today. Add a dedicated location for the new endpoint:

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

Keeping this scoped to the one path (rather than disabling buffering on
all of `/api/`) avoids changing behavior for `/api/estimate` and
`/api/history`.

`frontend/dev-server.mjs`'s `proxyToBackend` currently buffers the
entire backend response in memory (`await backendRes.arrayBuffer()`)
before writing anything to the client — this fully defeats streaming in
local dev (`devbox run front`), not just risks it. Fix: pipe the
response body through as it arrives instead of buffering, e.g.
`backendRes.body.pipeTo(...)` / forwarding the readable stream directly
to `res`, falling back to the current buffer-then-write behavior only
if that turns out to be simpler for non-streaming responses (both must
keep working, since this proxy also serves `/api/estimate` and
`/api/history`).

## Frontend changes

### `frontend/co2.js` (pure, unit-tested)

Add `parseSseChunk(buffer)`: given accumulated raw text from the
response stream, returns `{ events: [{type, data}, ...], remainder }` —
splits on blank-line-terminated SSE events, parses each `event:`/`data:`
pair, leaves any incomplete trailing event in `remainder` for the next
chunk. Pure function, no DOM/fetch — testable the same way
`parseCo2`/`toDistances` are today.

### `frontend/index.js` (manually verified, like today)

- New DOM refs for the reasoning panel (added to `index.html`): a
  collapsible container, a toggle, and a text area that reasoning
  deltas are appended into.
- `runEstimate` (for the normal form-submit path only — not
  `runFromQueryParam`) switches from `fetch` + `response.json()` to
  `fetch` + reading `response.body` via `ReadableStream`, feeding chunks
  through `parseSseChunk`, and handling each event:
  - `reasoning`: show the panel (replacing the generic loading state the
    first time this fires), append the text delta.
  - `restart`: clear the panel's accumulated text and reset to the
    "waiting" state, as if starting over.
  - `result`: same rendering `runEstimate` does today (distances, share
    buttons, history), then auto-collapse the reasoning panel.
  - `error`: same `showState({ showFetchError: true })` as today.
- If no `reasoning` event has arrived ~1s after the request starts, show
  today's existing generic loading animation instead (unchanged
  fallback) — implemented with a `setTimeout` that's cleared the moment
  a `reasoning` event arrives.

### `frontend/index.html` / `index.css`

- Add the reasoning panel markup (hidden by default): header with a
  "✨ Reasoning" label and collapse toggle, a scrollable text area.
- Style: monospace, muted color, auto-scrolls to the latest line as text
  is appended, collapses (height transition) when the `result` event
  renders.

## Error handling

- Network/HTTP failure before any bytes stream back: same as today —
  `showFetchError`.
- Failure after reasoning has streamed (the `restart` case): panel
  clears and restarts; if the retry also fails, falls through to
  `showFetchError` same as today, with the partially-streamed reasoning
  cleared.
- Browser doesn't support `ReadableStream` on `response.body`: not
  handled specially — this is baseline Fetch API support in all target
  browsers for this app; no polyfill needed.

## Testing

- Backend: extend `backend/tests/test_llm_client.py` with tests for
  `stream_estimate` against a mocked SSE response (success, the
  retry/restart path, and final failure). Add a test for the
  `/api/estimate/stream` endpoint's SSE framing and the history-save
  trigger on `result`, in the existing FastAPI test style.
- Frontend: TDD `parseSseChunk` in `co2.test.js` — single event, multiple
  events in one chunk, an event split across two chunks (partial
  buffering), malformed input.
- Manual verification (per AGENTS.md's existing note that `index.js`'s
  DOM/animation glue has no automated UI test): run the full dev stack
  (`devbox run llm && devbox run backend && devbox run front`), submit a
  query, confirm reasoning streams live and the panel auto-collapses on
  result; confirm the `?text=` share-link flow is unaffected; confirm
  the no-reasoning fallback (e.g. temporarily point `LLM_URL` at the
  Apertus benchmark server) shows the generic animation instead.

## Out of scope

- Any change to which model is the default (Gemma 4 E4B stays default
  per `benchmarks/README.md`).
- Showing Apertus's plain-text CoT (from `benchmarks/SYSTEM_PROMPT_apertus_cot.md`)
  in this panel — that prompt variant isn't used in production and
  isn't part of this change.
- Structured extraction / deterministic calculation (the separate open
  question in `benchmarks/README.md` about LLM arithmetic reliability).
