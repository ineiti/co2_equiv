# CO2 Equivalent Calculator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CO2 equivalent calculator: a static frontend that
sends free-text activity descriptions to a FastAPI backend, which
prompts an LLM (served by llama.cpp) and returns a validated
`{"calc","co2"}` JSON estimate, which the frontend turns into animated
plane/car/train distance comparisons.

**Architecture:** Three docker-compose services — `frontend` (nginx,
static files + reverse proxy to backend), `backend` (FastAPI wrapper
around the LLM call, built by us), `llm` (official
`ghcr.io/ggml-org/llama.cpp:server` image, pulled not built). Only
`frontend` and `backend` images are built/pushed by CI/CD. Local dev
uses devbox to run `llama-server`, `uvicorn`, and a static file server
as three separate local processes instead of containers.

**Tech Stack:** Python 3.13 + FastAPI + uvicorn + httpx (backend,
pytest + respx for tests); vanilla HTML/CSS/JS (frontend, vitest for
pure-function tests); nginx (frontend container); llama.cpp
`llama-server` (LLM runtime, local dev via devbox and
`ghcr.io/ggml-org/llama.cpp:server` in Docker); devbox (toolchain);
Docker Compose + GitHub Actions (CI/CD); prettier (formatting).

**Spec:** `docs/superpowers/specs/2026-10-04-co2-equivalent-calculator-design.md`

## Global Constraints

- Three containers in `docker-compose.yaml`: `frontend`, `backend`,
  `llm`. Only `frontend` and `backend` are built and pushed to ghcr.io
  by CI/CD; `llm` uses the pinned upstream image
  `ghcr.io/ggml-org/llama.cpp:server` as-is.
- Backend contract: `POST /api/estimate` with body `{"text": "<str>"}`
  returns either `{"calc": "<str>", "co2": "<str>"}`,
  `{"co2": "unknown"}`, or (on failure) HTTP 502 with
  `{"error": "estimate unavailable"}`. Empty/missing `text` → HTTP 422.
- System prompt is loaded verbatim from `SYSTEM_PROMPT.md` (repo root)
  and sent as the system message to the LLM on every request.
- LLM call failure or malformed JSON is retried exactly once before
  giving up.
- Frontend distance factors are fixed constants matching
  `SYSTEM_PROMPT.md`'s own reference values: plane 0.15 kg/km, car
  0.17 kg/km, train 0.035 kg/km.
- All formatting is enforced by `prettier --check` in CI and via a
  local pre-commit git hook.
- devbox is the only sanctioned way to install tooling locally (per
  root `CLAUDE.md`); every new binary/library dependency goes through
  `devbox add` into `devbox.json`.
- TDD: every unit of backend/frontend logic gets a failing test before
  its implementation.

## Review Focus

- **Empty or whitespace-only input**: user hits ESTIMATE with an empty
  box — spec implies the backend rejects it (422), but the frontend
  must also not fire a request and should give a visible hint instead
  of silently doing nothing.
- **LLM returns valid JSON but wrong shape** (e.g. `{"foo": "bar"}`,
  or `co2` present but not a string, or extra unexpected fields): the
  spec's retry-then-502 path must trigger, not a silent pass-through
  of garbage to the browser.
- **`co2` string the frontend can't parse** (e.g. backend's own retry
  exhausted path never reaches the frontend, but a hypothetical
  non-conforming number like `"abc kg"` or missing the `kg` suffix)
  must not crash the distance calculation — `parseCo2` must return
  `null` for anything it doesn't recognize, and the UI must treat
  `null` the same as `"unknown"`.
- **Very large or negative `co2` values** (e.g. `"-6.8kg"` for a
  savings case, or a large multi-ton value like `"5900kg"`): distance
  math must handle negative numbers (shown as savings, not a crash or
  `NaN`) and large numbers without overflow/formatting glitches.
- **Backend unreachable from frontend, or `llm` unreachable from
  backend** (container not yet healthy, network blip): both layers
  must surface a clear, user-visible error rather than hanging
  forever or showing a blank result — frontend needs a fetch
  timeout/error handler, backend needs the 502 path already specced.

---

## File Structure

