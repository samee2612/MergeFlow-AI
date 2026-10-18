"""Sentence-transformers embedding module with deterministic fallback for MergeFlow RAG."""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from loguru import logger

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
MAX_EMBEDDING_TEXT_CHARS = 12000

_MODEL_INSTANCE: Any = None
_MODEL_LOAD_FAILED: bool = False


def get_embedding_model_name() -> str:
    return os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL


def is_sentence_transformers_enabled() -> bool:
    flag = os.getenv("MERGEFLOW_DISABLE_SENTENCE_TRANSFORMERS", "").strip().lower()
    return flag not in {"1", "true", "yes"}


def _load_sentence_transformer() -> Any | None:
    global _MODEL_INSTANCE, _MODEL_LOAD_FAILED
    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE
    if _MODEL_LOAD_FAILED or not is_sentence_transformers_enabled():
        return None

    model_name = get_embedding_model_name()
    try:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading sentence-transformers model model={model}", model=model_name)
        _MODEL_INSTANCE = SentenceTransformer(model_name)
        return _MODEL_INSTANCE
    except Exception as error:
        _MODEL_LOAD_FAILED = True
        logger.warning(
            "Could not load sentence-transformers model; using deterministic hash embedding fallback model={model} error={error}",
            model=model_name,
            error=str(error),
        )
        return None


def embed_text(text: str) -> list[float]:
    """Generate a normalized embedding vector for a single text string with automatic fallback."""
    cleaned = (text or "").strip()[:MAX_EMBEDDING_TEXT_CHARS]
    if not cleaned:
        cleaned = "empty_pull_request_context"

    model = _load_sentence_transformer()
    if model is not None:
        try:
            vector = model.encode(cleaned, normalize_embeddings=True)
            if hasattr(vector, "tolist"):
                result = [float(x) for x in vector.tolist()]
            else:
                result = [float(x) for x in vector]
            if result:
                return result
        except Exception as error:
            logger.warning(
                "sentence-transformers encode failed; falling back to deterministic embedding error={error}",
                error=str(error),
            )

    return deterministic_fallback_embedding(cleaned)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with automatic per-item fallback."""
    return [embed_text(text) for text in texts]


def deterministic_fallback_embedding(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Deterministic bag-of-tokens feature hashing vector (L2-normalized) when neural model is unavailable."""
    tokens = [token.lower() for token in text.replace("/", " ").replace("_", " ").split() if token.strip()]
    if not tokens:
        tokens = ["empty"]

    vector = [0.0] * dimension
    for index, token in enumerate(tokens):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if (digest[4] % 2 == 0) else -1.0
        weight = 1.0 + (0.25 if index < 25 else 0.0)
        vector[bucket] += sign * weight

        if index + 1 < len(tokens):
            bigram = f"{token}_{tokens[index + 1]}"
            bg_digest = hashlib.sha256(bigram.encode("utf-8")).digest()
            bg_bucket = int.from_bytes(bg_digest[:4], "big") % dimension
            bg_sign = 1.0 if (bg_digest[4] % 2 == 0) else -1.0
            vector[bg_bucket] += bg_sign * 0.5

    norm = math.sqrt(sum(val * val for val in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector

    return [round(val / norm, 6) for val in vector]


def build_pr_embedding_document(
    repository: str,
    pr_number: int | None,
    title: str,
    change_types: list[str] | None = None,
    summary: str = "",
    changed_files: list[str] | None = None,
    diff_excerpt: str = "",
    endpoints: list[str] | None = None,
) -> str:
    """Build a structured text representation of a PR for embedding and semantic search."""
    files_line = ", ".join(changed_files or [])
    types_line = ", ".join(change_types or [])
    endpoints_line = ", ".join(endpoints or [])
    parts = [
        f"Repository: {repository}",
        f"PR Number: #{pr_number}" if pr_number is not None else "PR Number: unknown",
        f"Title: {title}",
        f"Change Types: {types_line}" if types_line else "",
        f"Summary: {summary}" if summary else "",
        f"Endpoints: {endpoints_line}" if endpoints_line else "",
        f"Changed Files: {files_line}" if files_line else "",
        f"Diff Excerpt:\n{diff_excerpt[:3000]}" if diff_excerpt else "",
    ]
    return "\n".join(part for part in parts if part).strip()
