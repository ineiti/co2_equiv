import logging
import os
import re
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.history import append_history, load_history
from app.llm_client import EstimateError, get_estimate
from app.system_prompt import load_system_prompt

app = FastAPI()
logger = logging.getLogger(__name__)

LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1/chat/completions")
SYSTEM_PROMPT = load_system_prompt(os.environ.get("SYSTEM_PROMPT_PATH"))
HISTORY_PATH = os.environ.get("HISTORY_PATH", "/data/fastapi/history.json")

# Matches frontend/co2.js's parseCo2: only a recognizable "<number>kg" co2
# value is worth remembering in history.
_CO2_PATTERN = re.compile(r"^-?\d+(\.\d+)?kg$")


class EstimateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    save: bool = True


@app.post("/api/estimate")
async def estimate(request: EstimateRequest):
    async with httpx.AsyncClient() as client:
        try:
            result = await get_estimate(request.text, LLM_URL, SYSTEM_PROMPT, client)
        except EstimateError:
            raise HTTPException(status_code=502, detail="estimate unavailable")

    if request.save and "calc" in result and _CO2_PATTERN.match(result["co2"]):
        entry = {
            "text": request.text,
            "calc": result["calc"],
            "co2": result["co2"],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            append_history(HISTORY_PATH, entry)
        except OSError:
            logger.exception("failed to write history entry")

    return result


@app.get("/api/history")
async def history():
    return load_history(HISTORY_PATH)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