```
co2_equiv/
├── devbox.json                       # toolchain + scripts (Task 1)
├── .env.example                      # MODEL_URL, LLM ports etc (Task 1)
├── .gitignore                        # data/, .env, node_modules, etc (Task 1)
├── .prettierrc.json / .prettierignore (Task 1)
├── scripts/
│   ├── download-model.sh             # Task 2
│   └── install-hooks.sh              # Task 8
├── backend/
│   ├── Dockerfile                    # Task 6
│   ├── pyproject.toml                # Task 3 (deps: fastapi, uvicorn, httpx)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app, /api/estimate (Task 4)
│   │   ├── llm_client.py             # calls llm service, retry (Task 4)
│   │   └── system_prompt.py          # loads SYSTEM_PROMPT.md (Task 3)
│   └── tests/
│       ├── test_system_prompt.py     # Task 3
│       ├── test_llm_client.py        # Task 4
│       └── test_main.py              # Task 5
├── frontend/
│   ├── Dockerfile                    # Task 7
│   ├── nginx.conf                    # Task 7
│   ├── package.json                 # vitest (Task 3)
│   ├── index.html                    # Task 9
│   ├── index.css                     # Task 9
│   ├── index.js                      # UI glue, imports co2.js (Task 9)
│   ├── co2.js                        # parseCo2, toDistances (Task 3)
│   └── co2.test.js                   # Task 3
├── docker-compose.yaml               # Task 10
├── .github/workflows/
│   ├── prettier.yml                  # Task 8
│   └── docker-build.yml              # Task 10
└── README.md                         # Task 11 (corrections)
```

**Rationale:** backend logic is split into three small files by
responsibility (prompt loading, LLM HTTP client with retry, FastAPI
route/validation) so each is independently testable; frontend keeps
all CO2 math in one pure, DOM-free `co2.js` module so it can be
unit-tested with vitest, separate from `index.js`'s DOM/animation glue
which is not unit-tested per the spec.

---

### Task 1: Project scaffolding — devbox, env, formatting config

**Files:**
- Create: `devbox.json`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `.prettierrc.json`
- Create: `.prettierignore`

**Interfaces:**
- Produces: `devbox.json` with packages `llama-cpp`, `python@3.13`,
  `nodejs@20`, `prettier`, and placeholder scripts `llm`, `backend`,
  `front`, `test`, `fmt`, `fmt:check`, `install-hooks` (bodies filled
  in by later tasks — this task creates the file and the no-op/echo
  stubs so `devbox run <name>` resolves from Task 1 onward; later
  tasks replace each stub body in place).

This task has no test cycle of its own (it is pure scaffolding); its
deliverable is verified by running `devbox install` and `devbox run
fmt:check` successfully in Step 3.

- [ ] **Step 1: Create `devbox.json`**

```json
{
  "packages": ["llama-cpp@latest", "python@3.13", "nodejs@20", "prettier@latest"],
  "shell": {
    "scripts": {
      "llm": "echo 'implemented in Task 2'",
      "backend": "echo 'implemented in Task 4'",
      "front": "echo 'implemented in Task 9'",
      "test": "echo 'implemented in Task 5'",
      "fmt": "prettier --write .",
      "fmt:check": "prettier --check .",
      "install-hooks": "echo 'implemented in Task 8'"
    }
  }
}
```

- [ ] **Step 2: Create `.env.example`, `.gitignore`, prettier config**

`.env.example`:
```
MODEL_URL=https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_0.gguf
LLM_PORT=8080
BACKEND_PORT=8000
FRONTEND_PORT=8081
```

`.gitignore`:
```
data/
.env
node_modules/
__pycache__/
*.pyc
.pytest_cache/
.devbox/
```

`.prettierrc.json`:
```json
{
  "singleQuote": true,
  "semi": true,
  "printWidth": 100
}
```

`.prettierignore`:
```
data/
node_modules/
*.gguf
```

- [ ] **Step 3: Verify devbox resolves and formatting check passes**

Run: `devbox install && devbox run fmt:check`
Expected: devbox installs packages successfully; `fmt:check` passes
(only the files created so far exist, all prettier-formatted).

- [ ] **Step 4: Commit**

```bash
git add devbox.json .env.example .gitignore .prettierrc.json .prettierignore
git commit -m "Add devbox scaffolding, env example, prettier config

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Model download script

**Files:**
- Create: `scripts/download-model.sh`
- Test: manual (shell script; verified by running it twice, see
  Step 2below — shell scripts in this plan are tested by direct
  execution rather than a unit-test framework)

**Interfaces:**
- Produces: `scripts/download-model.sh` — reads `MODEL_URL` from
  `.env` (falling back to `.env.example` if `.env` doesn't exist,
  so CI/fresh clones can still smoke-test it), downloads to
  `./data/llm/model.gguf` if that file does not already exist, is a
  no-op otherwise. Exits non-zero with a clear message if `MODEL_URL`
  is unset after sourcing both files.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
elif [ -f .env.example ]; then
  set -a
  source .env.example
  set +a
fi

if [ -z "${MODEL_URL:-}" ]; then
  echo "Error: MODEL_URL is not set (checked .env and .env.example)." >&2
  exit 1
fi

TARGET_DIR="./data/llm"
TARGET_FILE="$TARGET_DIR/model.gguf"

if [ -f "$TARGET_FILE" ]; then
  echo "Model already present at $TARGET_FILE, skipping download."
  exit 0
fi

mkdir -p "$TARGET_DIR"
echo "Downloading model from $MODEL_URL to $TARGET_FILE ..."
curl -L --fail -o "$TARGET_FILE" "$MODEL_URL"
echo "Done."
```

