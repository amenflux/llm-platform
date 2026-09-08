# LLM Platform

A production-style inference service for large language models, built to explore
what it takes to run LLMs reliably: structured logging, Prometheus metrics,
Grafana dashboards, containerised deployment and infrastructure as code.

The emphasis is deliberately on the **platform** around the model rather than the
model itself — latency, throughput, token accounting, failure handling and
observability are the interesting problems in production.

---

## Architecture

```
                    ┌──────────────────────────────┐
   HTTP request ───▶│  FastAPI service             │
                    │  • /generate  (inference)    │
                    │  • /ask       (grounded)     │───▶ Ollama / OpenAI-compatible
                    │  • /ingest    (indexing)     │      model server
                    │  • /health    (probe)        │      (chat + embeddings)
                    │  • /metrics   (Prometheus)   │
                    └──────┬──────────────┬────────┘
                           │              │ scraped every 15s
                           ▼              ▼
              ┌─────────────────┐  ┌──────────────────────────────┐
              │ Qdrant          │  │  Prometheus (time-series DB) │
              │ (vector store)  │  └───────────┬──────────────────┘
              └─────────────────┘              │
                                               ▼
                                  ┌──────────────────────────────┐
                                  │  Grafana dashboards          │
                                  └──────────────────────────────┘
```

Everything runs as containers via Docker Compose. The model server runs
separately so the same image works against a local model or a hosted API.

A small **load generator** container sends a steady trickle of varied requests.
Dashboards built on `rate()` queries show nothing while a service is idle, which
makes a healthy system look broken — a constant low-rate baseline keeps latency,
throughput and error panels meaningful.

---

## Quickstart

