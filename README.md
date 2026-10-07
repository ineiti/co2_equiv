# CO2 Equivalent Calculator

This is a very simple service which converts an activity
or an item to equivalent flight, car, and train distance.
The goal is to get some kind of intuition of how much
our different activities influence the climate.
It is of course not accurate at all, because there are
often too many factors which influence the CO2 outputs,
but being able to compare them is still nice.

# UI

There is only a text input where the user can type
anything they want - here some examples:

- eating 150g of beef
- forgot to turn off the office light for 2h
- heat 1l of water instead of 0.5l

Once the user hits RETURN or clicks on ESTIMATE,
the calculator outputs the kg of CO2, and a short,
simple animation of a plane, a car, and a train,
with the estimated distance they could travel.

It also works nicely on a mobile device.

Below the result, the page shows the last 20 estimates (text,
CO2 result, and timestamp), newest first. This list is loaded
once on page load from the backend's history, and updated
locally as new estimates come in.

Each result also shows Share buttons for Mastodon, Threads, and
LinkedIn. The share link is the app's own URL with the original
text in a `?text=` query parameter, so opening it re-runs the
same estimate. For Mastodon and Threads, the pre-filled post
also includes the original text and CO2 result; LinkedIn's share
intent only accepts a URL, so it shows just the link.
Opening a shared link does not get added to the backend's
history — only estimates a visitor types and submits themselves
are recorded. The Mastodon button asks once for your instance
domain (e.g. mastodon.social) and remembers it in the browser's
local storage for next time; shift-click the button to change it.

While the LLM calculates the output, there is a small
animation of the plane, train, and car.
From the returned JSON, the UI shows the "calc"
part above the distances, and then calculates with
mean numbers to show the distances of the "co2"
field.

# Setup

This tool uses three docker containers, configured in
a docker-compose.yaml, plus a watchtower container that
keeps them up to date. Only the first two are built by this
repo's CI/CD and pushed to ghcr.io; the third is pulled as-is
from upstream:

- frontend - holds the html, the CSS and a short javascript
  which takes the html input, and sends it to the backend,
  then interprets the returned value and updates the
  distances shown
- backend - a small FastAPI service which injects SYSTEM_PROMPT.md
  as the system prompt, calls the llm container's OpenAI-compatible
  API, validates the JSON shape it gets back, and returns it to
  the frontend. Every successful estimate is appended to a history
  file (JSON array, newest first, capped at the last 20 entries),
  stored at HISTORY_PATH (default /data/fastapi/history.json,
  mounted from ./data/fastapi). GET /api/history returns that list.
- llm - the official ghcr.io/ggml-org/llama.cpp:server image,
  serving a GGUF model file stored in ./data/llm. The model itself
  is downloaded by scripts/download-model.sh from a URL configured
  via MODEL_URL in .env, for example
  https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_0.gguf

The frontend and backend containers are labelled for
watchtower (ghcr.io/nicholas-fedor/watchtower, an actively
maintained fork of the original, now-archived watchtower
project). It polls ghcr.io every 5 minutes and recreates
either container when CI/CD has pushed a newer `:latest`
image, so a production host stays current without manual
intervention. The llm container is pinned by digest on
purpose and is not watched.

The SYSTEM_PROMPT.md tells the model to return a JSON
{"calc": "calculation", "co2": "x kg"}

# CI/CD

The CI/CD has the following github workflows:

- checks with "prettier" all code, markdown, and other files
- creates the two docker images and stores them in ghcr.io

It also uses a git-hook to check with "prettier" that all
files are correctly formatted.

# Local Development

All direct dependencies are handled with devbox.json, so that
it can be run locally as well as in docker.
Run, in three separate terminals: "devbox run llm", then
"devbox run backend", then "devbox run front". Then open
http://localhost:8081 in a browser to use the full stack locally.
Run "devbox run test" to run all backend and frontend tests.
Run "devbox run install-hooks" once to set up the local
prettier pre-commit check.

"devbox run front" runs frontend/dev-server.mjs, a small Node
static file server that also proxies `/api/*` to the backend
(mirroring what frontend/nginx.conf does in production), so the
three "devbox run" processes together are enough to exercise the
full flow locally without docker. `docker compose up` remains
available to run the stack exactly as it runs in production,
pulling the frontend and backend images from ghcr.io.
