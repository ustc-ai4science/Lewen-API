# 技术架构与项目结构

## 1. 系统概述

乐问学术搜索 API（Lewen），基于 S2 PaperData（2026-01-27 全量快照）构建，支持增量更新，提供 RESTful 接口。

### 核心能力

| API | 路径 | 说明 |
|-----|------|------|
| 论文搜索 | `GET /paper/search` | 稀疏 / 稠密 / 混合检索，仅返回 arXiv 论文 |
| 标题检索 | `GET /paper/search/title` | 基于与查询最接近的标题匹配检索论文 |
| 论文详情 | `GET /paper/{paper_id}` | 按 SHA / arXiv ID / Corpus ID / arXiv URL 查询，仅支持 arXiv 论文 |
| 引用列表 | `GET /paper/{paper_id}/citations` | 引用该论文的论文列表（仅 arXiv 内部） |
| 参考文献 | `GET /paper/{paper_id}/references` | 该论文引用的论文列表（仅 arXiv 内部） |

---

## 2. 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | **FastAPI** + uvicorn | 异步 HTTP，自带 `/docs` OpenAPI 文档 |
| 关系数据 | **SQLite**（WAL 模式） | 单文件零配置，存放 paper_metadata、citations、ID 映射 |
| 全文检索 | **SQLite FTS5** | 内置 BM25 排序，替代 rank_bm25 内存方案 |
| 向量检索 | **Qdrant** | 高性能向量数据库，binary 部署 |
| Embedding | **BGE-M3**（1024 维） | 编码 title + abstract，GPU 推理 |
| 混合排序 | **RRF**（Reciprocal Rank Fusion） | 融合 FTS5 + Qdrant 结果 |

### 检索模式（`/paper/search` 的 `retrieval` 参数）

| 值 | 说明 | GPU 依赖 |
|----|------|----------|
| `sparse` | 仅 paper_fts_combined BM25（title+abstract） | 无 |
| `dense` | 仅 Qdrant 向量 | 需要 |
| `hybrid`（默认） | FTS5 + Qdrant + RRF 融合 | 需要 |

---

## 3. 数据规模

| 数据 | 规模 | 说明 |
|------|------|------|
| paper_metadata | ~300 万 | 仅 arXiv + abstract 的论文 |
| arXiv 论文 | ~300 万 | 与 paper_metadata 一致，FTS5 + Qdrant 索引 |
| 引用关系 | ~3000 万 | 仅 citing、cited 均在 arXiv 的边（按每篇 ~10 条估算） |

---

## 4. 数据库设计

所有关系数据存于 `corpus/papers.db`（单一 SQLite 文件）。

### 4.1 paper_metadata

存储仅 arXiv 且有 abstract 的论文元数据，由 paper-ids ⋈ papers ⋈ abstracts（按 corpusid 关联）合并而成，约束为 abstracts 中有记录且 papers 中有 ArXiv ID。

| 字段 | 类型 | 说明 |
|------|------|------|
| paper_id | TEXT PK | SHA（来自 paper-ids.primary） |
| corpus_id | INTEGER UNIQUE | S2 CorpusId |
| title | TEXT | |
| abstract | TEXT | |
| year | INTEGER | |
| venue | TEXT | |
| citation_count | INTEGER | |
| reference_count | INTEGER | |
| authors_json | TEXT | JSON 数组 |
| fields_of_study_json | TEXT | JSON 数组 |
| publication_types_json | TEXT | JSON 数组 |
| publication_date | TEXT | |
| open_access_pdf_json | TEXT | JSON 对象 |
| external_ids_json | TEXT | JSON 对象（含 ArXiv、DOI 等） |
| journal_json | TEXT | JSON 对象 |

### 4.2 citations（仅 3 列）

| 字段 | 类型 | 说明 |
|------|------|------|
| citation_id | INTEGER PK | |
| citing_corpus_id | INTEGER NOT NULL | 引用方 |
| cited_corpus_id | INTEGER | 被引方（可为 NULL） |

