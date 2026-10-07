# Lewen API · 乐问学术搜索

面向学术应用与研究工具的可自部署论文检索后端。Lewen 将论文元数据、摘要、全文检索索引和引用关系保存在本地，通过统一 REST API 提供论文发现与查询能力，可作为文献检索、论文问答、综述辅助和科研 Agent 的检索基础设施。

**[完整文档](https://ustc-ai4science.github.io/Lewen-API/)** · **[开放语料库（ModelScope）](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus)** · **[API 参考](https://ustc-ai4science.github.io/Lewen-API/api-zh/)**

## 项目定位与能力

本仓库提供 API 服务、检索实现、API Key 管理和增量更新流水线；运行所需的数据通过 ModelScope 独立发布，无需从 Semantic Scholar 全量原始数据重新建库。

当前语料范围为 **具有摘要的 arXiv 论文**，历史规模约 300 万篇，实际数量随 release 变化。引用查询保留语料内论文之间的引用边，不代表 Semantic Scholar 全站引用图。本项目不提供论文 PDF 全文托管，也不包含问答或文本生成模型。

| 能力 | 接口 | 实现 |
| --- | --- | --- |
| 论文搜索 | `GET /paper/search` | `sparse`：SQLite FTS5 / BM25；`dense`：BGE-M3 + Qdrant；`hybrid`（默认）：RRF 融合 |
| 标题检索 | `GET /paper/search/title` | 标题 FTS5 匹配 |
| 论文详情 | `GET /paper/{paper_id}` | 支持 SHA、arXiv ID、Corpus ID 和 arXiv URL |
| 被引论文列表 | `GET /paper/{paper_id}/citations` | 查询引用该论文的语料内论文 |
| 参考文献列表 | `GET /paper/{paper_id}/references` | 查询该论文引用的语料内论文 |
| 服务管理 | 独立管理员服务 | API Key、状态查看、压测与增量更新任务 |

服务端采用 FastAPI + Uvicorn，SQLite 存储关系数据与 FTS5 索引，Qdrant 存储 1024 维 BGE-M3 向量。常规本地查询使用已下载语料；从 Semantic Scholar 获取增量数据时才需要访问其 Datasets API。

## 1. 本地环境与配置

完整检索与增量编码建议使用 **Linux + NVIDIA GPU + CUDA 版 PyTorch**。可从 1 张 GPU、16–32 GB 内存开始评估，内存和显存需求取决于 worker 数、查询长度与并发。无 CUDA 的机器可以先使用 SQLite 支持的稀疏检索、标题和详情查询；当前编码器固定使用 CUDA，不支持通过配置直接切换 CPU/MPS。

```bash
git clone https://github.com/ustc-ai4science/Lewen-API.git
cd Lewen-API
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# 按本机 CUDA 环境安装适配的 PyTorch，再安装项目依赖
python -m pip install -r requirements.txt
python -m pip install modelscope requests
cp .env.example .env
```

`modelscope` 用于下载语料和模型，`requests` 是增量下载脚本使用的依赖。Python 建议 3.10+，SQLite 必须支持 FTS5：

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE test USING fts5(text)'); print('FTS5 ready')"
python -c "import torch; print('CUDA available:', torch.cuda.is_available(), 'GPUs:', torch.cuda.device_count())"
```

`.env.example` 提供单卡起步配置，主要设置如下：

| 设置 | 用途 |
| --- | --- |
| `GPU_DEVICE_ID=0` | 在线查询编码使用的可见 CUDA 设备编号；代码默认是 `1` |
| `UVICORN_WORKERS=1` | 先用一个 worker，每个 worker 都会加载自己的模型 |
| `QDRANT_HOST=localhost`、`QDRANT_PORT=6334` | Qdrant 服务地址与 gRPC 端口；HTTP 检查端口是 `6333` |
| `AUTH_ENABLED=false` | 本地试用无需 API Key；对外服务应启用 |
| `ADMIN_SECRET` | 管理接口密钥，与普通用户 API Key 分开 |
| `S2_API_KEY` | Semantic Scholar Datasets API 密钥；仅增量更新需要 |

**模型路径需要修改 `config.py` 中的 `BGE_M3_MODEL_PATH`。** 当前它是开发机器的绝对路径，不读取同名环境变量。API 默认监听 `0.0.0.0:4000`，监听地址与端口也在 `config.py` 中设置。

下载 BGE-M3（稠密 / 混合检索、增量向量编码需要）：

```bash
python - <<'PY'
from modelscope import snapshot_download
snapshot_download('BAAI/bge-m3', local_dir='./models/bge-m3')
PY
```

将 `config.py` 中对应配置改为：

```python
BGE_M3_MODEL_PATH: str = str(PROJECT_ROOT / 'models' / 'bge-m3')
```

## 2. 下载语料库

语料已开放在 **[flappybear80/lewen-corpus](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus)**。Git 仓库不包含大体积数据，首次部署需另行下载。

| 发布文件 | 用途 | 大小（约，十进制） |
| --- | --- | --- |
| `papers.db` | 元数据、ID 映射、引用关系、FTS5 索引 | 20.4 GB |
| `current_release.txt` | 当前数据对应的 S2 release | 11 B |
| `qdrant_storage.tar.gz` | Qdrant 服务端存储归档 | 15.2 GB |
| `embeddings.tar.gz` | 预计算向量中间产物；已有 Qdrant 存储时无需下载 | 6.5 GB |

以上为当前发布文件的近似大小；压缩包还需解压空间，建议先准备 **至少 100 GB 可用磁盘**，并为增量文件、备份和模型额外预留空间。完整部署必需文件下载量约 35.6 GB；只试用 SQLite 接口可以先仅下载前两个文件。

在项目根目录执行以下命令，将下载文件放到独立暂存目录，避免覆盖正在使用的数据：

```bash
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

以下安装步骤用于**首次部署**，请在 API 与 Qdrant 均未运行、目标 `corpus/` 没有旧数据时执行：

```bash
mkdir -p corpus
cp downloads/lewen-corpus/papers.db corpus/papers.db
cp downloads/lewen-corpus/current_release.txt corpus/current_release.txt
# 先检查归档结构；目标目录应为 corpus/qdrant_storage/
tar -tzf downloads/lewen-corpus/qdrant_storage.tar.gz | head -20
tar -xzf downloads/lewen-corpus/qdrant_storage.tar.gz -C corpus
cat corpus/current_release.txt
```

发布包包含顶层 `qdrant_storage/` 目录。不要额外创建同名嵌套目录。数据集中的 `auth.db` 属于鉴权状态，部署时不下载或复用；本地首次启动 / 创建 Key 时会生成自己的鉴权数据库。SQLite 发布时的 WAL/SHM 附件、文件校验及替换已有数据的注意事项见 [语料库指南](docs/data.md)。

## 3. 部署 API

### 启动 Qdrant

稠密 / 混合检索需要独立 Qdrant Server。安装与你的操作系统、CPU 架构及发布存储格式兼容的 [Qdrant 二进制](https://github.com/qdrant/qdrant/releases)，放在仓库根目录并命名为 `qdrant`，或加入 `PATH`：

```bash
chmod +x qdrant
bash start_qdrant.sh
```

脚本读取 `config/qdrant_config.yaml`，使用 `corpus/qdrant_storage/`，开放 HTTP `6333` 和 gRPC `6334`。在另一个终端检查：

```bash
curl --fail http://localhost:6333/collections/papers
```

应能查到 `papers` collection，向量维度为 **1024**。存储包可能含其他 collection，其他集合不能替代 `papers`。若集合不存在、维度不符或存储版本不兼容，先核对发布数据和 Qdrant 版本，不能仅凭进程启动判断恢复成功。服务端存储归档也不应直接当作 `QDRANT_PATH` 的嵌入式客户端目录。

### 启动服务并验证

在另一个已激活虚拟环境的终端中运行：

```bash
bash start_api.sh
```

访问本地 OpenAPI 文档：**http://localhost:4000/docs**。测试请求：

```bash
# 稀疏检索：可先验证 SQLite 数据，不依赖 CUDA / Qdrant
curl --fail --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' \
  --data-urlencode 'retrieval=sparse' --data-urlencode 'limit=5'

# 默认 hybrid：需要 BGE-M3 和 Qdrant 都正常
curl --fail --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' --data-urlencode 'limit=5'

curl --fail 'http://localhost:4000/paper/2309.06180?fields=*'
curl --fail 'http://localhost:4000/paper/1706.03762/citations?limit=10'
```

启动时会尝试预热 BGE-M3 和 Qdrant；预热失败可能仍允许服务启动，请同时检查 `logs/api.log` 和实际 hybrid 请求。无 GPU 试用时务必显式传入 `retrieval=sparse`。

### 鉴权与长期运行

对外部署前，在 `.env` 中设置 `AUTH_ENABLED=true` 和随机生成的 `ADMIN_SECRET`，创建用户 Key 后重启 API：

```bash
python manage_keys.py create --name 'local-user' --email 'user@example.com'
curl -H 'X-API-Key: lw-替换为创建时返回的Key' \
  'http://localhost:4000/paper/search?query=transformer&retrieval=sparse'
```

可选管理员看板单独启动：

```bash
bash start_admin.sh
# http://localhost:4100/admin/panel
```

长期运行可使用 systemd 管理 API 与 Qdrant，并由 Nginx 等反向代理提供 HTTPS；Qdrant 和管理员接口限制为本机或可信网络访问。完整配置与启动、重启、验收步骤见 [部署指南](docs/deployment.md) 和 [管理员指南](docs/api-key-admin.md)。

## 4. 更新语料库

“下载发布快照”和“从 S2 拉取增量”是两种不同方式。首次部署使用 ModelScope 快照即可；已有部署可保留本地数据，通过 `incremental/` 更新元数据、FTS5 与向量索引。

增量更新前需配置 `.env` 中的 `S2_API_KEY`、确认 `corpus/current_release.txt` 与本地数据一致、启动 Qdrant，并准备 CUDA GPU 和 BGE-M3。先备份 SQLite、Qdrant 和 release 标记；更新会分阶段写入数据，严格一致性场景应在维护窗口暂停 API 查询。

**单卡推荐分步执行**。在同一个 Bash 会话中运行，并将 `TARGET` 改为 S2 实际可用的目标 release：

```bash
bash
TARGET=2026-04-07  # 示例日期，请替换；必须晚于当前 release
START=$(tr -d '[:space:]' < corpus/current_release.txt)

bash incremental/update_download.sh "$TARGET"
# 查看下载输出中的 END_RELEASE 与 INCR_DIR，后续使用实际解析出的值
```

接着按下载输出设置变量（目标日期可能解析为不晚于该日期的最近 release）：

```bash
END_RELEASE=2026-04-07  # 替换为下载输出的 END_RELEASE
INCR_DIR="PaperData/incremental/${START}_to_${END_RELEASE}"
bash incremental/update_validate.sh "$END_RELEASE"
bash incremental/update_merge.sh "$INCR_DIR"
bash incremental/update_qdrant_incremental.sh "$INCR_DIR" 0
cat corpus/current_release.txt
```

最后一个脚本在增量编码与入库成功后推进 release 标记。不要在仅完成 SQLite/FTS 合并后手动推进版本。默认一键入口 `bash incremental/update.sh latest` 使用 **GPU `0,2,3`**，只适合这些 GPU 都可用的机器；单卡机器使用上述显式指定 GPU `0` 的流程。

下载断点、校验、任务状态、重试和完整性核对见 [增量更新指南](docs/incremental-update.md)。本仓库不包含全量 `build_corpus/` 脚本，部署无需运行历史建库命令。

## 文档与项目结构

- [本地配置](docs/setup.md)：环境、模型、配置项与常见问题。
- [语料库下载](docs/data.md)：发布文件、落盘结构、校验与数据模型。
- [API 部署](docs/deployment.md)：Qdrant、进程管理、鉴权与验收。
- [增量更新](docs/incremental-update.md)：分阶段执行与失败恢复。
- [技术架构](docs/architecture.md)、[中文 API](docs/api-zh.md)、[English API](docs/api-en.md)。

```text
Lewen-API/
├── api/              # 搜索、详情、引用及管理路由
├── auth/             # API Key 存储与认证
├── core/             # 检索、引用查询、数据库池与管理任务
├── incremental/      # S2 增量下载、校验、合并、编码、入库
├── config/           # Qdrant 服务配置
├── docs/             # MkDocs 文档源文件
├── corpus/           # 下载 / 解压后的运行数据（不入 Git）
├── PaperData/         # 增量原始数据（运行后生成，不入 Git）
├── config.py         # 全局配置
├── .env.example      # 可复制的环境变量示例
├── main.py           # Paper API 入口
└── admin_main.py     # 独立管理员服务入口
```

文档本地预览与构建：

```bash
mkdocs serve
mkdocs build --strict
```

文档由 GitHub Actions 在 `main` 分支的 `docs/` 或 `mkdocs.yml` 更新后发布到 **https://ustc-ai4science.github.io/Lewen-API/**。

## 许可与数据来源

项目代码许可声明为 MIT。语料库许可与代码许可分开，具体以 [ModelScope 数据集页面](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus) 的发布声明及上游数据条件为准；论文元数据和摘要来自 Semantic Scholar，论文内容的权利归原权利人所有。
