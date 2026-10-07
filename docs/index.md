# 乐问学术搜索 API

Lewen 是可自部署的学术论文检索后端，为文献检索、论文问答、综述辅助与科研 Agent 提供统一 REST API。项目开放服务代码和独立发布的运行语料，支持本地查询与持续增量更新。

**[开放语料库 · ModelScope](https://www.modelscope.cn/datasets/flappybear80/lewen-corpus)** · **[源码 · GitHub](https://github.com/ustc-ai4science/Lewen-API)**

## 项目范围

当前语料面向具有摘要的 arXiv 论文，历史规模约 300 万篇，实际规模随 release 变化。支持论文元数据、摘要及语料内部引用关系，不托管 PDF 全文。API 提供检索与查询能力，可接入上层应用；问答和生成逻辑由应用自行实现。

| 能力 | 端点 | 说明 |
| --- | --- | --- |
| 论文检索 | `GET /paper/search` | BM25 稀疏检索、BGE-M3 稠密检索和 RRF 混合检索 |
| 标题检索 | `GET /paper/search/title` | 标题 FTS5 匹配 |
| 论文详情 | `GET /paper/{paper_id}` | SHA / arXiv ID / Corpus ID / arXiv URL |
| 被引论文 | `GET /paper/{paper_id}/citations` | 引用该论文的语料内论文 |
| 参考文献 | `GET /paper/{paper_id}/references` | 该论文引用的语料内论文 |

## 自部署路线

1. [本地配置](setup.md)：安装 Python、CUDA/PyTorch 与项目依赖，配置 BGE-M3 和环境变量。
2. [语料库下载](data.md)：从 ModelScope 获取 `papers.db`、release 标记和 Qdrant 存储包。
3. [API 部署](deployment.md)：启动 Qdrant、API 与可选管理员服务，验证检索并配置鉴权。
4. [增量更新](incremental-update.md)：从 S2 下载 diffs，依次更新 SQLite、FTS5 和向量索引。

首次部署不需要重新构建全量语料。本仓库未发布历史 `build_corpus/` 脚本，直接使用开放语料即可。

## 调用示例

完成部署后，本地默认 API 地址为 `http://localhost:4000`，交互文档为 `http://localhost:4000/docs`：

```bash
# 稀疏检索用于先验证本地 SQLite
curl --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' \
  --data-urlencode 'retrieval=sparse' --data-urlencode 'limit=5'

# 默认 hybrid 检索需要模型与 Qdrant 均可用
curl --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' --data-urlencode 'limit=5'

curl 'http://localhost:4000/paper/2309.06180?fields=*'
```

启用 `AUTH_ENABLED=true` 后，`/paper/*` 需添加 `X-API-Key` 请求头。完整参数、字段和响应见 [中文 API 参考](api-zh.md) 与 [English API reference](api-en.md)。文档站点本身是静态说明页面，不是 API 请求地址。

## 系统组成

| 层次 | 实现 |
| --- | --- |
| HTTP API | FastAPI + Uvicorn |
| 元数据与引用关系 | SQLite |
| 稀疏检索 | SQLite FTS5 / BM25 |
| 稠密检索 | BGE-M3（1024 维）+ Qdrant |
| 混合排序 | Reciprocal Rank Fusion（RRF） |
| 管理与维护 | API Key、独立管理员看板、五阶段增量更新 |

进一步阅读 [技术架构](architecture.md)、[管理员指南](api-key-admin.md) 和 [性能记录](performance-lessons.md)。文档正式地址为 **[ustc-ai4science.github.io/Lewen-API](https://ustc-ai4science.github.io/Lewen-API/)**。
