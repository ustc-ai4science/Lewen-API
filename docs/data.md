# 语料库下载与数据结构

Lewen 的运行语料独立开放在 **[ModelScope：flappybear80/lewen-corpus](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus)**。本仓库提供服务代码与增量更新脚本，首次部署直接下载已构建数据，无需先获取 S2 全量原始快照。

## 1. 范围与版本

语料由 Semantic Scholar 的论文元数据、摘要、ID 映射和引用数据整理而来，当前服务范围是具有摘要的 arXiv 论文。引用边仅保留两端均属于语料的记录。历史论文规模约 300 万篇；实际数量与 `corpus/current_release.txt` 对应的数据版本有关。

本次核对的发布 release 标记为 `2026-03-10`，后续下载应始终以发布文件为准，不要在首次安装时自行填写今天的日期或历史基线日期。该标记是 S2 数据 release，区别于 ModelScope 仓库的 Git revision。

数据包括摘要与论文元数据，不是 PDF 正文语料。数据许可、论文权利与项目代码许可分别适用；请查阅数据集页面及上游数据使用条件。

## 2. 发布文件

| 文件 | 约大小（十进制） | 部署用途 |
| --- | --- | --- |
| `papers.db` | 20.4 GB | 必需：SQLite 元数据、引用关系、ID 映射与两个 FTS5 索引 |
| `current_release.txt` | 11 B | 必需：当前 S2 release，增量下载以此为起点 |
| `qdrant_storage.tar.gz` | 15.2 GB | dense/hybrid 必需：Qdrant Server 存储归档 |
| `embeddings.tar.gz` | 6.5 GB | 可选：预计算向量中间产物；正常恢复 Qdrant 后无需下载 |
| `auth.db` | 16 KB | 不用于新部署；每个部署创建自己的 API Key 数据库 |
| `papers.db-wal`、`papers.db-shm` | 发布时附件 | SQLite WAL / 共享内存文件，见下文 |

尺寸来自当前发布文件元信息，不是解压后的运行空间。必需下载约 35.6 GB，请为解压、模型、备份和更新额外预留磁盘。

## 3. 下载

推荐 ModelScope SDK 选择所需文件，下载到暂存目录：

```bash
python -m pip install modelscope
python - <<'PY'
from modelscope.hub.snapshot_download import dataset_snapshot_download

dataset_snapshot_download(
    dataset_id='flappybear80/lewen-corpus',
    revision='master',
    local_dir='./downloads/lewen-corpus',
    allow_file_pattern=[
        'papers.db', 'current_release.txt', 'qdrant_storage.tar.gz',
    ],
)
PY
```

只使用 SQLite 接口时，可从列表移除 `qdrant_storage.tar.gz`。需要中间向量产物时，另行加入 `embeddings.tar.gz`。不要使用全量下载结果中的 `auth.db` 初始化自己的服务。

也可以在数据集的“数据集文件”页面手动下载相同文件。大文件使用 Git LFS，普通 `git clone` 未安装 LFS 时得到的可能只是指针文件；不能把指针当作数据库或压缩包。

