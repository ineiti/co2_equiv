# Agent notes for co2_equiv

Follow-ups intentionally deferred during initial implementation
(see docs/superpowers/specs/2026-10-04-co2-equivalent-calculator-design.md
section 10 for the original list):

- No rate limiting or abuse protection on POST /api/estimate. Add
  this before any public deployment.
- The default model (gemma-4-E4B-it Q4_0 GGUF) in .env.example is
  an example only, not a vetted recommendation — benchmark actual
  JSON-following reliability and latency before committing to a
  default. In manual end-to-end testing, a cold request (full
  system prompt, ~2000+ tokens) took ~14s on CPU; a warm/cached
  request took ~2s. Budget for the cold case in any UI timeout.
- llama-server runs CPU-only in the current docker-compose.yaml;
  GPU passthrough is not configured.
- No Playwright/e2e test of the full animated browser flow exists
  yet; frontend/co2.js has unit tests, but index.js's DOM/animation
  glue is only manually verified (see Task 9 and Task 10 of the
  implementation plan). Note for future automated UI tests: jsdom
  (as of 30.1.2) does not execute `<script type="module">` tags —
  any future headless test of index.js needs to set `document`/
  `window` as globals and `import()` the module directly instead.
- English-only prompt and UI; no i18n.
- ghcr.io/ggml-org/llama.cpp:server is referenced by tag (`:server`)
  rather than a pinned digest in docker-compose.yaml — consider
  pinning to a specific digest for reproducible builds.

Additional non-obvious things found while building this (not in the
original spec, worth knowing before touching the related files):

- devbox.json pins `nodejs@latest`, not `nodejs@20` as originally
  planned — nixpkgs flags nodejs-20.x as an insecure/EOL package in
  this environment and `devbox install` refuses it outright.
- devbox's python plugin provisions a project-root `.venv/` (see
  `devbox run -- printenv VENV_DIR`) rather than exposing `pip` on
  PATH directly — nixpkgs' Python is PEP 668 externally-managed, so
  `pip install` outside that venv fails. All devbox scripts that need
  pip/pytest/uvicorn source `$VENV_DIR/bin/activate` first
  (see devbox.json's `backend`/`test` scripts).
- `frontend/nginx.conf`'s `/api/` location uses `resolver 127.0.0.11
valid=10s;` plus a `set $backend_upstream ...; proxy_pass
$backend_upstream$request_uri;` pattern instead of a plain
  `proxy_pass http://backend:8000/api/;`. Two reasons, both bit us
  during implementation:
  1. A literal (non-variable) `proxy_pass` target is resolved at
     nginx config-parse/startup time; if `backend` isn't resolvable
     yet (e.g. running the frontend container standalone, outside
     docker-compose), nginx refuses to start at all.
  2. Once resolution is deferred via a variable, nginx also stops
     doing its usual location-prefix path rewriting — a trailing
     literal path after the variable (e.g. `.../api/`) is used
     verbatim, silently dropping the rest of the original URI
     (`/api/estimate` became `/api/` on the wire). Forwarding
     `$request_uri` explicitly is what makes the full path survive.
- `scripts/install-hooks.sh` resolves the hooks directory via
  `git rev-parse --git-common-dir`, not a hardcoded `.git/hooks`.
  Inside a git worktree, `.git` is a file (gitlink), not a directory,
  and hooks live in the shared common gitdir across all worktrees —
  a hardcoded path silently fails there.
- `backend/app/system_prompt.py`'s default path
  (`Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md"`) only
  resolves to the repo root locally. In the Docker image the file
  tree is flatter, so `backend/Dockerfile` sets
  `ENV SYSTEM_PROMPT_PATH=/app/SYSTEM_PROMPT.md` to override it —
  if the Dockerfile's `WORKDIR`/`COPY` layout ever changes, update
  that `ENV` line too.
- `devbox run front` now runs `frontend/dev-server.mjs` (plain
  Node, no extra deps) instead of `python3 -m http.server`, so it
  serves the static files _and_ proxies `/api/*` to
  `http://localhost:${BACKEND_PORT:-8000}`, matching
  `frontend/nginx.conf`'s production behavior. This means
  "devbox run llm && devbox run backend && devbox run front" (three
  terminals, or backgrounded with `&`) is now enough to exercise the
  full stack at http://localhost:8081 without docker compose.
