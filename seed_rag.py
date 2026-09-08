"""Seed the vector store with documents so /ask has something to retrieve.

Reads local markdown files and posts them to the running API. Kept outside the
container so the corpus can change without rebuilding the image.
"""

import pathlib
import sys

import requests

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

    response = requests.post(API, json={"documents": documents}, timeout=300)
    response.raise_for_status()
    print("ingested:", response.json())


if __name__ == "__main__":
    main()
