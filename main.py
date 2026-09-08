"""LLM Platform — an observable inference API.

Exposes a /generate endpoint backed by an OpenAI-compatible model server,
with structured request logging and Prometheus metrics covering latency,
throughput, saturation, token usage, estimated cost and errors.
"""

import logging
import os
import time
import uuid

import rag
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from prometheus_client import Counter, Gauge, Histogram
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

# Indicative list prices in USD per 1M tokens as (input, output).
# Self-hosted models have no per-token cost, so the accounting reads zero —
# swapping DEFAULT_MODEL to a hosted model makes the cost metric meaningful
# without any code change.
MODEL_PRICING = {
    "llama3.2:3b": (0.0, 0.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

app = FastAPI(title="LLM Platform", version="0.2.0")

# Exposes /metrics with request counts, a latency histogram and status codes.
Instrumentator().instrument(app).expose(app)

# ---------------------------------------------------------------------------
# LLM-specific metrics. Generic HTTP instrumentation can't see any of these —
# only the application knows what a token, a model or a dollar is.
# ---------------------------------------------------------------------------

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens processed by the LLM",
    ["type", "model"],
)

# Times the model call alone, excluding HTTP and serialisation overhead, so a
# slow model is distinguishable from a slow service.
llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "Duration of the model call itself",
    ["model"],
    buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34),
)

# Output tokens per second — the standard measure of generation throughput.
llm_tokens_per_second = Histogram(
    "llm_tokens_per_second",
    "Output token generation rate per request",
    ["model"],
    buckets=(1, 2, 5, 10, 20, 40, 80, 160),
)

# Saturation signal: how many model calls are in progress right now.
llm_requests_in_flight = Gauge(
    "llm_requests_in_flight",
    "Model requests currently being processed",
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Estimated cumulative spend in USD",
    ["model"],
)

llm_errors_total = Counter(
    "llm_errors_total",
    "Failed model calls by error type",
    ["model", "error_type"],
)

# ---------------------------------------------------------------------------
# RAG metrics. Retrieval adds two network hops before the model is even called,
# so each stage is timed separately — otherwise a slow answer is unattributable.
# ---------------------------------------------------------------------------

rag_embedding_duration_seconds = Histogram(
    "rag_embedding_duration_seconds",
    "Time to turn the question into a vector",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)

rag_retrieval_duration_seconds = Histogram(
    "rag_retrieval_duration_seconds",
    "Time to search the vector store for nearest chunks",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)