- [ ] **Step 2: Make executable and verify idempotency logic without a real download**

Run:
```bash
chmod +x scripts/download-model.sh
mkdir -p data/llm && touch data/llm/model.gguf
./scripts/download-model.sh
```
Expected output: `Model already present at ./data/llm/model.gguf, skipping download.`
Then clean up the fake file so a real download can happen later:
```bash
rm data/llm/model.gguf
```

- [ ] **Step 3: Wire into devbox `llm` script (placeholder call only; full llm script completed in Task 9's sibling or now)**

Edit `devbox.json`, replace the `llm` script stub:
```json
"llm": "./scripts/download-model.sh && llama-server -m ./data/llm/model.gguf --port ${LLM_PORT:-8080}"
```

- [ ] **Step 4: Verify script is listed and executable**

Run: `ls -l scripts/download-model.sh`
Expected: `-rwxr-xr-x` permission bits set.

- [ ] **Step 5: Commit**

```bash
git add scripts/download-model.sh devbox.json
git commit -m "Add model download script and wire devbox llm script

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Shared pure-logic modules — system prompt loader (backend) + co2 math (frontend)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/system_prompt.py`
- Test: `backend/tests/test_system_prompt.py`
- Create: `frontend/package.json`
- Create: `frontend/co2.js`
- Test: `frontend/co2.test.js`

**Interfaces:**
- Produces (backend): `load_system_prompt(path: str | None = None) -> str`
  in `backend/app/system_prompt.py` — reads the file at `path` (default:
  repo-root `SYSTEM_PROMPT.md`, resolved relative to this file's
  location, i.e. `Path(__file__).resolve().parent.parent.parent /
  "SYSTEM_PROMPT.md"`), returns its full text stripped of trailing
  whitespace. Raises `FileNotFoundError` if missing.
- Produces (frontend): `parseCo2(co2String: string): number | null` and
  `toDistances(kgCo2: number): {plane: number, car: number, train: number}`
  exported from `frontend/co2.js` (ES module). These are consumed by
  `frontend/index.js` in Task 9.

- [ ] **Step 1: Write failing backend test**

`backend/tests/test_system_prompt.py`:
```python
from pathlib import Path

import pytest

from app.system_prompt import load_system_prompt


def test_loads_repo_root_system_prompt():
    content = load_system_prompt()
    assert "carbon footprint estimator" in content
    assert content == content.strip()


def test_raises_if_missing(tmp_path):
    missing = tmp_path / "does-not-exist.md"
    with pytest.raises(FileNotFoundError):
        load_system_prompt(str(missing))


def test_loads_explicit_path(tmp_path):
    custom = tmp_path / "custom.md"
    custom.write_text("hello world  \n\n")
    assert load_system_prompt(str(custom)) == "hello world"
```

- [ ] **Step 2: Create `backend/pyproject.toml` and package init so pytest can import `app`**

`backend/pyproject.toml`:
```toml
[project]
name = "co2-equiv-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8", "respx>=0.21"]

[tool.pytest.ini_options]
pythonpath = ["."]
```

`backend/app/__init__.py`: empty file.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest tests/test_system_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.system_prompt'`

- [ ] **Step 4: Implement `load_system_prompt`**

`backend/app/system_prompt.py`:
```python
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "SYSTEM_PROMPT.md"


def load_system_prompt(path: str | None = None) -> str:
    target = Path(path) if path is not None else DEFAULT_PATH
    return target.read_text(encoding="utf-8").strip()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_system_prompt.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write failing frontend test**

`frontend/co2.test.js`:
```javascript
import { describe, it, expect } from "vitest";
import { parseCo2, toDistances } from "./co2.js";

describe("parseCo2", () => {
  it("parses a positive kg value", () => {
    expect(parseCo2("4.3kg")).toBe(4.3);
  });

  it("parses a negative kg value", () => {
    expect(parseCo2("-6.8kg")).toBe(-6.8);
  });

  it("returns null for unknown", () => {
    expect(parseCo2("unknown")).toBeNull();
  });

  it("returns null for unparseable strings", () => {
    expect(parseCo2("abc")).toBeNull();
    expect(parseCo2("")).toBeNull();
    expect(parseCo2(undefined)).toBeNull();
  });
});

describe("toDistances", () => {
  it("computes plane/car/train distances from a positive kg value", () => {
    const d = toDistances(4.3);
    expect(d.plane).toBeCloseTo(4.3 / 0.15, 5);
    expect(d.car).toBeCloseTo(4.3 / 0.17, 5);
    expect(d.train).toBeCloseTo(4.3 / 0.035, 5);
  });

  it("computes negative distances for negative kg (savings)", () => {
    const d = toDistances(-6.8);
    expect(d.plane).toBeLessThan(0);
    expect(d.car).toBeLessThan(0);
    expect(d.train).toBeLessThan(0);
  });

  it("returns zero distances for zero kg", () => {
    const d = toDistances(0);
    expect(d.plane).toBe(0);
    expect(d.car).toBe(0);
    expect(d.train).toBe(0);
  });
});
```

- [ ] **Step 7: Create `frontend/package.json` with vitest**

```json
{
  "name": "co2-equiv-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 8: Run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `co2.js` does not exist / export not found.

- [ ] **Step 9: Implement `co2.js`**

```javascript
const FACTORS = {
  plane: 0.15,
  car: 0.17,
  train: 0.035,
};

export function parseCo2(co2String) {
  if (typeof co2String !== "string") return null;
  const match = co2String.match(/^(-?\d+(\.\d+)?)kg$/);
  if (!match) return null;
  return parseFloat(match[1]);
}

export function toDistances(kgCo2) {
  return {
    plane: kgCo2 / FACTORS.plane,
    car: kgCo2 / FACTORS.car,
    train: kgCo2 / FACTORS.train,
  };
}
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (7 tests)

- [ ] **Step 11: Commit**

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/app/system_prompt.py backend/tests/test_system_prompt.py frontend/package.json frontend/package-lock.json frontend/co2.js frontend/co2.test.js
git commit -m "Add system prompt loader and frontend co2 math module

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Backend LLM client with retry

**Files:**
- Create: `backend/app/llm_client.py`
- Test: `backend/tests/test_llm_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks directly (independent HTTP
  client), but conceptually sits between `system_prompt.py`'s output
  and `main.py`'s route (Task 5).
- Produces: `async def get_estimate(text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient | None = None) -> dict`
  in `backend/app/llm_client.py`. Returns a dict shaped either
  `{"calc": str, "co2": str}` or `{"co2": "unknown"}` on success.
  Raises `EstimateError` (defined in the same module) if the LLM is
  unreachable or returns unparseable/invalid JSON after one retry.
  Consumed by `backend/app/main.py` in Task 5.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_llm_client.py`:
```python
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
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response("not json"))
    )
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
    respx.post(LLM_URL).mock(
        return_value=httpx.Response(200, json=_openai_response('{"foo": "bar"}'))
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(EstimateError):
            await get_estimate("test", LLM_URL, "system prompt", client)
```

- [ ] **Step 2: Add test deps and run to verify failure**

Edit `backend/pyproject.toml` dev deps to add `pytest-asyncio>=0.24`:
```toml
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21"]
```
Add to `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`

Run: `cd backend && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm_client'`

- [ ] **Step 3: Implement `llm_client.py`**

```python
import json

import httpx


class EstimateError(Exception):
    pass


def _validate_shape(data: dict) -> dict:
    if set(data.keys()) == {"co2"} and data["co2"] == "unknown":
        return data
    if set(data.keys()) == {"calc", "co2"} and all(
        isinstance(v, str) for v in data.values()
    ):
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
    data = json.loads(content)
    return _validate_shape(data)


async def get_estimate(
    text: str, llm_url: str, system_prompt: str, client: httpx.AsyncClient
) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return await _call_once(text, llm_url, system_prompt, client)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = exc
    raise EstimateError(f"LLM call failed after retry: {last_error}") from last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_llm_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/llm_client.py backend/tests/test_llm_client.py
git commit -m "Add backend LLM client with retry and shape validation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Backend FastAPI route

**Files:**
- Create: `backend/app/main.py`
- Test: `backend/tests/test_main.py`
- Modify: `devbox.json` (`backend` and `test` script stubs)

**Interfaces:**
- Consumes: `load_system_prompt()` from Task 3
  (`backend/app/system_prompt.py`); `get_estimate(text, llm_url,
  system_prompt, client)` and `EstimateError` from Task 4
  (`backend/app/llm_client.py`).
- Produces: FastAPI app object `app` in `backend/app/main.py`, route
  `POST /api/estimate`, request model `{"text": str}`, consumed by
  Task 6 (Dockerfile `CMD`) and Task 10 (docker-compose).

- [ ] **Step 1: Write failing tests**

`backend/tests/test_main.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement `main.py`**

```python
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.llm_client import EstimateError, get_estimate
from app.system_prompt import load_system_prompt

app = FastAPI()

LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1/chat/completions")
SYSTEM_PROMPT = load_system_prompt(os.environ.get("SYSTEM_PROMPT_PATH"))


class EstimateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post("/api/estimate")
async def estimate(request: EstimateRequest):
    async with httpx.AsyncClient() as client:
        try:
            return await get_estimate(request.text, LLM_URL, SYSTEM_PROMPT, client)
        except EstimateError:
            raise HTTPException(status_code=502, detail="estimate unavailable")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (all tests across test_system_prompt.py,
test_llm_client.py, test_main.py — 14 tests total)

- [ ] **Step 5: Wire devbox `backend` and `test` scripts**

Edit `devbox.json`:
```json
"backend": "cd backend && pip install -e '.[dev]' --quiet && LLM_URL=http://localhost:${LLM_PORT:-8080}/v1/chat/completions uvicorn app.main:app --reload --port ${BACKEND_PORT:-8000}",
"test": "cd backend && pip install -e '.[dev]' --quiet && pytest -v && cd ../frontend && npm install --silent && npm test"
```

- [ ] **Step 6: Run the full test script**

Run: `devbox run test`
Expected: all backend pytest tests PASS, all frontend vitest tests
PASS (from Task 3).

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py devbox.json
git commit -m "Add backend FastAPI /api/estimate route

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Backend Dockerfile

**Files:**
- Create: `backend/Dockerfile`

**Interfaces:**
- Consumes: `backend/pyproject.toml`, `backend/app/`,
  `SYSTEM_PROMPT.md` (repo root, copied in).
- Produces: a runnable image exposing port 8000, consumed by Task 10's
  `docker-compose.yaml`.

This task's deliverable is verified by building and running the image
directly (no pytest cycle — it's infra, verified by execution), per
the Task Right-Sizing guidance: fold scaffolding into the task whose
deliverable needs it, verify by running it.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY SYSTEM_PROMPT.md ./SYSTEM_PROMPT.md

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build the image**

Run: `docker build -f backend/Dockerfile -t co2-equiv-backend:test .`
Expected: build succeeds (build context is repo root so
`SYSTEM_PROMPT.md` is reachable).

- [ ] **Step 3: Verify the container starts and responds**

Run:
```bash
docker run --rm -d --name co2-test-backend -p 8000:8000 -e LLM_URL=http://invalid-host:8080/v1/chat/completions co2-equiv-backend:test
sleep 2
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/estimate -H "Content-Type: application/json" -d '{"text":"test"}'
docker stop co2-test-backend
```
Expected: HTTP code `502` printed (LLM host is unreachable by design in
this smoke test, confirming the route is live and the error path
works end-to-end in a real container).

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile
git commit -m "Add backend Dockerfile

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Frontend nginx config and Dockerfile

**Files:**
- Create: `frontend/nginx.conf`
- Create: `frontend/Dockerfile`

**Interfaces:**
- Consumes: static files `frontend/index.html`, `frontend/index.css`,
  `frontend/index.js`, `frontend/co2.js` (index.html/css created in
  Task 9; this task can reference them even though Task 9 runs later,
  since nginx will simply 404 until Task 9 lands — verified instead
  with a temporary placeholder `index.html`, replaced by Task 9's real
  one at the same path, so nothing here needs to change later).
- Produces: image exposing port 80, proxying `/api/` to
  `backend:8000`, consumed by Task 10's `docker-compose.yaml`.

- [ ] **Step 1: Write `nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Write `frontend/Dockerfile`**

```dockerfile
FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/index.css /usr/share/nginx/html/index.css
COPY frontend/index.js /usr/share/nginx/html/index.js
COPY frontend/co2.js /usr/share/nginx/html/co2.js

EXPOSE 80
```

- [ ] **Step 3: Create a temporary minimal `index.html`/`index.css`/`index.js` so the build succeeds now (replaced by Task 9)**

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>CO2 Equivalent Calculator</title>
  </head>
  <body>
    <p>Placeholder — replaced in Task 9.</p>
  </body>
</html>
```
`frontend/index.css`: empty file with a single comment
`/* placeholder — replaced in Task 9 */`.
`frontend/index.js`: empty file with a single comment
`// placeholder — replaced in Task 9`.

- [ ] **Step 4: Build and verify the image serves content and proxies**

Run: `docker build -f frontend/Dockerfile -t co2-equiv-frontend:test .`
Expected: build succeeds.

Run:
```bash
docker run --rm -d --name co2-test-frontend -p 8081:80 co2-equiv-frontend:test
sleep 1
curl -s http://localhost:8081/ | grep -q "Placeholder" && echo "OK: static file served"
docker stop co2-test-frontend
```
Expected: `OK: static file served` printed. (The `/api/` proxy target
`backend` won't resolve outside docker-compose's network, so proxy
behavior is verified later in Task 10, not here.)

- [ ] **Step 5: Commit**

```bash
git add frontend/nginx.conf frontend/Dockerfile frontend/index.html frontend/index.css frontend/index.js
git commit -m "Add frontend nginx config, Dockerfile, and placeholder static files

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Prettier CI workflow and local pre-commit hook

**Files:**
- Create: `.github/workflows/prettier.yml`
- Create: `scripts/install-hooks.sh`
- Modify: `devbox.json` (`install-hooks` script stub)

**Interfaces:**
- Produces: a git pre-commit hook installed at `.git/hooks/pre-commit`
  (not tracked in git itself — the installer script is tracked) that
  runs `prettier --check` on staged files.

- [ ] **Step 1: Write `.github/workflows/prettier.yml`**

```yaml
name: Prettier

on:
  push:
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npx prettier@3 --check .
```

- [ ] **Step 2: Write `scripts/install-hooks.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

cat > .git/hooks/pre-commit <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Running prettier --check on staged files..."
STAGED=$(git diff --cached --name-only --diff-filter=ACM)
if [ -z "$STAGED" ]; then
  exit 0
fi
echo "$STAGED" | xargs npx prettier@3 --check
EOF

chmod +x .git/hooks/pre-commit
echo "Installed pre-commit hook at .git/hooks/pre-commit"
```

- [ ] **Step 3: Wire devbox script**

Edit `devbox.json`:
```json
"install-hooks": "./scripts/install-hooks.sh"
```

- [ ] **Step 4: Make executable and verify**

Run:
```bash
chmod +x scripts/install-hooks.sh
devbox run install-hooks
ls -l .git/hooks/pre-commit
```
Expected: file exists with executable permission bits, printed message
confirms installation.

- [ ] **Step 5: Verify the CI workflow file itself is prettier-clean**

Run: `devbox run fmt:check`
Expected: PASS (all files including the new workflow YAML and shell
script — prettier checks YAML; shell scripts are covered by
`.prettierignore` only if excluded, so confirm `.sh` files aren't
flagged as unparsable: if `fmt:check` fails on `.sh` files, add `*.sh`
to `.prettierignore` since prettier has no shell plugin by default).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/prettier.yml scripts/install-hooks.sh devbox.json .prettierignore
git commit -m "Add prettier CI workflow and local pre-commit hook

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Frontend UI — HTML, CSS, JS glue, animation

**Files:**
- Modify: `frontend/index.html` (replace Task 7 placeholder)
- Modify: `frontend/index.css` (replace Task 7 placeholder)
- Modify: `frontend/index.js` (replace Task 7 placeholder)
- Modify: `devbox.json` (`front` script stub)

**Interfaces:**
- Consumes: `parseCo2`, `toDistances` from `frontend/co2.js` (Task 3).
- Produces: the full user-facing page. No further tasks consume this
  task's internals (it's the top of the frontend stack), so this task
  is verified manually (per spec §5: "DOM/animation rendering itself
  is not unit-tested; verified manually") plus the existing `co2.js`
  automated tests already cover its only testable logic.

- [ ] **Step 1: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>CO2 Equivalent Calculator</title>
    <link rel="stylesheet" href="index.css" />
  </head>
  <body>
    <main>
      <h1>CO2 Equivalent Calculator</h1>
      <p class="hint">
        Describe an activity or item, e.g. "eating 150g of beef" or "forgot
        to turn off the office light for 2h".
      </p>
      <form id="estimate-form">
        <input
          id="text-input"
          type="text"
          placeholder="What did you do?"
          autocomplete="off"
        />
        <button type="submit" id="estimate-button">ESTIMATE</button>
      </form>
      <p id="input-error" class="error" hidden>Please type something first.</p>
      <div id="loading" hidden>
        <span class="icon">✈️</span>
        <span class="icon">🚗</span>
        <span class="icon">🚆</span>
        <p>Thinking...</p>
      </div>
      <div id="result" hidden>
        <p id="calc-text"></p>
        <p id="co2-text"></p>
        <div class="distance-row">
          <span class="icon">✈️</span>
          <span id="plane-distance"></span>
        </div>
        <div class="distance-row">
          <span class="icon">🚗</span>
          <span id="car-distance"></span>
        </div>
        <div class="distance-row">
          <span class="icon">🚆</span>
          <span id="train-distance"></span>
        </div>
      </div>
      <p id="fetch-error" class="error" hidden>
        Could not get an estimate right now. Please try again.
      </p>
    </main>
    <script type="module" src="index.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Write `frontend/index.css`**

```css
:root {
  font-family: system-ui, sans-serif;
  color-scheme: light dark;
}

body {
  margin: 0;
  padding: 1rem;
  display: flex;
  justify-content: center;
}

main {
  max-width: 480px;
  width: 100%;
}

.hint {
  opacity: 0.8;
  font-size: 0.9rem;
}

#estimate-form {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

#text-input {
  flex: 1 1 200px;
  padding: 0.6rem;
  font-size: 1rem;
}

