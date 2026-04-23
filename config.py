"""Centralized configuration for Paper Search API."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
PAPER_DATA_DIR = PROJECT_ROOT / "PaperData"

PAPERS_DB_PATH = str(CORPUS_DIR / "papers.db")

CORPUS_DIR.mkdir(parents=True, exist_ok=True)

# ── Semantic Scholar API ───────────────────────────────────────────────
S2_API_KEY: str = os.getenv("S2_API_KEY", "")
S2_API_BASE_URL: str = "https://api.semanticscholar.org/graph/v1"

# ── Embedding Model ───────────────────────────────────────────────────
BGE_M3_MODEL_PATH: str = "/data/wdy/Downloads/models/BAAI/bge-m3"
VECTOR_DIM: int = 1024
GPU_DEVICE_ID: int = int(os.getenv("GPU_DEVICE_ID", "1"))

# ── Embedding Batch Queue ────────────────────────────────────────────
# Batch multiple search queries for GPU encoding to amortize transfer overhead.
EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_BATCH_TIMEOUT_MS: float = float(os.getenv("EMBEDDING_BATCH_TIMEOUT_MS", "50"))  # 0.05s

# ── Dense Search Batch Queue ─────────────────────────────────────────
# Batch multiple vector searches into one Qdrant API call.
DENSE_SEARCH_BATCH_SIZE: int = int(os.getenv("DENSE_SEARCH_BATCH_SIZE", "32"))
DENSE_SEARCH_BATCH_TIMEOUT_MS: float = float(os.getenv("DENSE_SEARCH_BATCH_TIMEOUT_MS", "50"))  # 0.05s

# ── FTS5 Search Batch Queue ───────────────────────────────────────────
# Batch multiple FTS5 queries; run in one SQLite connection to reduce overhead.
FTS5_SEARCH_BATCH_SIZE: int = int(os.getenv("FTS5_SEARCH_BATCH_SIZE", "32"))
FTS5_SEARCH_BATCH_TIMEOUT_MS: float = float(os.getenv("FTS5_SEARCH_BATCH_TIMEOUT_MS", "50"))  # 0.05s

# ── Qdrant ─────────────────────────────────────────────────────────────
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6334"))  # gRPC port
QDRANT_PATH: str | None = os.getenv("QDRANT_PATH")  # Non-empty: use local embedded mode
QDRANT_COLLECTION_NAME: str = "papers"
QDRANT_PREFER_GRPC: bool = True
QDRANT_TIMEOUT: float = float(os.getenv("QDRANT_TIMEOUT", "300"))

# ── API Server ─────────────────────────────────────────────────────────
API_HOST: str = "0.0.0.0"
API_PORT: int = 4000
# Qdrant Server supports multi-worker; increase for high concurrency
UVICORN_WORKERS: int = int(os.getenv("UVICORN_WORKERS", "4"))
UVICORN_TIMEOUT_KEEP_ALIVE: int = int(os.getenv("UVICORN_TIMEOUT_KEEP_ALIVE", "60"))
UVICORN_LIMIT_CONCURRENCY: int = int(os.getenv("UVICORN_LIMIT_CONCURRENCY", "500"))  # Max concurrent connections

# ── Search Defaults ────────────────────────────────────────────────────
DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 100
RRF_K: int = 60
# Max concurrent heavy ops. Qdrant handles concurrency well; can increase.
HEAVY_OPS_MAX_CONCURRENT: int = int(os.getenv("HEAVY_OPS_MAX_CONCURRENT", "100"))
# Per-request timeout (s). Matches client timeout (e.g. test_load.py --timeout 30).
REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "30"))

# ── Auth ───────────────────────────────────────────────────────────────
AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "false").lower() in ("1", "true", "yes")
AUTH_DB_PATH: str = str(CORPUS_DIR / "auth.db")
ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "")
AUTH_CACHE_TTL: int = int(os.getenv("AUTH_CACHE_TTL", "60"))  # seconds

# ── Ingest Defaults ───────────────────────────────────────────────────
INGEST_BATCH_SIZE: int = 5000
SQLITE_CACHE_SIZE: int = -1024 * 512  # 512 MB (more cache = faster SQLite/FTS5)
SQLITE_MMAP_SIZE: int = 512 * 1024 * 1024  # 512 MB for FTS5 read performance
SQLITE_BUSY_TIMEOUT_MS: int = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "300000"))  # 5 min
