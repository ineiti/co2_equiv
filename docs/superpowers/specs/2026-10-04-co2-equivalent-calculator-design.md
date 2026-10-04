# CO2 Equivalent Calculator — Design Spec

Date: 2026-10-04
Status: Approved

## 1. Purpose

A single-page web tool: the user types a free-text description of an
activity or item ("eating 150g of beef"), hits Estimate, and sees an
LLM-generated kg-CO2e estimate plus a short, playful comparison shown as
equivalent travel distances by plane, car, and train. Goal is intuition,
not precision. Works on mobile.

## 2. Architecture — 3 containers, 2 built images

Contrary to the original README wording ("two containers"), the actual
design needs **three** docker-compose services, because the LLM runtime
is best sourced as the official pre-built llama.cpp image rather than
reimplemented. Only two images are *built* by our CI/CD; the third is
pulled as-is. The README will be corrected to say this explicitly.

```
docker-compose.yaml
  frontend   build ./frontend   (nginx; serves static files; proxies /api/*)
  backend    build ./backend    (FastAPI; prompt injection + JSON validation)
  llm        image: ghcr.io/ggml-org/llama.cpp:server   (pulled, not built)
```

Data flow:

```
Browser --POST /api/estimate {text}--> frontend (nginx proxy)
                                          |
                                          v
                                       backend (FastAPI)
                                          |  injects SYSTEM_PROMPT.md,
                                          |  calls llm's OpenAI-compatible
                                          |  /v1/chat/completions
                                          v
                                       llm (llama-server, GGUF model)
                                          |
                                          v
                                       backend validates/repairs JSON
                                          |
                                          v
Browser <--{"calc","co2"} or {"co2":"unknown"}--
                                          |
                                      frontend JS computes plane/car/train
                                      distances from co2 using fixed mean
                                      factors, animates, renders.
```

CI/CD builds and pushes exactly two images to ghcr.io: `frontend` and
`backend`. The `llm` service in docker-compose.yaml references the
upstream image directly (`ghcr.io/ggml-org/llama.cpp:server`, pinned to
a specific tag/digest, not `:latest`).

## 3. Backend (FastAPI)

- Single endpoint: `POST /api/estimate` — body `{"text": "<user input>"}`.
- On request: validate `text` non-empty (max length e.g. 500 chars),
  build a chat-completion request to the `llm` service
  (`http://llm:8080/v1/chat/completions` in compose, configurable via
  `LLM_URL` env var) with `SYSTEM_PROMPT.md`'s contents as the system
  message and `text` as the user message.
- Parse the model's reply as JSON. Expected shapes:
  - `{"calc": str, "co2": str}` — pass through unchanged.
  - `{"co2": "unknown"}` — pass through unchanged.
  - Anything else / invalid JSON / network error: retry the LLM call
    once. If it still fails, return HTTP 502 with
    `{"error": "estimate unavailable"}`.
- No persistence, no auth, no rate limiting (matches the tool's scope;
  noted as a possible follow-up in AGENTS.md).
- Config via `.env` / environment: `LLM_URL`, `LLM_MODEL` (model name
  reported to the OpenAI-compatible endpoint, if required by
  llama-server), `SYSTEM_PROMPT_PATH` (defaults to bundled
  `SYSTEM_PROMPT.md`).

### Testing (TDD, red/green)

pytest + FastAPI `TestClient`, with the `llm` HTTP call mocked
(`httpx` + `respx` or similar):

1. Valid `{"calc","co2"}` JSON from LLM → passed through, 200.
2. `{"co2":"unknown"}` from LLM → passed through, 200.
3. Malformed JSON once, then valid on retry → 200 with retried result.
4. Malformed JSON twice → 502 `{"error": ...}`.
5. Empty/missing `text` in request body → 422 (FastAPI/pydantic default).
6. LLM endpoint unreachable (connection error) → 502.

## 4. LLM service

- `ghcr.io/ggml-org/llama.cpp:server`, pinned tag.
- Model file mounted from `./data/llm/model.gguf` (host volume), loaded
  via llama-server's `-m` flag / compose command args.
- Model URL configured via `.env` (`MODEL_URL`), consumed by
  `scripts/download-model.sh` (see §6), not by the container itself.
