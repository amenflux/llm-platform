"""Retrieval-Augmented Generation: ingestion, embedding, storage and retrieval.

The pipeline has two halves that run at different times:

  Ingestion (once, ahead of time)
      document -> chunks -> embeddings -> vector store

  Query (on every question)
      question -> embedding -> nearest chunks -> injected into the prompt

An LLM only knows what it saw during training. RAG is how it answers questions
about documents it has never seen: rather than trying to fit a whole corpus into
the prompt, we store the corpus as vectors and retrieve only the few passages
that are semantically closest to the question.
"""

import logging
import os
import re
import uuid
from typing import Iterable

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-minilm")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "documents")

# Chunking is the highest-leverage knob in RAG:
#   too large  -> retrieved passages carry irrelevant filler, diluting the prompt
#   too small  -> a passage loses the context that makes it meaningful
# The overlap keeps a sentence that straddles a boundary intact in one of the
# two neighbouring chunks.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# Confidence floor. Below this similarity the corpus does not meaningfully cover
# the question, and calling the model anyway costs tokens to produce a non-answer
# — or worse, invites it to improvise from whatever weakly-related text came back.
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.25"))

qdrant = QdrantClient(url=QDRANT_URL)


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries.

    A fixed character window is the simplest strategy. Splitting on blank lines
    first keeps semantically related sentences together, which retrieves better
    than slicing blindly every N characters.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        # Start a new chunk once adding this paragraph would exceed the window.
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current.strip())
            # Carry the tail of the previous chunk forward so context spanning
            # the boundary is not lost.
            current = current[-overlap:] + "\n\n" + paragraph if overlap else paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _embedding_client() -> OpenAI:
    """Embeddings are served by the same OpenAI-compatible endpoint as chat."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return OpenAI(base_url=base_url, api_key="ollama")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Turn text into vectors. Text with similar meaning yields nearby vectors."""
    response = _embedding_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def ensure_collection(vector_size: int) -> None:
    """Create the collection on first use.

    COSINE distance measures the angle between vectors rather than their
    magnitude, which is what "similar meaning" means for embeddings.
    """
    existing = {c.name for c in qdrant.get_collections().collections}
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        logging.info(f"created collection={COLLECTION_NAME} vector_size={vector_size}")


def index_documents(documents: Iterable[dict]) -> dict:
    """Chunk, embed and store documents. Each doc is {"source": str, "text": str}."""
    chunks: list[str] = []
    sources: list[str] = []

    for document in documents:
        for chunk in chunk_text(document["text"]):
            chunks.append(chunk)
            sources.append(document.get("source", "unknown"))

    if not chunks:
        return {"chunks_indexed": 0}

    vectors = embed_texts(chunks)
    ensure_collection(vector_size=len(vectors[0]))

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                # The payload travels with the vector, so a search returns the
                # original text — the vector alone is not human-readable.
                payload={"text": chunk, "source": source},
            )
            for chunk, vector, source in zip(chunks, vectors, sources)
        ],
    )

    logging.info(f"indexed chunks={len(chunks)} collection={COLLECTION_NAME}")
    return {"chunks_indexed": len(chunks), "collection": COLLECTION_NAME}


def retrieve(question: str, top_k: int = 4) -> list[dict]:
    """Return the chunks whose meaning is closest to the question.

    top_k is the second big knob: more chunks give the model more to work with
    but cost tokens and can bury the answer in noise.
    """
    query_vector = embed_texts([question])[0]
    hits = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    ).points

    return [
        {
            "text": hit.payload.get("text", ""),
            "source": hit.payload.get("source", "unknown"),
            "score": round(hit.score, 4),
        }
        for hit in hits
    ]


def corpus_size() -> int:
    """Chunks currently stored, read from the vector store itself.

    The ingestion counter cannot answer this: it resets when the process
    restarts, while the corpus persists in the volume. Asking Qdrant is the only
    way to report what is actually retrievable right now.
    """
    try:
        return qdrant.count(collection_name=COLLECTION_NAME, exact=True).count
    except Exception:
        # The collection does not exist until the first ingest.
        return 0


def build_prompt(question: str, chunks: list[dict]) -> str:
    """Assemble the retrieved context and the question into one prompt.

    The instruction to answer only from the context is what separates RAG from
    ordinary generation: without it the model happily falls back on its training
    data and the citations become meaningless.
    """
    context = "\n\n---\n\n".join(
        f"[Source: {c['source']}]\n{c['text']}" for c in chunks
    )
    return (
        "Answer the question using only the context below. "
        "If the context does not contain the answer, say so plainly.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )
