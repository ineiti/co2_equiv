import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.history import append_history, load_history
from app.llm_client import EstimateError, get_estimate, stream_estimate, warmup_cache
from app.system_prompt import load_system_prompt

logger = logging.getLogger(__name__)

LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1/chat/completions")
SYSTEM_PROMPT = load_system_prompt(os.environ.get("SYSTEM_PROMPT_PATH"))
HISTORY_PATH = os.environ.get("HISTORY_PATH", "/data/fastapi/history.json")
EMPTY_HISTORY_PATH = os.environ.get(
    "EMPTY_HISTORY_PATH", "/data/fastapi/history_empty.json"
)
HISTORY_DISPLAY_LIMIT = 10


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def _warmup():
        async with httpx.AsyncClient() as client:
            await warmup_cache(LLM_URL, SYSTEM_PROMPT, client)

    task = asyncio.create_task(_warmup())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)

# Matches frontend/co2.js's parseCo2: only a recognizable "<number>kg" co2
# value goes to the main history; anything else (e.g. "unknown" or an
# unparseable co2) goes to EMPTY_HISTORY_PATH instead.
_CO2_PATTERN = re.compile(r"^-?\d+(\.\d+)?kg$")


class EstimateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    save: bool = True


def _maybe_save_history(text: str, result: dict) -> None:
    co2 = result.get("co2", "")
    is_valid = "calc" in result and bool(_CO2_PATTERN.match(co2))
    entry = {
        "text": text,
        "calc": result.get("calc", ""),
        "co2": co2,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        append_history(HISTORY_PATH if is_valid else EMPTY_HISTORY_PATH, entry)
    except OSError:
        logger.exception("failed to write history entry")


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


@app.post("/api/estimate/stream")
async def estimate_stream(request: EstimateRequest):
    async def event_source():
        async with httpx.AsyncClient() as client:
            async for event_type, data in stream_estimate(
                request.text, LLM_URL, SYSTEM_PROMPT, client
            ):
                if event_type == "reasoning":
                    yield f"event: reasoning\ndata: {json.dumps(data)}\n\n"
                elif event_type == "answer":
                    yield f"event: answer\ndata: {json.dumps(data)}\n\n"
                elif event_type == "restart":
                    yield "event: restart\ndata: null\n\n"
                elif event_type == "result":
                    if request.save:
                        _maybe_save_history(request.text, data)
                    yield f"event: result\ndata: {json.dumps(data)}\n\n"
                elif event_type == "error":
                    yield f"event: error\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/api/history")
async def history():
    return load_history(HISTORY_PATH)[:HISTORY_DISPLAY_LIMIT]


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