#estimate-button {
  padding: 0.6rem 1rem;
  font-size: 1rem;
  cursor: pointer;
}

.error {
  color: #c0392b;
}

#loading {
  margin-top: 1rem;
  text-align: center;
}

#loading .icon {
  display: inline-block;
  font-size: 1.5rem;
  animation: bounce 1s infinite ease-in-out;
}

@keyframes bounce {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-6px);
  }
}

#result {
  margin-top: 1rem;
}

.distance-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.4rem 0;
}

.distance-row .icon {
  font-size: 1.3rem;
}
```

- [ ] **Step 3: Write `frontend/index.js`**

```javascript
import { parseCo2, toDistances } from "./co2.js";

const form = document.getElementById("estimate-form");
const input = document.getElementById("text-input");
const inputError = document.getElementById("input-error");
const loading = document.getElementById("loading");
const result = document.getElementById("result");
const fetchError = document.getElementById("fetch-error");
const calcText = document.getElementById("calc-text");
const co2Text = document.getElementById("co2-text");
const planeDistance = document.getElementById("plane-distance");
const carDistance = document.getElementById("car-distance");
const trainDistance = document.getElementById("train-distance");

function formatDistance(km) {
  const rounded = Math.round(Math.abs(km));
  const sign = km < 0 ? "saved " : "";
  return `${sign}${rounded} km`;
}

