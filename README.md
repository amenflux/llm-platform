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
                    │  • /health    (probe)        │───▶ Ollama / OpenAI-compatible
                    │  • /metrics   (Prometheus)   │      model server
                    └───────────┬──────────────────┘
                                │ scraped every 15s
                                ▼
                    ┌──────────────────────────────┐
                    │  Prometheus (time-series DB) │
                    └───────────┬──────────────────┘
                                │
                                ▼
                    ┌──────────────────────────────┐
                    │  Grafana dashboards          │
                    └──────────────────────────────┘
```

Everything runs as containers via Docker Compose. The model server runs
separately so the same image works against a local model or a hosted API.

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

## Observability

Every request emits a structured log line carrying a `request_id`, the model
used, token counts, latency and outcome — enough to trace a single call end to
end:

```
2026-09-04 13:41:07 INFO request_id=8f329f39 model=llama3.2:3b status=success
  prompt_tokens=33 completion_tokens=8 total_tokens=41 latency=6.324s
```

Metrics exposed on `/metrics`:

| Metric                                | Type      | Purpose                              |
|---------------------------------------|-----------|--------------------------------------|
| `http_requests_total`                 | counter   | Traffic and error rate by endpoint   |
| `http_request_duration_highr_seconds` | histogram | Latency percentiles (p50/p95/p99)    |
| `llm_tokens_total{type,model}`        | counter   | Token usage, split prompt/completion |

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

---

## Infrastructure as code

`infra/` contains Terraform for provisioning the platform on Oracle Cloud
Infrastructure — compartment, VCN, subnet, internet gateway, route table,
security list, IAM (group, user, least-privilege policy, API key) and the
compute instance, with remote state in object storage.

---

## Tech stack

Python 3.11 · FastAPI · Pydantic · Prometheus · Grafana · Docker · Docker Compose · Terraform

## Roadmap

- [x] Inference API with structured logging
- [x] Prometheus metrics and Grafana dashboards
- [x] Containerised stack via Docker Compose
- [x] Terraform infrastructure definitions
- [ ] Retrieval-augmented generation (chunking, embeddings, vector store)
- [ ] Kubernetes deployment with autoscaling
- [ ] CI/CD pipeline with automated evaluation
- [ ] Latency and cost optimisation (caching, batching, model routing)
