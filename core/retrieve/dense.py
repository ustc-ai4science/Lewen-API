"""Qdrant vector database operations (dense retrieval).

Stores only paper_id + dense_vector. Uses HNSW index. All paper metadata
is retrieved from SQLite (papers.db) after vector search.
"""

from __future__ import annotations

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    PointIdsList,
    PointStruct,
    VectorParams,
)

import config

_client: QdrantClient | None = None


def _paper_id_to_point_id(paper_id: str) -> int:
    """Convert paper_id to uint64 point ID for Qdrant."""
    return hash(paper_id) & 0xFFFFFFFFFFFFFFFF


def get_client() -> QdrantClient:
    """Return a singleton QdrantClient.

    Uses QDRANT_PATH for local mode if set; otherwise connects to Qdrant Server.

    Returns:
        QdrantClient connected to the server or local storage.
    """
    global _client
    if _client is None:
        if config.QDRANT_PATH:
            _client = QdrantClient(path=config.QDRANT_PATH)
            print(f"✅ Qdrant connected (local): {config.QDRANT_PATH}")
        else:
            _client = QdrantClient(
                host=config.QDRANT_HOST,
                port=config.QDRANT_PORT,
                prefer_grpc=config.QDRANT_PREFER_GRPC,
                timeout=config.QDRANT_TIMEOUT,
            )
            print(f"✅ Qdrant connected: {config.QDRANT_HOST}:{config.QDRANT_PORT}")
    return _client


def init_collection(drop_existing: bool = False) -> None:
    """Create the papers collection if it does not exist.

    Args:
        drop_existing: If True, drop and recreate the collection.
    """
    client = get_client()
    name = config.QDRANT_COLLECTION_NAME

    if client.collection_exists(name):
        if drop_existing:
            client.delete_collection(name)
            print(f"🗑️ Dropped existing collection '{name}'.")
        else:
            print(f"ℹ️ Collection '{name}' already exists, skipping creation.")
            return

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(
            size=config.VECTOR_DIM,
            distance=Distance.COSINE,
        ),
    )
    print(f"✅ Collection '{name}' created.")


def ensure_index() -> None:
    """Qdrant builds HNSW index automatically. No-op for compatibility."""
    client = get_client()
    name = config.QDRANT_COLLECTION_NAME
    if not client.collection_exists(name):
        print(f"⚠️ Collection '{name}' does not exist. Run load_embeddings_to_qdrant first.")
        return
    print("ℹ️ Qdrant HNSW index is built automatically.")


def insert_vectors(
    paper_ids: list[str],
    vectors: np.ndarray,
) -> None:
    """Insert paper_id + dense_vector pairs into Qdrant.

    Args:
        paper_ids: List of SHA paper_ids.
        vectors: Dense vectors, shape (len(paper_ids), dim).
    """
    client = get_client()
    points = [
        PointStruct(
            id=_paper_id_to_point_id(pid),
            vector=vec.tolist(),
            payload={"paper_id": pid},
        )
        for pid, vec in zip(paper_ids, vectors)
    ]
    client.upsert(
        collection_name=config.QDRANT_COLLECTION_NAME,
        points=points,
    )


def vector_search(
    query_vector: list[float],
    top_k: int = 100,
) -> list[tuple[str, float]]:
    """Search papers by dense vector similarity.

    Args:
        query_vector: Query embedding (dim=1024).
        top_k: Number of results to return.

    Returns:
        List of (paper_id, cosine_score) tuples, sorted by score desc.
    """
    client = get_client()
    response = client.query_points(
        collection_name=config.QDRANT_COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=["paper_id"],
    )
    results = response.points if hasattr(response, "points") else []

    output = []
    for hit in results:
        pid = hit.payload.get("paper_id") if hit.payload else None
        score = hit.score if hit.score is not None else 0.0
        if pid:
            output.append((pid, score))
    return output


def vector_search_batch(
    query_vectors: list[list[float]],
    top_k: int = 100,
) -> list[list[tuple[str, float]]]:
    """Batch search papers by dense vector similarity.

    Args:
        query_vectors: List of query embeddings (each dim=1024).
        top_k: Number of results per query.

    Returns:
        List of result lists; each inner list is (paper_id, score) tuples.
    """
    return [vector_search(vec, top_k=top_k) for vec in query_vectors] if query_vectors else []


def delete_vectors(paper_ids: list[str]) -> None:
    """Delete vectors by paper_id.

    Args:
        paper_ids: List of paper_ids to remove from Qdrant.
    """
    if not paper_ids:
        return
    client = get_client()
    point_ids = [_paper_id_to_point_id(pid) for pid in paper_ids]
    client.delete(
        collection_name=config.QDRANT_COLLECTION_NAME,
        points_selector=PointIdsList(points=point_ids),
    )