function showState({ showLoading = false, showResult = false, showInputError = false, showFetchError = false }) {
  loading.hidden = !showLoading;
  result.hidden = !showResult;
  inputError.hidden = !showInputError;
  fetchError.hidden = !showFetchError;
}

async function submitEstimate(text) {
  const response = await fetch("/api/estimate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return response.json();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();

  if (!text) {
    showState({ showInputError: true });
    return;
  }

  showState({ showLoading: true });

  try {
    const data = await submitEstimate(text);
    const kg = parseCo2(data.co2);

    if (kg === null) {
      calcText.textContent = "";
      co2Text.textContent = "Couldn't estimate that — try describing it differently.";
      planeDistance.textContent = "";
      carDistance.textContent = "";
      trainDistance.textContent = "";
      showState({ showResult: true });
      return;
    }

    const distances = toDistances(kg);
    calcText.textContent = data.calc ?? "";
    co2Text.textContent = `${kg}kg CO2e`;
    planeDistance.textContent = formatDistance(distances.plane);
    carDistance.textContent = formatDistance(distances.car);
    trainDistance.textContent = formatDistance(distances.train);
    showState({ showResult: true });
  } catch (err) {
    showState({ showFetchError: true });
  }
});
```

- [ ] **Step 4: Wire devbox `front` script**

Edit `devbox.json`:
```json
"front": "cd frontend && python3 -m http.server ${FRONTEND_PORT:-8081}"
```

(Note: in this local, non-proxied dev mode, `/api/estimate` calls from
`index.js` will 404 against the static server directly — local dev of
the full flow against a live backend is documented in README as
requiring either the full `docker-compose up`, or manually running
`devbox run llm` + `devbox run backend` and accessing the frontend via
a browser extension/proxy, or editing `index.js`'s fetch URL
temporarily. This limitation is accepted per spec §7's note that the
exact local proxy approach is an implementation detail; captured here
for the README rather than solved with extra infra, since
docker-compose already provides the real proxied path.)

- [ ] **Step 5: Run all automated tests once more (full regression)**

Run: `devbox run test`
Expected: all backend and frontend tests still PASS (index.js has no
new automated tests — co2.js's existing tests are unaffected).

- [ ] **Step 6: Manual verification**

Run: `devbox run front` then open `http://localhost:8081` in a browser.
Expected: page loads, typing in the box and clicking ESTIMATE shows the
loading animation then a fetch error (since no backend is running in
this manual step) — confirming the UI, animation, and error path all
render correctly. Note in the session that full end-to-end manual
verification (a real estimate) happens in Task 10 once docker-compose
wires all three services together.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/index.css frontend/index.js devbox.json
git commit -m "Build frontend UI with loading animation and distance display

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: docker-compose wiring and Docker build CI workflow