- Exposes an OpenAI-compatible `/v1/chat/completions` endpoint on an
  internal port; not published to the host in production compose
  (only `frontend`'s port is published). For local debugging, compose
  can still map it if useful.

## 5. Frontend

- Static `index.html`, `index.css` (or `style.css`), `index.js`, served
  by nginx.
- nginx config: serve static root `/`, reverse-proxy `/api/` to
  `backend:8000`.
- JS logic (`index.js`), kept in small testable pure functions:
  - `submitEstimate(text)` — POSTs to `/api/estimate`, returns parsed
    JSON or throws.
  - `parseCo2(co2String)` — parses `"4.3kg"` → `4.3` (number, kg,
    signed), or `null` for `"unknown"`.
  - `toDistances(kgCo2)` — returns `{plane, car, train}` km, each
    `kgCo2 / factor`, using fixed mean factors:
    - plane: 0.15 kg/km
    - car: 0.17 kg/km
    - train: 0.035 kg/km
    (Matches SYSTEM_PROMPT.md's own reference values for consistency.)
    Negative kgCo2 → negative distances (shown as "saved" distances).
  - UI glue: on submit, show loading animation (plane/train/car), call
    `submitEstimate`, on success render `calc` text + three distance
    rows with simple CSS animation (e.g. icon sliding proportionally to
    distance, capped/scaled for display); on `unknown`, show a friendly
    "couldn't estimate that" message; on error, show a generic error
    message.
  - Enter key and an "ESTIMATE" button both trigger submit.
  - Responsive layout (mobile-first CSS, flexbox/grid, no fixed
    pixel widths for the main input/results).

### Testing (TDD, red/green)

The pure functions (`parseCo2`, `toDistances`) are unit-testable without
a DOM. Use `vitest` (devbox-installable, zero-config, fast) for:

1. `parseCo2("4.3kg")` → `4.3`.
2. `parseCo2("-6.8kg")` → `-6.8`.
3. `parseCo2("unknown")` → `null`.
4. `toDistances(4.3)` → plane/car/train numbers matching the fixed
   factors (within floating-point tolerance).
5. `toDistances(-6.8)` → negative distances.

DOM/animation rendering itself is not unit-tested; verified manually
(and optionally later with a Playwright smoke test, noted as a
follow-up in AGENTS.md, not required now).

## 6. Model download script

`scripts/download-model.sh`:
- Reads `MODEL_URL` from `.env` (source `.env` or use `dotenv`-style
  loading; keep it POSIX-shell simple).
- Target path: `./data/llm/model.gguf`.
- If target already exists, skip (idempotent, safe to call every run).
- Otherwise download via `curl -L -o`, creating `./data/llm/` if
  missing.
- Used both by `devbox run llm` (local dev) and expected to be run
  manually (or via a Make-style helper) before `docker-compose up` in
  the Docker flow, since the model is a host-mounted volume, not baked
  into any image.

## 7. Local development (devbox)

`devbox.json` installs: `llama-cpp` (for `llama-server` binary),
`python3` + `uv` or `pip` (for FastAPI/uvicorn), `nodejs` (for `vitest`
and serving frontend locally), `prettier`.

Scripts (`devbox run <name>`):
- `llm` — `scripts/download-model.sh && llama-server -m ./data/llm/model.gguf --port 8080`
- `backend` — installs backend deps if needed, runs
  `uvicorn app:app --reload --port 8000` with `LLM_URL=http://localhost:8080`
- `front` — serves `frontend/` statically on e.g. port 8081 (simple
  Python `http.server` or a tiny Node static server), proxying is not
  needed locally if the frontend JS is configured (via a small runtime
  config or relative path assumption) to call `http://localhost:8000`
  directly in dev mode. (Exact proxy-vs-direct approach for local dev
  is an implementation detail decided during coding; must not change
  production nginx-proxy behavior.)
- `test` — runs backend pytest + frontend vitest.
- `fmt` / `fmt:check` — runs prettier.

README "Local Development" section is updated to: "devbox run llm",
then "devbox run backend", then "devbox run front" (three steps, not
two, since backend is now its own process distinct from the LLM).

## 8. CI/CD (GitHub Actions)

- `.github/workflows/prettier.yml` — on push/PR: `prettier --check .`
  over the whole repo.
- `.github/workflows/docker-build.yml` — on push to `main` (and
  optionally PRs, build-only without push): builds `frontend` and
  `backend` images, pushes both to `ghcr.io/<owner>/co2-equiv-frontend`
  and `ghcr.io/<owner>/co2-equiv-backend` on push to `main`.
- Local git pre-commit hook (installed via a devbox script, e.g.
  `devbox run install-hooks`, writing `.git/hooks/pre-commit`) runs
  `prettier --check` on staged files before allowing commit.

## 9. README changes required

- Correct "two docker containers" → three containers (frontend,
  backend, llm), two of which (frontend, backend) are built by CI/CD;
  `llm` uses the official `ghcr.io/ggml-org/llama.cpp:server` image.
- Update "Local Development" to the three-step devbox flow.
- Everything else in the current README (UI description, JSON
  contract, CI/CD description of prettier + image builds) remains
  accurate and unchanged.

## 10. Out of scope / follow-ups (→ AGENTS.md)

- Rate limiting / abuse protection on `/api/estimate`.
- Choosing and pinning a specific default model + quantization size
  (README references gemma-4-E4B-it-GGUF Q4_0 as an example only).
- GPU support for llama-server (CPU-only assumed for now).
- Playwright/e2e smoke test of the full animated flow.
- Internationalization (English-only prompt/UI for now).
