"""FastAPI application — Paper Search API aligned with Semantic Scholar."""

from __future__ import annotations

import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI

import config

# ── Logging ───────────────────────────────────────────────────────────
LOG_DIR = config.PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_handler = RotatingFileHandler(
    LOG_DIR / "api.log",
    maxBytes=50 * 1024 * 1024,  # 50 MB per file
    backupCount=5,               # keep api.log.1 … api.log.5
    encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

logging.basicConfig(level=logging.INFO, handlers=[_log_handler, logging.StreamHandler()])
logging.getLogger("uvicorn.access").handlers = [_log_handler, logging.StreamHandler()]
logging.getLogger("uvicorn.error").handlers = [_log_handler, logging.StreamHandler()]

from api.paper import router as paper_router
from api.paper_detail import router as paper_detail_router
from api.paper_citations import router as paper_citations_router
from api.admin import router as admin_router
from core.retrieve import Retriever
from core.retrieve.embedding_batcher import EmbeddingBatcher
from core.retrieve.dense_search_batcher import DenseSearchBatcher
from core.retrieve.fts5_search_batcher import FTS5SearchBatcher
from core.citation.database import init_db

sys.path.insert(0, str(Path(__file__).resolve().parent))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify database, init retriever, optionally warm up embedding model."""
    print("🚀 Starting Paper Search API ...")

    db_path = Path(config.PAPERS_DB_PATH)
    if not db_path.exists():
        print("⚠️ papers.db not found. Run ingest scripts first.")
        raise SystemExit(1)

    init_db(create_fts=False)
    print("✅ papers.db ready.")

    from auth.database import init_auth_db
    init_auth_db()
    print("✅ auth.db ready.")

    dense_search_batcher = DenseSearchBatcher()
    dense_search_batcher.start()
    app.state.dense_search_batcher = dense_search_batcher

    fts5_search_batcher = FTS5SearchBatcher()
    fts5_search_batcher.start()
    app.state.fts5_search_batcher = fts5_search_batcher

    app.state.retriever = Retriever(
        search_batcher=dense_search_batcher,
        fts5_batcher=fts5_search_batcher,
    )
    print("✅ Retriever initialized (embedding + dense + FTS5 batchers enabled).")

    # Dedicated thread pool for blocking ops (search, citations, etc.).
    app.state.executor = ThreadPoolExecutor(max_workers=config.HEAVY_OPS_MAX_CONCURRENT)
    print(f"✅ Thread pool ready (max_workers={config.HEAVY_OPS_MAX_CONCURRENT}).")

    try:
        from core.retrieve.embedding import encode
        encode(["warmup"])
        print("✅ BGE-M3 embedding model ready.")
        batcher = EmbeddingBatcher()
        batcher.start()
        app.state.embedding_batcher = batcher
        print(f"✅ Embedding batcher started (batch_size={config.EMBEDDING_BATCH_SIZE}, "
              f"timeout_ms={config.EMBEDDING_BATCH_TIMEOUT_MS}).")
    except Exception as e:
        print(f"⚠️ BGE-M3 warmup failed: {e}. Dense/hybrid search unavailable.")
        app.state.embedding_batcher = None

    try:
        from core.retrieve.dense import get_client, vector_search
        get_client()
        # Warm up Qdrant: run a minimal search to load index into memory
        dummy_vec = [0.0] * config.VECTOR_DIM
        vector_search(dummy_vec, top_k=1)
        print("✅ Qdrant warmed up.")
    except Exception as e:
        print(f"⚠️ Qdrant warmup failed: {e}. Dense/hybrid search may be slow on first request.")

    try:
        from core.retrieve.sparse import fts5_search
        fts5_search("transformer", top_k=1)
        print("✅ FTS5 warmed up.")
    except Exception as e:
        print(f"⚠️ FTS5 warmup failed: {e}")

    print("✅ All models loaded. API ready.")
    yield
    print("👋 Shutting down.")
    batcher = getattr(app.state, "embedding_batcher", None)
    if batcher is not None:
        batcher.stop()
        print("✅ Embedding batcher stopped.")
    dense_batcher = getattr(app.state, "dense_search_batcher", None)
    if dense_batcher is not None:
        dense_batcher.stop()
        print("✅ Dense search batcher stopped.")
    fts5_batcher = getattr(app.state, "fts5_search_batcher", None)
    if fts5_batcher is not None:
        fts5_batcher.stop()
        print("✅ FTS5 search batcher stopped.")
    executor = getattr(app.state, "executor", None)
    if executor is not None:
        executor.shutdown(wait=False)
        print("✅ Thread pool shutdown.")


app = FastAPI(
    title="Paper Search API",
    description="Academic paper search service.",
    version="0.2.0",
    lifespan=lifespan,
)

if config.AUTH_ENABLED:
    from auth.middleware import ApiKeyMiddleware
    app.add_middleware(ApiKeyMiddleware)
    logging.getLogger(__name__).info("🔐 API key authentication enabled.")

app.include_router(paper_router)
app.include_router(paper_citations_router)
app.include_router(paper_detail_router)
app.include_router(admin_router)


def _force_exit_on_second_sigint():
    """Force exit on second Ctrl+C (e.g. when BGE-M3/PyTorch cleanup hangs)."""
    count = [0]

    def handler(signum, frame):
        count[0] += 1
        if count[0] >= 2:
            print("\n⚠️ Force exit.")
            sys.exit(1)
        print("\n👋 Shutting down... (Ctrl+C again to force)")

    signal.signal(signal.SIGINT, handler)


if __name__ == "__main__":
    _force_exit_on_second_sigint()
    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        workers=config.UVICORN_WORKERS,
        reload=False,
        timeout_keep_alive=config.UVICORN_TIMEOUT_KEEP_ALIVE,
        limit_concurrency=config.UVICORN_LIMIT_CONCURRENCY,
    )