**Files:**
- Create: `docker-compose.yaml`
- Create: `.github/workflows/docker-build.yml`

**Interfaces:**
- Consumes: `backend/Dockerfile` (Task 6), `frontend/Dockerfile`
  (Task 7), `.env.example` keys (Task 1).
- Produces: the full running stack, verified end-to-end manually.

- [ ] **Step 1: Write `docker-compose.yaml`**

```yaml
services:
  llm:
    image: ghcr.io/ggml-org/llama.cpp:server
    command: ["-m", "/models/model.gguf", "--host", "0.0.0.0", "--port", "8080"]
    volumes:
      - ./data/llm:/models
    expose:
      - "8080"

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      - LLM_URL=http://llm:8080/v1/chat/completions
    depends_on:
      - llm
    expose:
      - "8000"

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    ports:
      - "${FRONTEND_PORT:-8081}:80"
    depends_on:
      - backend
```

- [ ] **Step 2: Download a real model and bring up the stack**

Run:
```bash
cp .env.example .env
./scripts/download-model.sh
docker compose up --build -d
sleep 5
docker compose ps
```
Expected: all three services show as running/healthy.

- [ ] **Step 3: End-to-end manual verification**

Run: `curl -s -X POST http://localhost:8081/api/estimate -H "Content-Type: application/json" -d '{"text":"drove 25 km to work"}'`
Expected: a JSON response shaped `{"calc": "...", "co2": "...kg"}`
(exact numbers depend on the model, but the shape must match).

