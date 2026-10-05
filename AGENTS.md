# Agent notes for co2_equiv

Follow-ups intentionally deferred during initial implementation
(see docs/superpowers/specs/2026-10-04-co2-equivalent-calculator-design.md
section 10 for the original list):

- No rate limiting or abuse protection on POST /api/estimate. Add
  this before any public deployment. Now more pressing: every
  opened share link (Mastodon/Threads/LinkedIn) triggers a full
  LLM call via the `?text=` auto-run, so sharing is itself a public,
  unauthenticated way to drive load onto the LLM container.
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
- History (`backend/app/history.py`, `GET /api/history`) writes to
  `HISTORY_PATH` (default `/data/fastapi/history.json`, mounted from
  `./data/fastapi` in docker-compose.yaml). `append_history` does an
  atomic write via `tempfile.mkstemp` + `os.replace`, and explicitly
  `os.chmod`s the temp file to 0644 before the rename — `mkstemp`
  defaults to 0600, which would otherwise leave the host-mounted file
  unreadable by a non-root user. A failed history write (`OSError`,
  e.g. read-only mount) is caught in `main.py` and logged, not
  surfaced as a 500 — history is a non-essential enhancement and must
  never break a successful estimate. `devbox run backend` now also
  does `mkdir -p data/fastapi` first and sets
  `HISTORY_PATH=../data/fastapi/history.json`, so local dev writes
  alongside the docker-compose volume path instead of the
  container-only default.
- `main.py` only persists a history entry when `co2` matches the same
  `^-?\d+(\.\d+)?kg$` shape that `frontend/co2.js`'s `parseCo2`
  accepts (see `_CO2_PATTERN` in `main.py`). This is intentionally
  duplicated rather than shared, so that what gets saved to history
  matches what the frontend would actually render as a result on that
  same request. If `parseCo2`'s pattern changes, update `_CO2_PATTERN`
  to match.
- Share buttons (Mastodon/Threads/LinkedIn) and the `?text=` shared
  link both live entirely client-side; the backend only knows about
  them via the `save` field on `POST /api/estimate` (`EstimateRequest.
save`, default `true`). `index.js`'s `runFromQueryParam()` reads
  `?text=` on load, pre-fills the input, strips the query param via
  `history.replaceState` (so a reload or re-sharing the bare URL
  doesn't re-trigger it), and calls the shared `runEstimate(text,
{save: false})` path — the same function the normal form submit
  uses with `{save: true}`. Because `save` is sent by the client, a
  modified/malicious client could still get an estimate recorded or
  skipped either way; nothing server-side enforces the distinction,
  it's purely a UX convention for "did a person actually type this."
  Trim the query-param text (`?.trim()`) — a raw untrimmed value can
  be whitespace-only, which fails the backend's `min_length=1`.
- Mastodon's share intent has no single global URL (unlike Threads'
  `threads.com/intent/post` — note `.com`, not `.net`, per Meta's
  "Threads Web Intents" docs — and LinkedIn's `linkedin.com/sharing/
share-offsite`) because each user is on their own instance. The
  Mastodon button prompts once for the instance domain, normalizes it
  with `normalizeMastodonInstance` in `co2.js` (strips scheme,
  `@user@` prefix, path/trailing slash, whitespace; rejects anything
  without a dot), and caches the normalized result in
  `localStorage['mastodonInstance']`. A cancelled/invalid prompt
  clears the stored key rather than caching a broken value. A
  shift-click on the button always re-prompts (pre-filled with the
  current stored value), so a valid-but-wrong instance (a typo like
  `mastodon.socal`, or moving instances) isn't stuck forever behind
  the "ask once" cache.
- LinkedIn's share-offsite endpoint only accepts a `url` param, not
  pre-filled text — unlike Mastodon/Threads, the LinkedIn button
  can't show the CO2 result in the pre-filled post, only the link.
  This is a platform limitation, not something fixable client-side.
- Not verified in an actual browser (same limitation as the history
  feature): no chromium-cli/Playwright/jsdom available in this
  environment to click the buttons and watch `window.open` fire or
  the Mastodon prompt flow end-to-end. Verified instead by unit tests
  on the pure `co2.js` helpers (`buildShareUrl`, `buildShareText`,
  `normalizeMastodonInstance`) and by reading through the DOM wiring.
