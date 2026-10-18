"""ChromaDB-backed RAG pipeline for storing and retrieving similar past pull requests with local fallback."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any

from loguru import logger

from backend.github_client import get_runs_root
from backend.rag.embedder import build_pr_embedding_document, embed_text
from backend.run_store import list_run_metadata

DEFAULT_CHROMADB_DIR = "/tmp/mergeflow-chromadb"
CHROMADB_COLLECTION_NAME = "mergeflow_pr_history"
DEFAULT_TOP_K = 3


@dataclass(frozen=True)
class SimilarPullRequest:
    pr_id: str
    repository: str
    pr_number: int | None
    title: str
    summary: str
    change_types: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    merged_at: str | None = None
    author: str = ""
    similarity_score: float = 0.0
    source_backend: str = "chromadb"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RAGStoreResult:
    success: bool
    pr_id: str
    repository: str
    pr_number: int | None
    backend: str
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RAGRetrievalResult:
    success: bool
    repository: str
    similar_prs: list[SimilarPullRequest] = field(default_factory=list)
    backend: str = "chromadb"
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "repository": self.repository,
            "backend": self.backend,
            "errorMessage": self.error_message,
            "similarPrCount": len(self.similar_prs),
            "similarPrs": [item.as_dict() for item in self.similar_prs],
        }


def get_chromadb_dir() -> Path:
    return Path(os.getenv("MERGEFLOW_CHROMADB_DIR", DEFAULT_CHROMADB_DIR))


def get_fallback_index_path() -> Path:
    return get_runs_root() / "rag_fallback_index.json"


def pr_document_id(repository: str, pr_number: int | None) -> str:
    safe_repo = repository.strip().lower().replace("/", "__") or "unknown_repo"
    pr_part = str(pr_number) if pr_number is not None else "unknown"
    return f"{safe_repo}__{pr_part}"


def _get_chroma_collection() -> Any | None:
    if os.getenv("MERGEFLOW_DISABLE_CHROMADB", "").strip().lower() in {"1", "true", "yes"}:
        return None

    try:
        import chromadb

        chroma_dir = get_chromadb_dir()
        chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(chroma_dir))
        return client.get_or_create_collection(
            name=CHROMADB_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as error:
        logger.warning(
            "ChromaDB collection unavailable; using JSON cosine-similarity fallback error={error}",
            error=str(error),
        )
        return None


def store_pr_context(
    repository: str,
    pr_number: int | None,
    title: str,
    author: str = "",
    merged_at: str | None = None,
    change_types: list[str] | None = None,
    summary: str = "",
    changed_files: list[str] | None = None,
    diff_excerpt: str = "",
    endpoints: list[str] | None = None,
) -> RAGStoreResult:
    """Embed and store a merged PR in ChromaDB and the local fallback index."""
    doc_id = pr_document_id(repository, pr_number)
    normalized_types = list(change_types or [])
    normalized_files = list(changed_files or [])
    normalized_endpoints = list(endpoints or [])

    document_text = build_pr_embedding_document(
        repository=repository,
        pr_number=pr_number,
        title=title,
        change_types=normalized_types,
        summary=summary,
        changed_files=normalized_files,
        diff_excerpt=diff_excerpt,
        endpoints=normalized_endpoints,
    )
    embedding = embed_text(document_text)
    now_iso = datetime.now(timezone.utc).isoformat()

    metadata_record: dict[str, Any] = {
        "pr_id": doc_id,
        "repository": repository,
        "pr_number": pr_number if pr_number is not None else -1,
        "title": title or f"PR #{pr_number}",
        "author": author or "",
        "merged_at": merged_at or "",
        "summary": summary or "",
        "change_types_json": json.dumps(normalized_types),
        "changed_files_json": json.dumps(normalized_files),
        "endpoints_json": json.dumps(normalized_endpoints),
        "indexed_at": now_iso,
    }

    # Always persist to the local fallback index so RAG works even if ChromaDB is unavailable
    _write_fallback_entry(doc_id, document_text, embedding, metadata_record)

    collection = _get_chroma_collection()
    if collection is not None:
        try:
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[document_text],
                metadatas=[metadata_record],
            )
            logger.info(
                "Stored PR context in ChromaDB doc_id={doc_id} repo={repo} pr_number={pr_number}",
                doc_id=doc_id,
                repo=repository,
                pr_number=pr_number,
            )
            return RAGStoreResult(
                success=True,
                pr_id=doc_id,
                repository=repository,
                pr_number=pr_number,
                backend="chromadb",
            )
        except Exception as error:
            logger.warning(
                "ChromaDB upsert failed; stored PR context in fallback index doc_id={doc_id} error={error}",
                doc_id=doc_id,
                error=str(error),
            )
            return RAGStoreResult(
                success=True,
                pr_id=doc_id,
                repository=repository,
                pr_number=pr_number,
                backend="fallback_json",
                error_message=str(error),
            )

    logger.info(
        "Stored PR context in local RAG fallback index doc_id={doc_id} repo={repo} pr_number={pr_number}",
        doc_id=doc_id,
        repo=repository,
        pr_number=pr_number,
    )
    return RAGStoreResult(
        success=True,
        pr_id=doc_id,
        repository=repository,
        pr_number=pr_number,
        backend="fallback_json",
    )


def retrieve_similar_prs(
    repository: str,
    query_text: str,
    exclude_pr_number: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> RAGRetrievalResult:
    """Retrieve the top-K most similar past PRs for a repository from ChromaDB or fallback store."""
    try:
        seed_from_run_store(repository, exclude_pr_number=exclude_pr_number)
    except Exception as error:
        logger.warning("RAG run_store backfill skipped error={error}", error=str(error))

    query_embedding = embed_text(query_text)
    collection = _get_chroma_collection()

    if collection is not None:
        try:
            total_count = collection.count()
            if total_count > 0:
                n_results = min(max(top_k + 2, 5), total_count)
                where_filter: dict[str, Any] | None = {"repository": repository} if repository else None
                query_response = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    where=where_filter,
                )
                similar = _parse_chroma_query_response(
                    query_response,
                    exclude_pr_number=exclude_pr_number,
                    top_k=top_k,
                )
                if similar:
                    logger.info(
                        "Retrieved similar PRs from ChromaDB repo={repo} count={count} prs={prs}",
                        repo=repository,
                        count=len(similar),
                        prs=[item.pr_number for item in similar],
                    )
                    return RAGRetrievalResult(
                        success=True,
                        repository=repository,
                        similar_prs=similar,
                        backend="chromadb",
                    )
        except Exception as error:
            logger.warning(
                "ChromaDB query failed; falling back to local RAG index repo={repo} error={error}",
                repo=repository,
                error=str(error),
            )

    try:
        fallback_matches = _retrieve_from_fallback_index(
            repository=repository,
            query_embedding=query_embedding,
            exclude_pr_number=exclude_pr_number,
            top_k=top_k,
        )
        logger.info(
            "Retrieved similar PRs from fallback index repo={repo} count={count} prs={prs}",
            repo=repository,
            count=len(fallback_matches),
            prs=[item.pr_number for item in fallback_matches],
        )
        return RAGRetrievalResult(
            success=True,
            repository=repository,
            similar_prs=fallback_matches,
            backend="fallback_json",
        )
    except Exception as error:
        logger.exception("RAG retrieval failed completely; returning empty context error={error}", error=str(error))
        return RAGRetrievalResult(
            success=False,
            repository=repository,
            similar_prs=[],
            backend="fallback_empty",
            error_message=str(error),
        )


def seed_from_run_store(repository: str, exclude_pr_number: int | None = None) -> int:
    """Ensure existing MergeFlow run history for this repository is indexed in RAG."""
    existing_fallback = _read_fallback_index()
    seeded_count = 0

    for metadata in list_run_metadata():
        run_repo = metadata.get("repository")
        pr_num = metadata.get("prNumber")
        if not isinstance(run_repo, str) or run_repo.lower() != repository.lower():
            continue
        if isinstance(pr_num, int) and exclude_pr_number is not None and pr_num == exclude_pr_number:
            continue

        doc_id = pr_document_id(run_repo, pr_num if isinstance(pr_num, int) else None)
        if doc_id in existing_fallback:
            continue

        classification = metadata.get("classification") if isinstance(metadata.get("classification"), dict) else {}
        change_types = classification.get("changeTypes") if isinstance(classification.get("changeTypes"), list) else []
        summary = str(classification.get("summary") or "")
        title = str(metadata.get("prTitle") or f"PR #{pr_num}")

        if not summary and not title:
            continue

        store_pr_context(
            repository=run_repo,
            pr_number=pr_num if isinstance(pr_num, int) else None,
            title=title,
            author=str(metadata.get("author") or ""),
            merged_at=metadata.get("mergedAt") if isinstance(metadata.get("mergedAt"), str) else None,
            change_types=[str(ct) for ct in change_types],
            summary=summary,
        )
        seeded_count += 1

    if seeded_count > 0:
        logger.info("Backfilled {count} historical PR(s) into RAG for repo={repo}", count=seeded_count, repo=repository)
    return seeded_count


def format_rag_context_for_prompt(retrieval_result: RAGRetrievalResult) -> str:
    """Format retrieved similar PRs into a grounded prompt section for LLM generation."""
    if not retrieval_result.similar_prs:
        return "No similar past PRs found in repository history."

    blocks: list[str] = []
    for index, pr in enumerate(retrieval_result.similar_prs, start=1):
        pr_label = f"PR #{pr.pr_number}" if pr.pr_number is not None else pr.pr_id
        change_types = ", ".join(pr.change_types) if pr.change_types else "Unspecified"
        endpoints = ", ".join(pr.endpoints) if pr.endpoints else "None recorded"
        files = ", ".join(pr.changed_files) if pr.changed_files else "None recorded"
        blocks.append(
            f"{index}. {pr_label}: {pr.title} (similarity={pr.similarity_score:.2f})\n"
            f"   - Change Types: {change_types}\n"
            f"   - Summary: {pr.summary}\n"
            f"   - Endpoints: {endpoints}\n"
            f"   - Changed Files: {files}"
        )

    return "\n\n".join(blocks)


def _parse_chroma_query_response(
    query_response: dict[str, Any],
    exclude_pr_number: int | None,
    top_k: int,
) -> list[SimilarPullRequest]:
    ids_nested = query_response.get("ids") or [[]]
    metadatas_nested = query_response.get("metadatas") or [[]]
    distances_nested = query_response.get("distances") or [[]]

    ids = ids_nested[0] if ids_nested else []
    metadatas = metadatas_nested[0] if metadatas_nested else []
    distances = distances_nested[0] if distances_nested else []

    results: list[SimilarPullRequest] = []
    for index, doc_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        pr_num_raw = metadata.get("pr_number")
        pr_number = int(pr_num_raw) if isinstance(pr_num_raw, int) and pr_num_raw >= 0 else None

        if exclude_pr_number is not None and pr_number == exclude_pr_number:
            continue

        similarity = round(max(0.0, min(1.0, 1.0 - distance)), 4)
        results.append(_metadata_to_similar_pr(str(doc_id), metadata, similarity, "chromadb"))
        if len(results) >= top_k:
            break

    return results


def _metadata_to_similar_pr(
    doc_id: str,
    metadata: dict[str, Any],
    similarity: float,
    source_backend: str,
) -> SimilarPullRequest:
    pr_num_raw = metadata.get("pr_number")
    pr_number = int(pr_num_raw) if isinstance(pr_num_raw, int) and pr_num_raw >= 0 else None
    return SimilarPullRequest(
        pr_id=doc_id,
        repository=str(metadata.get("repository") or ""),
        pr_number=pr_number,
        title=str(metadata.get("title") or ""),
        summary=str(metadata.get("summary") or ""),
        change_types=_loads_list(metadata.get("change_types_json")),
        changed_files=_loads_list(metadata.get("changed_files_json")),
        endpoints=_loads_list(metadata.get("endpoints_json")),
        merged_at=str(metadata.get("merged_at") or "") or None,
        author=str(metadata.get("author") or ""),
        similarity_score=similarity,
        source_backend=source_backend,
    )


def _loads_list(raw_json: Any) -> list[str]:
    if isinstance(raw_json, list):
        return [str(x) for x in raw_json]
    if isinstance(raw_json, str) and raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    return []


def _read_fallback_index() -> dict[str, dict[str, Any]]:
    path = get_fallback_index_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_fallback_entry(
    doc_id: str,
    document_text: str,
    embedding: list[float],
    metadata: dict[str, Any],
) -> None:
    try:
        path = get_fallback_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        index_data = _read_fallback_index()
        index_data[doc_id] = {
            "document": document_text,
            "embedding": embedding,
            "metadata": metadata,
        }
        path.write_text(json.dumps(index_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as error:
        logger.warning("Failed to write RAG fallback index entry error={error}", error=str(error))


def _retrieve_from_fallback_index(
    repository: str,
    query_embedding: list[float],
    exclude_pr_number: int | None,
    top_k: int,
) -> list[SimilarPullRequest]:
    index_data = _read_fallback_index()
    scored: list[tuple[float, str, dict[str, Any]]] = []

    for doc_id, entry in index_data.items():
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        entry_repo = str(metadata.get("repository") or "")
        if repository and entry_repo.lower() != repository.lower():
            continue

        pr_num_raw = metadata.get("pr_number")
        pr_number = int(pr_num_raw) if isinstance(pr_num_raw, int) and pr_num_raw >= 0 else None
        if exclude_pr_number is not None and pr_number == exclude_pr_number:
            continue

        embedding = entry.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            continue

        score = _cosine_similarity(query_embedding, [float(x) for x in embedding])
        scored.append((score, doc_id, metadata))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        _metadata_to_similar_pr(doc_id, metadata, round(score, 4), "fallback_json")
        for score, doc_id, metadata in scored[:top_k]
    ]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))