Then open `http://localhost:8081` in a browser, type an activity, click
ESTIMATE, and confirm the loading animation plays and a result with
three distances renders.

Run: `docker compose down`

- [ ] **Step 4: Write `.github/workflows/docker-build.yml`**

```yaml
name: Docker Build

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [frontend, backend]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Log in to ghcr.io
        if: github.event_name == 'push'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.service }}/Dockerfile
          push: ${{ github.event_name == 'push' }}
          tags: ghcr.io/${{ github.repository_owner }}/co2-equiv-${{ matrix.service }}:latest
```

- [ ] **Step 5: Verify formatting**

Run: `devbox run fmt:check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yaml .github/workflows/docker-build.yml
git commit -m "Add docker-compose stack and Docker build CI workflow

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: README corrections and final docs pass

**Files:**
- Modify: `README.md`
- Create: `AGENTS.md`

**Interfaces:**
- None — terminal documentation task.

- [ ] **Step 1: Update `README.md`'s "Setup" section**

Replace the "This tool uses two docker containers" paragraph with:

```markdown
# Setup

This tool uses three docker containers, configured in
a docker-compose.yaml. Only the first two are built by this
repo's CI/CD and pushed to ghcr.io; the third is pulled as-is
from upstream:

- frontend - holds the html, the CSS and a short javascript
which takes the html input, and sends it to the backend,
then interprets the returned value and updates the
distances shown
- backend - a small FastAPI service which injects SYSTEM_PROMPT.md
as the system prompt, calls the llm container's OpenAI-compatible
API, validates the JSON shape it gets back, and returns it to
the frontend
- llm - the official ghcr.io/ggml-org/llama.cpp:server image,
serving a GGUF model file stored in ./data/llm. The model itself
is downloaded by scripts/download-model.sh from a URL configured
via MODEL_URL in .env, for example
https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/blob/main/gemma-4-E4B-it-Q4_0.gguf

