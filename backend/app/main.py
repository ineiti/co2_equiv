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
