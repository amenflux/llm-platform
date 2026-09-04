"""LLM Platform — an observable inference API.

Exposes a /generate endpoint backed by an OpenAI-compatible model server,
with structured request logging and Prometheus metrics for latency,
throughput, errors and token usage.
"""

import logging
import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from openai import OpenAI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Configuration comes from the environment so the same image runs unchanged
# on a laptop, in Docker Compose, or in Kubernetes.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.2:3b")

app = FastAPI(title="LLM Platform", version="0.1.0")

# Exposes /metrics with request counts, a latency histogram and status codes.
Instrumentator().instrument(app).expose(app)

# Domain metric: no library knows what an LLM token is, so we track it ourselves.
llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens processed by the LLM",
    ["type", "model"],
)

client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


class GenerateRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL


@app.get("/")
def read_root():
    return {"service": "llm-platform", "status": "ok"}


@app.get("/health")
def health():
    """Liveness/readiness probe target for Docker and Kubernetes."""
    return {"status": "healthy"}


@app.post("/generate")
def generate_text(payload: GenerateRequest):
    request_id = str(uuid.uuid4())
    start = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": payload.prompt}],
        )

        answer = response.choices[0].message.content
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        latency = time.perf_counter() - start

        llm_tokens_total.labels(type="prompt", model=payload.model).inc(prompt_tokens)
        llm_tokens_total.labels(type="completion", model=payload.model).inc(completion_tokens)

        logging.info(
            f"request_id={request_id} model={payload.model} status=success "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            f"total_tokens={total_tokens} latency={latency:.3f}s"
        )

        return {
            "response": answer,
            "request_id": request_id,
            "model": payload.model,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "latency_seconds": round(latency, 3),
        }

    except Exception as exc:
        latency = time.perf_counter() - start
        logging.error(
            f"request_id={request_id} model={payload.model} status=error "
            f"latency={latency:.3f}s error={exc}"
        )
        raise HTTPException(status_code=500, detail="LLM request failed")
