# 本地环境与配置

本指南适用于下载开放语料库后自部署 Lewen API。所有命令均从项目根目录执行。

## 1. 环境要求

- 建议 Python 3.10+，SQLite 需包含 FTS5。
- 完整 dense/hybrid 检索及增量向量编码使用 NVIDIA GPU 与 CUDA 版 PyTorch；当前编码器显式使用 `cuda:{GPU_DEVICE_ID}`。
- 仅使用 sparse、标题、详情、引用接口时不需要成功加载 BGE-M3 或连接 Qdrant。启动仍会尝试两者的预热，失败会记录警告；请显式选择 `retrieval=sparse`。
- 建议从单 worker、16–32 GB 内存开始，按查询长度和并发评估资源。每个 worker 独立加载 BGE-M3，增加 worker 会增加显存与内存占用。
- 下载必需语料约 35.6 GB，另有解压、备份、模型和增量数据空间，建议至少 100 GB 可用磁盘起步。使用本地 SSD 存放 SQLite 和 Qdrant。

## 2. 安装

```bash
git clone https://github.com/ustc-ai4science/Lewen-API.git
cd Lewen-API
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# 先根据本机 CUDA 环境安装适配的 PyTorch
python -m pip install -r requirements.txt
python -m pip install modelscope requests
cp .env.example .env
```

PyTorch 的安装方式以 [官方安装选择器](https://pytorch.org/get-started/locally/) 为准。`modelscope` 是下载工具，`requests` 是增量下载器直接导入的依赖。

检查环境：

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE test USING fts5(text)'); print('FTS5 ready')"
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"
```

## 3. 模型配置

下载 BGE-M3 到项目目录：

```bash
python - <<'PY'
from modelscope import snapshot_download
snapshot_download('BAAI/bge-m3', local_dir='./models/bge-m3')
PY
```

修改 `config.py`：

```python
BGE_M3_MODEL_PATH: str = str(PROJECT_ROOT / 'models' / 'bge-m3')
```

当前默认值是开发机器路径 `/data/wdy/Downloads/models/BAAI/bge-m3`，不能直接用于其他机器。**同名 `.env` 变量不会覆盖该配置。** 在线查询和增量编码都使用该路径。应使用与发布向量相同的 BGE-M3 模型，不能仅因向量维度相同就换用其他模型。

## 4. 环境变量

`config.py` 调用 `load_dotenv()` 读取 `.env`，已存在的进程环境变量优先。配置修改后需重启相应进程。

| 环境变量 | 代码默认值 | 建议 / 作用 |
| --- | --- | --- |
| `GPU_DEVICE_ID` | `1` | 单卡使用 `0`；受 `CUDA_VISIBLE_DEVICES` 的可见设备顺序影响 |
| `UVICORN_WORKERS` | `4` | 单卡先设 `1`，按显存和并发再增加 |
| `QDRANT_HOST` | `localhost` | Qdrant Server 地址 |
| `QDRANT_PORT` | `6334` | 当前代码按 gRPC 配置；HTTP 检查用 6333 |
| `QDRANT_TIMEOUT` | `300` | Qdrant 请求超时，单位秒 |
| `QDRANT_PATH` | 未设置 | 非空会切换为嵌入式模式；发布的服务端归档不使用该模式 |
| `AUTH_ENABLED` | `false` | `true` 时 `/paper/*` 需要 API Key |
| `ADMIN_SECRET` | 空 | 管理接口密钥；空值时管理接口不可用 |
| `AUTH_CACHE_TTL` | `60` | API Key 验证缓存，单位秒 |
| `ADMIN_HOST` | `0.0.0.0` | 示例文件设为 `127.0.0.1`，只允许本机访问看板 |
| `ADMIN_PORT` | `4100` | 独立管理员服务端口 |
| `ADMIN_TARGET_API_BASE_URL` | `http://localhost:4000` | 管理员看板测试 / 检查的 API 地址 |
| `S2_API_KEY` | 空 | S2 增量下载需要的 Datasets API 凭证 |
| `REQUEST_TIMEOUT` | `30` | API 请求超时，单位秒 |
| `HEAVY_OPS_MAX_CONCURRENT` | `100` | 重操作线程池并发上限 |

批处理参数 `EMBEDDING_BATCH_SIZE`、`DENSE_SEARCH_BATCH_SIZE`、`FTS5_SEARCH_BATCH_SIZE` 默认均为 32，对应 `*_BATCH_TIMEOUT_MS` 默认均为 50 ms。先使用默认值，调优方法见 [性能记录](performance-lessons.md)。

以下设置在当前代码中为固定配置，**需修改 `config.py`，不能只写到 `.env`**：

| 配置 | 当前值 |
| --- | --- |
| `BGE_M3_MODEL_PATH` | 开发机器模型路径，必须按本机修改 |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `4000` |
| `QDRANT_COLLECTION_NAME` / `VECTOR_DIM` | `papers` / `1024` |
| `CORPUS_DIR` / `PAPER_DATA_DIR` | 项目根目录下 `corpus/` / `PaperData/` |

## 5. 下一步与排错

1. 按 [语料库指南](data.md) 下载并安装 SQLite 与 Qdrant 数据。
2. 按 [部署指南](deployment.md) 启动 Qdrant 和 API。
3. 按 [增量更新指南](incremental-update.md) 更新已有语料。

| 现象 | 检查项 |
| --- | --- |
| 找不到 `papers.db` | 是否存在 `corpus/papers.db`，是否下载成了 Git LFS 指针 |
| `no such module: fts5` | 当前 Python 使用的 SQLite 是否包含 FTS5 |
| `invalid device ordinal` | 单卡设置 `GPU_DEVICE_ID=0`；核对可见 GPU 编号 |
| BGE-M3 预热失败 | `config.py` 模型路径、模型文件、CUDA 可用性与显存 |
| Qdrant 连接失败 | 是否启动服务、6334 是否可达、是否误设 `QDRANT_PATH` |
| 稀疏查询正常，默认搜索失败 | 默认是 hybrid；进一步检查模型和 `papers` 集合 |
| 增量脚本在 GPU 2/3 报错 | 一键入口默认 `0,2,3`；单卡改用显式传 `0` 的分步流程 |