# Retrieval quality: if top scores trend down, the corpus no longer covers what
# users are asking — a drift signal you cannot see from latency alone.
rag_top_score = Histogram(
    "rag_top_score",
    "Similarity score of the best-matching chunk",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

rag_chunks_indexed_total = Counter(
    "rag_chunks_indexed_total",
    "Chunks written to the vector store",
)

# Questions the corpus could not answer. A rising rate is the clearest signal
# that the indexed documents no longer match what people are asking.
rag_low_confidence_total = Counter(
    "rag_low_confidence_total",
    "Questions refused because no chunk cleared the similarity threshold",
)

client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost of one call from the price table. Unknown models are treated as free."""
    input_price, output_price = MODEL_PRICING.get(model, (0.0, 0.0))
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


class GenerateRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL


class Document(BaseModel):
    source: str
    text: str


class IngestRequest(BaseModel):
    documents: list[Document]


class AskRequest(BaseModel):
    question: str
    model: str = DEFAULT_MODEL
    top_k: int = 4


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
    model = payload.model

    try:
        # The gauge increments on entry and decrements on exit, even if the
        # call raises — so it can never leak and drift upward over time.
        with llm_requests_in_flight.track_inprogress():
            model_start = time.perf_counter()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": payload.prompt}],
            )
            model_duration = time.perf_counter() - model_start

        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        answer = response.choices[0].message.content

        tokens_per_second = completion_tokens / model_duration if model_duration > 0 else 0
        cost_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)

        llm_tokens_total.labels(type="prompt", model=model).inc(prompt_tokens)
        llm_tokens_total.labels(type="completion", model=model).inc(completion_tokens)
        llm_request_duration_seconds.labels(model=model).observe(model_duration)
        llm_tokens_per_second.labels(model=model).observe(tokens_per_second)
        llm_cost_usd_total.labels(model=model).inc(cost_usd)

        logging.info(
            f"request_id={request_id} model={model} status=success "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            f"total_tokens={total_tokens} model_latency={model_duration:.3f}s "
            f"tokens_per_second={tokens_per_second:.1f} cost_usd={cost_usd:.6f}"
        )

        return {
            "response": answer,
            "request_id": request_id,
            "model": model,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "latency_seconds": round(model_duration, 3),
            "tokens_per_second": round(tokens_per_second, 1),
            "estimated_cost_usd": round(cost_usd, 6),
        }

    except Exception as exc:
        # Label by exception class so the dashboard distinguishes a timeout
        # from a bad model name from a connection failure.
        error_type = type(exc).__name__
        llm_errors_total.labels(model=model, error_type=error_type).inc()
        logging.error(
            f"request_id={request_id} model={model} status=error "
            f"error_type={error_type} error={exc}"
        )
        raise HTTPException(status_code=500, detail="LLM request failed")


@app.post("/ingest")
def ingest_documents(payload: IngestRequest):
    """Chunk, embed and store documents so they can be retrieved later."""
    started = time.perf_counter()
    try:
        result = rag.index_documents([d.model_dump() for d in payload.documents])
        rag_chunks_indexed_total.inc(result.get("chunks_indexed", 0))
        elapsed = time.perf_counter() - started
        logging.info(
            f"status=success operation=ingest documents={len(payload.documents)} "
            f"chunks={result.get('chunks_indexed')} duration={elapsed:.3f}s"
        )
        return result
    except Exception as exc:
        logging.error(f"status=error operation=ingest error_type={type(exc).__name__} error={exc}")
        raise HTTPException(status_code=500, detail="ingestion failed")


@app.post("/ask")
def ask(payload: AskRequest):
    """Answer a question grounded in the indexed documents.

    Three timed stages: embed the question, search the vector store, then
    generate. Timing them separately is what makes a slow answer diagnosable.
    """
    request_id = str(uuid.uuid4())
    model = payload.model

    try:
        # Stage 1 + 2 — embed the question and find the nearest chunks.
        retrieval_start = time.perf_counter()
        embed_start = time.perf_counter()
        query_vector = rag.embed_texts([payload.question])[0]
        rag_embedding_duration_seconds.observe(time.perf_counter() - embed_start)

        search_start = time.perf_counter()
        hits = rag.qdrant.query_points(
            collection_name=rag.COLLECTION_NAME,
            query=query_vector,
            limit=payload.top_k,
            with_payload=True,
        ).points
        rag_retrieval_duration_seconds.observe(time.perf_counter() - search_start)

        chunks = [
            {
                "text": h.payload.get("text", ""),
                "source": h.payload.get("source", "unknown"),
                "score": round(h.score, 4),
            }
            for h in hits
        ]
        retrieval_duration = time.perf_counter() - retrieval_start
        if chunks:
            rag_top_score.observe(chunks[0]["score"])

        # Refuse before spending a model call. Retrieval already answered the
        # question "is this in the corpus at all?" — generating anyway wastes
        # tokens and lets the model improvise from weakly-related text.
        if not chunks or chunks[0]["score"] < rag.MIN_SCORE:
            rag_low_confidence_total.inc()
            top = chunks[0]["score"] if chunks else 0.0
            logging.info(
                f"request_id={request_id} model={model} status=refused operation=ask "
                f"top_score={top} threshold={rag.MIN_SCORE} "
                f"retrieval_latency={retrieval_duration:.3f}s"
            )
            return {
                "answer": "The indexed documents do not contain an answer to that question.",
                "request_id": request_id,
                "model": model,
                "refused": True,
                "sources": [],
                "timings": {
                    "retrieval_seconds": round(retrieval_duration, 3),
                    "generation_seconds": 0.0,
                },
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        # Stage 3 — generate an answer constrained to the retrieved context.
        prompt = rag.build_prompt(payload.question, chunks)

        with llm_requests_in_flight.track_inprogress():
            model_start = time.perf_counter()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            model_duration = time.perf_counter() - model_start

        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        answer = response.choices[0].message.content

        tokens_per_second = completion_tokens / model_duration if model_duration > 0 else 0
        cost_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)

        llm_tokens_total.labels(type="prompt", model=model).inc(prompt_tokens)
        llm_tokens_total.labels(type="completion", model=model).inc(completion_tokens)
        llm_request_duration_seconds.labels(model=model).observe(model_duration)
        llm_tokens_per_second.labels(model=model).observe(tokens_per_second)
        llm_cost_usd_total.labels(model=model).inc(cost_usd)

        logging.info(
            f"request_id={request_id} model={model} status=success operation=ask "
            f"chunks_retrieved={len(chunks)} top_score={chunks[0]['score'] if chunks else 0} "
            f"retrieval_latency={retrieval_duration:.3f}s model_latency={model_duration:.3f}s "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens}"
        )

        return {
            "answer": answer,
            "request_id": request_id,
            "model": model,
            # Returning the sources is what makes a RAG answer auditable —
            # the caller can verify the claim against the cited passage.
            "sources": [{"source": c["source"], "score": c["score"]} for c in chunks],
            "timings": {
                "retrieval_seconds": round(retrieval_duration, 3),
                "generation_seconds": round(model_duration, 3),
            },
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

    except Exception as exc:
        error_type = type(exc).__name__
        llm_errors_total.labels(model=model, error_type=error_type).inc()
        logging.error(
            f"request_id={request_id} model={model} status=error operation=ask "
            f"error_type={error_type} error={exc}"
        )
        raise HTTPException(status_code=500, detail="RAG query failed")