SDK 参数依据 [ModelScope 下载实现](https://github.com/modelscope/modelscope/blob/master/modelscope/hub/snapshot_download.py)。需要可复现部署时，记录下载 revision 和文件 SHA-256，并使用数据集页面公布的 SHA-256 核对本地文件：

```bash
# Linux
sha256sum downloads/lewen-corpus/papers.db downloads/lewen-corpus/qdrant_storage.tar.gz
# macOS
shasum -a 256 downloads/lewen-corpus/papers.db downloads/lewen-corpus/qdrant_storage.tar.gz
```

### SQLite WAL 注意事项

本次核对的 `papers.db-wal` 大小为 0，所以上述首次安装命令仅取 `papers.db`。若未来发布的 WAL 非空，必须确认发布者已提供同一一致性快照的数据库与 WAL，或已完成 checkpoint 的独立数据库；不能丢弃非空 WAL。`-shm` 是运行时共享内存文件，关闭连接后可重建，不作为可移植语料安装文件。

不要在服务运行时覆盖 SQLite 文件或混入其他版本的 WAL/SHM。替换已有语料时，先暂停 API、管理员更新任务及 Qdrant，再备份完整旧数据，在新的空目录准备匹配版本的 SQLite、Qdrant 与 release 文件，验收后切换；保留自己的 `auth.db`。

## 4. 安装与检查

以下命令仅用于没有旧运行数据的首次部署，执行时 API 与 Qdrant 应处于停止状态：

```bash
mkdir -p corpus
cp downloads/lewen-corpus/papers.db corpus/papers.db
cp downloads/lewen-corpus/current_release.txt corpus/current_release.txt
tar -tzf downloads/lewen-corpus/qdrant_storage.tar.gz | head -20
tar -xzf downloads/lewen-corpus/qdrant_storage.tar.gz -C corpus
cat corpus/current_release.txt
```

当前归档含顶层 `qdrant_storage/`，解压后的路径应为：

```text
corpus/
├── papers.db
├── current_release.txt
├── qdrant_storage/
│   └── collections/
│       └── papers/       # 必须验收此集合；归档可能还包含其他集合
└── auth.db              # 本部署生成，不从开放语料复制
```

检查 SQLite 完整性和表结构（大库检查可能耗时）：

```bash
python - <<'PY'
import sqlite3
with sqlite3.connect('file:corpus/papers.db?mode=ro', uri=True) as db:
    print('integrity:', db.execute('PRAGMA quick_check').fetchall())
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    required = {'paper_metadata', 'citations', 'corpus_id_mapping',
                'arxiv_to_paper', 'paper_fts_title', 'paper_fts_combined'}
    print('missing tables:', sorted(required - names))
    print('sample:', db.execute('SELECT paper_id, title FROM paper_metadata LIMIT 1').fetchone())
PY
```

启动 Qdrant 后还要检查 `GET http://localhost:6333/collections/papers`，确认 `papers` 存在、向量维度为 1024，并进行实际 hybrid 搜索。归档前部可见其他 collection，不能因此判断论文集合已经正确恢复。当前数据集卡片未说明构建 Qdrant 的确切版本，需在恢复时核对服务端日志与存储兼容性。

## 5. SQLite 逻辑结构

| 表 | 作用 | 主要字段 |
| --- | --- | --- |
| `paper_metadata` | 论文元数据与摘要 | `paper_id`、`corpus_id`、`title`、`abstract`、`year`、`authors_json`、`external_ids_json` 等 |
| `corpus_id_mapping` | S2 Corpus ID → SHA | `corpus_id`、`paper_id` |
| `arxiv_to_paper` | arXiv ID → SHA | `arxiv_id`、`paper_id` |
| `citations` | 有向引用边 | `citation_id`、`citing_corpus_id`、`cited_corpus_id` |
| `paper_fts_title` | 标题 BM25 检索 | `paper_id`、`title` |
| `paper_fts_combined` | 标题与摘要 BM25 检索 | `paper_id`、`title_abstract` |

`paper_id` 为 Semantic Scholar 的 SHA 标识；`corpus_id` 为整数 Corpus ID。元数据字段在 API 层转换为 `paperId`、`citationCount`、`externalIds` 等响应字段，详见 [API 参考](api-zh.md)。引用表不保存 contexts、intents 或 isInfluential，不能从该发布库还原这些字段。

Qdrant 的 `papers` 集合使用 1024 维 Cosine 向量，文本为 `title + abstract`，payload 包含 `paper_id`；其余元数据回查 SQLite。

## 6. S2 原始数据与增量文件

原始 S2 数据和本项目运行数据是不同层次：

| S2 数据集 | 内容 | 当前增量处理 |
| --- | --- | --- |
| `paper-ids` | Corpus ID 与 SHA 映射 | 更新映射、处理删除 |
| `papers` | 标题、作者、年份、外部 ID 等 | 更新元数据 |
| `abstracts` | 摘要与开放获取信息 | 更新摘要与语料成员 |
| `citations` | 引用方与被引方 Corpus ID | 更新语料内部引用边 |
| `authors` | 作者档案 | 下载，但不参与当前 SQLite/FTS/Qdrant 合并 |

增量文件为压缩 JSON Lines 等格式，保存在 `PaperData/incremental/{start}_to_{end}/`。首次部署无需下载原始全量 `PaperData`；日常更新参见 [增量更新指南](incremental-update.md)。历史文档中的 `build_corpus/` 未随本仓库发布，不作为部署步骤。