仅保留 citing、cited 均在 corpus（arXiv）的边；`cited_corpus_id IS NULL` 的边不插入。

索引：`cited_corpus_id`、`citing_corpus_id`。

### 4.3 corpus_id_mapping

| 字段 | 类型 | 说明 |
|------|------|------|
| corpus_id | INTEGER PK | |
| paper_id | TEXT NOT NULL | SHA |

### 4.4 arxiv_to_paper

| 字段 | 类型 | 说明 |
|------|------|------|
| arxiv_id | TEXT PK | 归一化（如 `2309.06180`，去掉版本号） |
| paper_id | TEXT NOT NULL | SHA |

### 4.5 paper_fts_title（FTS5 虚拟表）

```sql
CREATE VIRTUAL TABLE paper_fts_title USING fts5(paper_id, title);
```

自包含表，仅索引 title，供 `/paper/search/title` 使用。

### 4.6 paper_fts_combined（FTS5 虚拟表）

```sql
CREATE VIRTUAL TABLE paper_fts_combined USING fts5(paper_id, title_abstract);
```

自包含表，索引 title+abstract 拼接后的文本，供 `/paper/search` sparse/hybrid 使用。与 Qdrant 建库逻辑一致（`f"{title} {abstract}"`）。

### 4.7 Qdrant（`corpus/qdrant_storage/`）

| 字段 | 类型 | 说明 |
|------|------|------|
| paper_id | payload string | SHA |
| dense_vector | FLOAT[1024] | BGE-M3 编码 title+abstract |

Cosine 度量。仅存 arXiv 论文。通过独立的 Qdrant 服务端进程提供检索。

---

## 5. paper_id 多格式解析

API 中所有 `paper_id` 参数支持以下输入格式，由 `core/paper_id_resolver.py` 统一解析为 SHA：

| 输入格式 | 示例 | 解析方式 |
|----------|------|----------|
| SHA | `83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05` | 40 位十六进制，直接查 paper_metadata |
| arXiv ID | `2309.06180`、`2309.06180v1` | 归一化后查 arxiv_to_paper |
| Corpus ID | `215416146`、`CorpusId:215416146` | 查 corpus_id_mapping |
| arXiv URL | `https://arxiv.org/abs/2309.06180` | 提取 arXiv ID，再查 arxiv_to_paper |

解析优先级：URL → Corpus ID → arXiv ID → SHA。

---

## 6. 构建流程

```
Phase 1 ─ ingest_paper_metadata.py
  abstracts/*.gz ──→ abstracts_corpus_ids（有 abstract 的 corpus_id）
  paper-ids/*.gz ──→ 仅保留 abstracts 中的 corpus_id → sha
  papers/*.gz ────→ paper_metadata, corpus_id_mapping, arxiv_to_paper（仅 arXiv + abstract）

Phase 2 ─ ingest_citations.py
  citations/*.gz ──→ citations（3 列，仅 citing、cited 均在 arXiv 的边）

Phase 3 ─ 两步：编码 + 入库
  Step 1: encode_embeddings.py（4 卡并行，GPU 1,2,3,4）
    paper_metadata ──→ BGE-M3 encode ──→ corpus/embeddings/embeddings_shard_*.npz
  Step 2: load_embeddings_to_qdrant.py
    embeddings_shard_*.npz ──→ Qdrant

Phase 4a ─ ingest_fts_title.py
  paper_metadata（筛选 arXiv）──→ paper_fts_title

Phase 4b ─ ingest_fts_combined.py
  paper_metadata（筛选 arXiv）──→ paper_fts_combined（title+abstract 拼接）

Phase 5 ─ incremental 五段式流程
  Step 5-1: incremental/download.py
    下载增量 diff
  Step 5-2: incremental/validate.py
    校验 diff 并重下坏文件
  Step 5-3: incremental/sqlite_fts_merge.py
    PaperData/incremental/*/updates,deletes ──→ SQLite + FTS5
  Step 5-4: incremental/qdrant_encode.py
    _qdrant_task.json ──→ 多卡增量 embedding shard
  Step 5-5: incremental/qdrant_load.py
    incremental_embeddings_shard_*.npz ──→ Qdrant
```

