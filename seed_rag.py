"""Seed the vector store with documents so /ask has something to retrieve.

Reads local markdown files and posts them to the running API. Kept outside the
container so the corpus can change without rebuilding the image, and written
against the standard library so it runs anywhere Python does.
"""

import json
import pathlib
import sys
import urllib.request

API = "http://localhost:8000/ingest"
FILES = ["README.md"]


def main() -> None:
    documents = []
    for name in FILES:
        path = pathlib.Path(name)
        if not path.exists():
            print(f"skipping missing file: {name}")
            continue
        documents.append({"source": name, "text": path.read_text()})

    if not documents:
        sys.exit("no documents found to ingest")

    request = urllib.request.Request(
        API,
        data=json.dumps({"documents": documents}).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Embedding every chunk can take a while on a cold model, so allow for it.
    with urllib.request.urlopen(request, timeout=600) as response:
        print("ingested:", json.load(response))


if __name__ == "__main__":
    main()