Requires Docker and a running [Ollama](https://ollama.com) instance with a model
pulled (`ollama pull llama3.2:3b`).

```bash
docker compose up -d --build
```

| Service    | URL                     | Notes                          |
|------------|-------------------------|--------------------------------|
| API        | http://localhost:8000   | Swagger UI at `/docs`          |
| Prometheus | http://localhost:9090   | Targets under Status → Targets |
| Grafana    | http://localhost:3000   | `admin` / `admin`              |

The load generator starts automatically. Tune or disable it with
`REQUEST_INTERVAL_SECONDS` in `docker-compose.yml`.

Send a request:

```bash
curl -X POST localhost:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Explain Kubernetes in one sentence."}'
```

```json
{
  "response": "Kubernetes is an orchestration system that automates...",
  "request_id": "8f329f39-7686-42f8-bcbc-6b5be5d474fa",
  "model": "llama3.2:3b",
  "usage": { "prompt_tokens": 33, "completion_tokens": 8, "total_tokens": 41 },
  "latency_seconds": 6.324
}
```

---

## Retrieval-augmented generation

A model only knows what it saw during training. RAG is how it answers questions
about documents it has never seen — without fine-tuning and without trying to fit
an entire corpus into the prompt.

The pipeline has two halves that run at different times:

```
INGESTION  (once, ahead of time)      POST /ingest
    document ─▶ chunks ─▶ embeddings ─▶ Qdrant

QUERY      (on every question)        POST /ask
    question ─▶ embedding ─▶ nearest chunks ─▶ prompt ─▶ answer + sources
```

```bash
curl -X POST localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What does llm_requests_in_flight measure?"}'
```

```json
{
  "answer": "It is a saturation signal: the number of model calls...",
  "sources": [
    { "source": "README.md", "score": 0.7412 },
    { "source": "README.md", "score": 0.6108 }
  ],
  "timings": { "retrieval_seconds": 0.081, "generation_seconds": 4.902 }
}
```

### Design decisions

**Chunking is the highest-leverage knob.** Text is split on paragraph boundaries
first and only then packed to `CHUNK_SIZE`, because slicing blindly every N
characters cuts sentences in half. Chunks that are too large retrieve irrelevant
filler that dilutes the prompt; chunks that are too small lose the context that
made the passage meaningful. `CHUNK_OVERLAP` carries the tail of each chunk into
the next so a passage straddling a boundary survives intact in one of the two.

**Cosine distance** compares the *angle* between vectors rather than their
magnitude — which is what "similar meaning" means for embeddings, independent of
passage length.

**The payload travels with the vector.** A vector is not human-readable, so each
point stores its original text and source alongside the embedding. That is what
lets a search return something that can be put into a prompt and cited.

**The grounding instruction is what makes it RAG.** The assembled prompt tells the
model to answer *only* from the retrieved context and to say so plainly when the
answer is not there. Without that line the model quietly falls back on its
training data and the citations become decoration.

**Answers carry their sources.** Returning the matched passages and their
similarity scores makes an answer auditable — the caller can check the claim
against the passage it came from.

**The vector dimension is derived, not hardcoded.** The collection is created
from the width of the first embedding returned, so changing `EMBEDDING_MODEL`
needs no code change.

---

## Observability

Every request emits a structured log line carrying a `request_id`, the model
used, token counts, latency and outcome — enough to trace a single call end to
end:

```
2026-09-04 13:41:07 INFO request_id=8f329f39 model=llama3.2:3b status=success
  prompt_tokens=33 completion_tokens=8 total_tokens=41 latency=6.324s
```

Metrics exposed on `/metrics`:

| Metric                                 | Type      | Purpose                                          |
|----------------------------------------|-----------|--------------------------------------------------|
| `http_requests_total`                  | counter   | Traffic and error rate by endpoint               |
| `http_request_duration_highr_seconds`  | histogram | End-to-end latency percentiles                   |
| `llm_tokens_total{type,model}`         | counter   | Token usage, split prompt/completion             |
| `llm_request_duration_seconds{model}`  | histogram | **Model call only** — isolates model from service |
| `llm_tokens_per_second{model}`         | histogram | Generation throughput distribution               |
| `llm_requests_in_flight`               | gauge     | Saturation — concurrent model calls              |
| `llm_cost_usd_total{model}`            | counter   | Estimated spend from a per-model price table     |
| `llm_errors_total{model,error_type}`   | counter   | Failures labelled by exception class             |
| `rag_embedding_duration_seconds`       | histogram | Stage 1 — turning the question into a vector     |
| `rag_retrieval_duration_seconds`       | histogram | Stage 2 — vector search                          |
| `rag_top_score`                        | histogram | **Retrieval quality** — similarity of best match |
| `rag_chunks_indexed_total`             | counter   | Size of the retrievable corpus                   |

Four of these are worth calling out:

**`llm_request_duration_seconds` times the model call alone**, excluding HTTP and
serialisation overhead. Compared against the end-to-end HTTP histogram it answers
"is the model slow, or is my service slow?" — a question a single latency metric
cannot.

**`llm_requests_in_flight` uses a gauge that increments on entry and decrements on
exit even when the call raises**, so it can't leak upward over time. Sustained
growth means arrivals are outpacing completions — the earliest saturation signal
you get.

**RAG is timed in three separate stages** — embed, search, generate. Retrieval
adds two network round-trips before the model is even called, so a single
end-to-end number cannot say which stage is at fault. Three histograms can.

**`rag_top_score` measures answer quality, not infrastructure health.** It records
how closely the best-matching chunk matched each question. A sustained downward
trend means the corpus no longer covers what people are asking — retrieval drift.
That is invisible in latency, error rate, CPU or any other infrastructure metric,
and it is usually the first thing to go wrong in a RAG system that was working.

The provisioned Grafana dashboard covers the four golden signals (latency,
traffic, errors, saturation) plus LLM-specific token throughput, which is what
actually drives cost and explains latency — output tokens are generated one at a
time, so longer answers are slower.

---

## Configuration

The service is configured through the environment, so one image runs unchanged
locally, in Compose, or in a cluster:

| Variable          | Default                        | Description               |
|-------------------|--------------------------------|---------------------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1`    | Model server endpoint     |
| `DEFAULT_MODEL`   | `llama3.2:3b`                  | Model used when unspecified |
| `QDRANT_URL`      | `http://localhost:6333`        | Vector store endpoint     |
| `EMBEDDING_MODEL` | `nomic-embed-text`             | Model used to embed text  |
| `COLLECTION_NAME` | `documents`                    | Qdrant collection         |
| `CHUNK_SIZE`      | `800`                          | Target chunk length (chars) |
| `CHUNK_OVERLAP`   | `150`                          | Overlap carried between chunks |

---

## Infrastructure as code

`infra/` contains Terraform for provisioning the platform on Oracle Cloud
Infrastructure — compartment, VCN, subnet, internet gateway, route table,
security list, IAM (group, user, least-privilege policy, API key) and the
compute instance, with remote state in object storage.

---

## Tech stack

Python 3.11 · FastAPI · Pydantic · Qdrant · Prometheus · Grafana · Docker · Docker Compose · Terraform

## Roadmap

- [x] Inference API with structured logging
- [x] Prometheus metrics and Grafana dashboards
- [x] LLM-specific telemetry: throughput, concurrency, cost, error taxonomy
- [x] Containerised stack via Docker Compose
- [x] Terraform infrastructure definitions
- [x] Retrieval-augmented generation (chunking, embeddings, vector store)
- [ ] Kubernetes deployment with autoscaling
- [ ] CI/CD pipeline with automated evaluation
- [ ] Latency and cost optimisation (caching, batching, model routing)
