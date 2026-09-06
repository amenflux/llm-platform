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

    for prompt in itertools.cycle(PROMPTS):
        started = time.perf_counter()
        try:
            response = requests.post(
                TARGET_URL,
                json={"prompt": prompt},
                timeout=REQUEST_TIMEOUT,  # never block forever on a hung server
            )
            elapsed = time.perf_counter() - started
            if response.ok:
                body = response.json()
                logging.info(
                    f"status={response.status_code} elapsed={elapsed:.2f}s "
                    f"tokens={body.get('usage', {}).get('total_tokens')} "
                    f"tps={body.get('tokens_per_second')}"
                )
            else:
                logging.warning(f"status={response.status_code} elapsed={elapsed:.2f}s")
        except requests.RequestException as exc:
            # A generator that dies on the first blip is useless; log and continue.
            logging.warning(f"request failed: {type(exc).__name__}: {exc}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