The SYSTEM_PROMPT.md tells the model to return a JSON
{"calc": "calculation", "co2": "x kg"}
```

Replace the "Local Development" section with:

```markdown
# Local Development

All direct dependencies are handled with devbox.json, so that
it can be run locally as well as in docker.
Run, in three separate terminals: "devbox run llm", then
"devbox run backend", then "devbox run front".
Run "devbox run test" to run all backend and frontend tests.
Run "devbox run install-hooks" once to set up the local
prettier pre-commit check.
```

- [ ] **Step 2: Write `AGENTS.md`**

```markdown
# Agent notes for co2_equiv

Follow-ups intentionally deferred during initial implementation
(see docs/superpowers/specs/2026-10-04-co2-equivalent-calculator-design.md
section 10 for the original list):

- No rate limiting or abuse protection on POST /api/estimate. Add
  this before any public deployment.
- The default model (gemma-4-E4B-it Q4_0 GGUF) in .env.example is
  an example only, not a vetted recommendation — benchmark actual
  JSON-following reliability and latency before committing to a
  default.
- llama-server runs CPU-only in the current docker-compose.yaml;
  GPU passthrough is not configured.
- No Playwright/e2e test of the full animated browser flow exists
  yet; frontend/co2.js has unit tests, but index.js's DOM/animation
  glue is only manually verified (see Task 9 and Task 10 of the
  implementation plan).
- Local dev's "devbox run front" serves static files directly with
  no /api proxy, so the live full flow (frontend+backend+llm talking
  to each other) can currently only be exercised via
  "docker compose up", not via the three separate "devbox run"
  processes. If pure-local full-flow testing becomes important,
  consider adding a small dev-only proxy (e.g. via Python's
  http.server with a CGI/WSGI shim, or switching index.js to call
  an absolute backend URL in dev mode).
- English-only prompt and UI; no i18n.
- ghcr.io/ggml-org/llama.cpp:server is referenced by tag (`:server`)
  rather than a pinned digest in docker-compose.yaml — consider
  pinning to a specific digest for reproducible builds.
```

- [ ] **Step 3: Verify formatting and full test suite one last time**

Run: `devbox run fmt:check && devbox run test`
Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "Correct README container count and add AGENTS.md follow-ups

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
