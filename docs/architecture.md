# 技术架构与项目结构

## 1. 定位与数据边界

Lewen 是学术论文检索与查询后端。服务从本地发布语料读取论文元数据、摘要、ID 映射和语料内部引用边，为上层应用提供 REST API。当前语料成员为具有摘要的 arXiv 论文，不是 Semantic Scholar 全站数据，也不包含 PDF 正文。

首次部署从 [ModelScope](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus) 获取已经构建的 SQLite 与 Qdrant 数据；`corpus/current_release.txt` 标识本地数据的 S2 release。历史全量构建脚本 `build_corpus/` 不随本仓库发布，不能作为安装前提。

## 2. 请求路径

```text
HTTP request
  → FastAPI 路由 + 可选 API Key 认证
  → 论文 ID 解析 / Retriever / 引用查询
      ├─ sparse / title → FTS5 batcher → SQLite BM25
      ├─ dense → BGE-M3 embedding batcher → Qdrant
      └─ hybrid → sparse + dense → RRF 融合
  → SQLite 元数据回查与过滤
  → 字段筛选、分页、JSON response
```

| 组件 | 职责 |
| --- | --- |
| FastAPI + Uvicorn | 异步 HTTP、OpenAPI、worker 进程管理 |
| SQLite + 数据库池 | 元数据、ID 映射、引用关系查询 |
| FTS5 | `paper_fts_title` 与 `paper_fts_combined` 的 BM25 检索 |
| BGE-M3 | 查询与增量论文编码，1024 维 dense vector，当前使用 CUDA |
| Qdrant Server | `papers` collection，Cosine 检索，payload 为 `paper_id` |
| 批处理队列 | 合并编码与检索请求，降低单请求调度开销 |
| RRF | 融合 sparse / dense 排名 |

`retrieval=hybrid` 为默认模式。`sparse` 不执行查询编码，但启动过程仍会尝试预热模型与 Qdrant。预热失败被记录后不一定阻止 API 启动，部署时必须用实际 hybrid 请求验收。

## 3. 存储模型

所有关系数据与 FTS5 索引位于 `corpus/papers.db`：

| 表 | 作用 |
| --- | --- |
| `paper_metadata` | `paper_id`（SHA）、`corpus_id`、标题、摘要、年份及 JSON 元数据字段 |
| `corpus_id_mapping` | S2 Corpus ID → SHA |
| `arxiv_to_paper` | arXiv ID → SHA |
| `citations` | `citation_id`、`citing_corpus_id`、`cited_corpus_id` |
| `paper_fts_title` | 标题索引 |
| `paper_fts_combined` | `title + abstract` 索引 |

Qdrant 使用 `corpus/qdrant_storage/` 服务端存储目录。论文向量文本同样为 `title + abstract`，只将论文标识写入 payload，其余信息回查 SQLite。发布包可能含其他 collection，服务仅使用 `papers`，其维度与模型必须匹配。

鉴权数据保存在本部署生成的 `corpus/auth.db`，与开放论文语料分开。详情字段与数据结构参见 [语料库指南](data.md)。

## 4. ID 解析与响应

`core/paper_id_resolver.py` 将不同格式解析为 SHA：

| 输入 | 示例 |
| --- | --- |
| SHA | 40 位十六进制论文标识 |
| arXiv ID | `2309.06180`、`2309.06180v1` |
| Corpus ID | `215416146`、`CorpusId:215416146` |
| arXiv URL | `https://arxiv.org/abs/2309.06180` |

响应的分页字段为 `total`、`offset`、`next` 和 `data`。检索的 `total` 是候选集经过过滤后的数量，不是对全部语料的精确命中计数。引用返回 `citingPaper`，参考文献返回 `citedPaper`；当前数据库不保留 contexts、intents、isInfluential。具体接口契约见 [API 参考](api-zh.md)。

## 5. 增量链路

```text
S2 Datasets API diffs
  → download.py：下载 / 续传
  → validate.py：文件完整性校验 / 重下
  → sqlite_fts_merge.py：SQLite + FTS5 upsert / delete
      → _qdrant_task.json
  → qdrant_encode.py：按分片进行 BGE-M3 编码
      → qdrant_embeddings/*.npz
  → qdrant_load.py：Qdrant delete / upsert
  → update_qdrant_incremental.sh：推进 current_release.txt
```

SQLite 合并进度与 Qdrant 任务独立维护。更新不是跨 SQLite 与 Qdrant 的原子事务，只有所有编码分片与入库均完成后才能声明新版本。手动入库不会自动写 release 标记。详见 [增量更新指南](incremental-update.md)。

## 6. 项目目录

```text
Lewen-API/
├── api/                 # 论文与管理路由、看板
├── auth/                # Key 数据库、Key 管理、认证中间件
├── core/
│   ├── retrieve/        # 编码、FTS5、Qdrant、RRF 与批处理队列
│   ├── citation/        # 引用关系查询
│   ├── db_pool.py       # SQLite 连接池
│   ├── paper_id_resolver.py
│   └── admin_jobs.py    # 管理后台任务
├── incremental/         # 下载、校验、合并、编码、入库脚本
├── config/qdrant_config.yaml
├── docs/                # MkDocs 源文档
├── test/                # 接口测试、压测与增量测试
├── corpus/              # 运行数据，不入 Git
├── PaperData/           # 增量原始文件，不入 Git
├── config.py
├── .env.example
├── main.py
├── admin_main.py
├── manage_keys.py
└── start_*.sh
```

## 7. 部署约束

- CUDA / BGE-M3 只服务于 dense/hybrid 与增量编码；CPU 环境可先验证 SQLite 查询。
- 每个 Uvicorn worker 独立加载模型，先从单 worker 起步。
- Qdrant Server 目录归档不能直接作为嵌入式 `QDRANT_PATH` 数据库。
- 端口监听成功不代表模型、集合和索引已通过验收。
- 资源估算应依据实际发布包与并发；旧全量原始快照的大小和建库耗时不作为当前部署承诺。

部署方式与检查命令见 [本地配置](setup.md) 和 [API 部署](deployment.md)。