### 构建命令

**Phase 1 先执行，Phase 2-1/2-2/2-3 可并行**

```bash
# Phase 1: 元数据（后续所有步骤的基础）
bash build_corpus/build_1_paper_metadata.sh        # 约 1.5–3 h

# Phase 2-1/2-2/2-3: 互相无依赖，可并行
bash build_corpus/build_2-1_citations.sh            # 引用关系，约 0.5–1.5 h
bash build_corpus/build_2-2_vectors.sh              # 向量编码 + 入库，约 0.5–1.5 h
bash build_corpus/build_2-3_fts.sh                  # FTS5 全文索引，约 10–30 min
```

**直接调用 Python（调试用）**

```bash
python build_corpus/ingest_paper_metadata.py
python build_corpus/ingest_citations.py
# Phase 2-2: 两步（4 卡并行编码）
bash build_corpus/build_2-2_vectors.sh
# 或手动分步：
# python build_corpus/encode_embeddings.py --gpu 1 --shard 0 --total-shards 4 &
# python build_corpus/encode_embeddings.py --gpu 2 --shard 1 --total-shards 4 &
# python build_corpus/encode_embeddings.py --gpu 3 --shard 2 --total-shards 4 &
# python build_corpus/encode_embeddings.py --gpu 4 --shard 3 --total-shards 4 &
# wait
# python build_corpus/load_embeddings_to_qdrant.py --drop
python build_corpus/ingest_fts_title.py --rebuild
python build_corpus/ingest_fts_combined.py --rebuild

# Phase 5: 增量更新（按需）
bash incremental/update_download.sh 2026-02-24
bash incremental/update_validate.sh 2026-02-24
bash incremental/update_merge.sh PaperData/incremental/2026-01-27_to_2026-02-24
bash incremental/update_qdrant_incremental.sh PaperData/incremental/2026-01-27_to_2026-02-24 0,2,3
```

