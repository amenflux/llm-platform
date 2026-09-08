"""Continuous low-rate traffic generator.

Dashboards built on rate() queries show nothing when a service is idle, which
makes a working system look broken. This sends a steady trickle of realistic
requests so latency, throughput and error panels always carry signal.
"""

import itertools
import logging
import os
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TARGET_URL = os.getenv("TARGET_URL", "http://app:8000/generate")
ASK_URL = os.getenv("ASK_URL", "http://app:8000/ask")
INTERVAL_SECONDS = float(os.getenv("REQUEST_INTERVAL_SECONDS", "20"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))

# Varied lengths so token counts and latency differ between requests, which
# makes the histograms show a real distribution rather than a flat line.
PROMPTS = [
    "Reply with one word: ok.",
    "In one sentence, what is a container?",
    "Name three benefits of infrastructure as code.",
    "Explain the difference between a Deployment and a StatefulSet in Kubernetes.",
    "Summarise what an Internet Gateway does in an AWS VPC, in two sentences.",
]

# Deliberately mixed: questions the indexed corpus covers, and questions it does
# not. Without the second group the refusal path is never exercised and the
# retrieval-quality histogram only ever sees good scores — the drift panels would
# look healthy because nothing is testing them, not because nothing is wrong.
QUESTIONS = [
    "What does llm_requests_in_flight measure?",
    "Why is the model call timed separately from the HTTP request?",
    "What distance metric does the vector store use?",
    "How does chunk overlap help retrieval?",
    "What is the airspeed velocity of an unladen swallow?",
    "Who won the Champions League in 2011?",
]


def main() -> None:
    logging.info(f"load generator starting: target={TARGET_URL} interval={INTERVAL_SECONDS}s")

    # Wait for the API to accept traffic before starting the loop.
    health_url = TARGET_URL.rsplit("/", 1)[0] + "/health"
    for attempt in range(30):
        try:
            if requests.get(health_url, timeout=5).status_code == 200:
                logging.info("target is healthy, beginning load")
                break
        except requests.RequestException:
            pass
        time.sleep(2)

    # Alternate plain generation and grounded retrieval so both paths carry load.
    for prompt, question in zip(itertools.cycle(PROMPTS), itertools.cycle(QUESTIONS)):
        for url, payload, kind in (
            (TARGET_URL, {"prompt": prompt}, "generate"),
            (ASK_URL, {"question": question}, "ask"),
        ):
            started = time.perf_counter()
            try:
                response = requests.post(
                    url,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,  # never block forever on a hung server
                )
                elapsed = time.perf_counter() - started
                if response.ok:
                    body = response.json()
                    logging.info(
                        f"kind={kind} status={response.status_code} elapsed={elapsed:.2f}s "
                        f"tokens={body.get('usage', {}).get('total_tokens')} "
                        f"refused={body.get('refused', False)}"
                    )
                else:
                    logging.warning(f"kind={kind} status={response.status_code} elapsed={elapsed:.2f}s")
            except requests.RequestException as exc:
                # A generator that dies on the first blip is useless; log and continue.
                logging.warning(f"kind={kind} request failed: {type(exc).__name__}: {exc}")

            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
