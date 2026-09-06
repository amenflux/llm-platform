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

Two of these are worth calling out:

**`llm_request_duration_seconds` times the model call alone**, excluding HTTP and
serialisation overhead. Compared against the end-to-end HTTP histogram it answers
"is the model slow, or is my service slow?" — a question a single latency metric
cannot.

**`llm_requests_in_flight` uses a gauge that increments on entry and decrements on
exit even when the call raises**, so it can't leak upward over time. Sustained
growth means arrivals are outpacing completions — the earliest saturation signal
you get.

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
- [x] LLM-specific telemetry: throughput, concurrency, cost, error taxonomy
- [x] Containerised stack via Docker Compose
- [x] Terraform infrastructure definitions
- [ ] Retrieval-augmented generation (chunking, embeddings, vector store)
- [ ] Kubernetes deployment with autoscaling
- [ ] CI/CD pipeline with automated evaluation
- [ ] Latency and cost optimisation (caching, batching, model routing)