### 启动 API 服务

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 4000
```

---

## 7. 资源估算

### 7.1 存储

| 组件 | 估算 |
|------|------|
| PaperData 原始（gz） | ~50 GB |
| papers.db（paper_metadata + corpus_id_mapping + citations + FTS5） | ~8 GB |
| qdrant_storage（仅 arXiv） | ~11 GB |
| **合计** | **~70 GB** |

### 7.2 首次构建

| Phase | 预估 | 瓶颈 |
|-------|------|------|
| 1. paper_metadata | 1–2 h | I/O + SQLite 写入 |
| 2. citations | 0.5–1.5 h | I/O + 批量 insert（已过滤） |
| 3. 向量（4 卡并行） | 0.5–1 h | BGE-M3 GPU 编码 |
| 4. FTS5 | 0.1–0.3 h | SQLite 建索引 |
| **合计** | **2–5 h** | |

### 7.3 运行时

| 资源 | 建议 | 说明 |
|------|------|------|
| 磁盘 | 70 GB（只读访问 corpus/） | |
| 内存 | 16–32 GB | BGE-M3 ~2–4 GB；SQLite 缓存；Qdrant 检索 |
| GPU | 1 张，8 GB | query embedding（sparse 模式无需 GPU） |
| CPU | 4–8 核 | HTTP + SQLite + Qdrant 查询 |

---

## 8. 增量更新

基于 S2 Datasets API 的 incremental diffs，按主键执行 upsert / delete：

| 数据集 | 主键 | 操作 |
|--------|------|------|
| papers | corpusid | upsert / delete |
| abstracts | corpusid | upsert / delete |
| paper-ids updates | corpusid | upsert |
| paper-ids deletes | sha | delete |
| citations | citationid | upsert / delete |

详见 [incremental-update.md](incremental-update.md)。

---

## 9. 项目目录结构

```
Paper_Search_API/
├── api/                             # FastAPI 路由（统一前缀 /paper）
│   ├── __init__.py
│   ├── paper.py                     # GET /paper/search
│   ├── paper_detail.py              # GET /paper/{id}
│   └── paper_citations.py           # GET /paper/{id}/citations, /references
├── core/                            # 核心逻辑
│   ├── __init__.py
│   ├── paper_id_resolver.py         # 多格式 paper_id 解析
│   ├── citation/                    # 引用查询（SQLite）
│   │   ├── __init__.py
│   │   ├── database.py              # 建表、insert、查询
│   │   └── lookup.py                # citations/references 查询接口
│   └── retrieve/                    # 检索引擎
│       ├── __init__.py
│       ├── sparse.py                # FTS5 稀疏检索（paper_fts_title、paper_fts_combined）
│       ├── dense.py                  # Qdrant 稠密向量检索
│       ├── embedding.py             # BGE-M3 编码
│       └── retriever.py              # sparse/dense/hybrid 统一入口
├── build_corpus/                    # 数据构建脚本
│   ├── ingest_paper_metadata.py     # Phase 1: paper_metadata + 映射表
│   ├── ingest_citations.py          # Phase 2: citations
│   ├── encode_embeddings.py         # Phase 3 Step 1: 编码并保存到 npz
│   ├── load_embeddings_to_qdrant.py # Phase 3 Step 2: 从 npz 加载写入 Qdrant
│   ├── ingest_fts_title.py          # Phase 4a: paper_fts_title
│   ├── ingest_fts_combined.py      # Phase 4b: paper_fts_combined
│   ├── optimize_fts.py              # FTS5 索引优化
├── incremental/                     # 增量更新流水线
│   ├── download.py                  # 下载增量 diff
│   ├── validate.py                  # 校验增量 diff
│   ├── sqlite_fts_merge.py          # SQLite + FTS 增量合并
│   ├── qdrant_manifest.py           # 生成 _qdrant_task.json
│   ├── qdrant_encode.py             # 多卡增量 embedding
│   ├── qdrant_load.py               # 写入 Qdrant
│   └── update.sh                    # 一键增量更新入口
├── corpus/                          # 运行时数据（构建后生成）
│   ├── papers.db                    # SQLite: 所有表 + FTS5
│   ├── qdrant_storage/              # Qdrant 向量存储
│   └── embeddings/                  # Phase 3 中间文件（embeddings_shard_*.npz）
├── PaperData/                       # 原始数据（S2 全量快照）
│   ├── paper-ids/
│   ├── papers/
│   ├── abstracts/
│   ├── citations/
│   └── incremental/                 # 增量 diff（按需下载）
├── docs/                            # 项目文档
│   ├── architecture.md              # 本文件
│   ├── data.md                      # 数据集结构说明
│   └── incremental-update.md        # 增量更新指南
├── archive/                         # 归档：小规模 dev 阶段内容
├── config.py                        # 全局配置
├── main.py                          # FastAPI 入口
├── schemas.py                       # Pydantic 模型 & 字段过滤
├── requirements.txt
└── .env                             # S2_API_KEY 等环境变量
```

---

## 10. API 响应格式

### /paper/search

```json
{
  "total": 42,
  "offset": 0,
  "next": 10,
  "data": [
    {
      "paperId": "83b90f4a...",
      "title": "Attention Is All You Need",
      "abstract": "...",
      "year": 2017,
      "authors": [{"authorId": "...", "name": "..."}],
      ...
    }
  ]
}
```

### /paper/{id}/citations

```json
{
  "total": 1024,
  "offset": 0,
  "next": 10,
  "data": [
    {
      "citingPaper": {
        "paperId": "...",
        "title": "..."
      }
    }
  ]
}
```

**注意**：因不存储 `contexts`、`intents`、`isInfluential`，这些字段直接省略，不返回空值。

---

## 11. FTS5 维护

布尔检索与稀疏检索依赖 `paper_fts_title`、`paper_fts_combined`。定期执行 optimize 可合并内部 b-tree 段，提升查询性能：

```bash
python build_corpus/optimize_fts.py
```

建议在批量导入后或每周执行一次。
