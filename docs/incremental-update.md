# 增量更新指南

本文档说明当前项目如何通过新的 `incremental/` 目录执行增量更新。  
现在的设计原则是：

- 下载、校验、SQLite/FTS、Qdrant 编码、Qdrant 入库彻底拆开
- `_merge_progress.json` 只属于 SQLite/FTS merge
- Qdrant 使用独立的 `_qdrant_task.json`
- 根目录旧增量脚本已移除，统一使用 `incremental/` 下的新入口

---

## 1. 执行方式

```bash
# 一键执行：下载 -> 校验 -> SQLite/FTS -> Qdrant 任务 -> Qdrant 入库
bash incremental/update.sh

# 指定目标 release
bash incremental/update.sh 2026-03-10

# 分步执行（五段）
bash incremental/update_download.sh 2026-03-10
bash incremental/update_validate.sh 2026-03-10
bash incremental/update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10
python incremental/qdrant_encode.py PaperData/incremental/2026-01-27_to_2026-03-10 --gpu 0 --shard 0 --total-shards 3
python incremental/qdrant_load.py PaperData/incremental/2026-01-27_to_2026-03-10
```

推荐顺序：

1. 网络不稳定时先执行 `incremental/update_download.sh`
2. 文件下完后执行 `incremental/update_validate.sh`
3. 执行 `incremental/update_merge.sh` 完成 SQLite + FTS，并生成 `_qdrant_task.json`
4. 执行 `incremental/qdrant_encode.py` 完成多卡 embedding 编码
5. 执行 `incremental/qdrant_load.py` 将 embedding 写入 Qdrant

### 前置条件

- `corpus/current_release.txt` 存在且包含当前 release 日期
- `.env` 中配置了 `S2_API_KEY`
- Qdrant 服务运行中
- 至少一张可用 GPU；多卡编码时可传入例如 `0,2,3`

---

## 2. 五段职责

### 2.1 下载

入口：

```bash
bash incremental/update_download.sh 2026-03-10
python incremental/download.py --start 2026-01-27 --end 2026-03-10
```

职责：

- 调用 S2 incremental diffs API
- 在 `PaperData/incremental/{start}_to_{end}/` 下创建增量目录
- 文件存在即跳过
- 如果存在 `.tmp` 文件，则继续断点续传
- 不做完整 gzip/UTF-8 校验

### 2.2 校验

入口：

```bash
bash incremental/update_validate.sh 2026-03-10
python incremental/validate.py --start 2026-01-27 --end 2026-03-10
```

职责：

- 完整校验 `.gz/.jsonl`
- 对缺失或损坏文件重新下载
- 维护 `INCR_DIR/_download_validation_progress.json`

### 2.3 SQLite + FTS

入口：

```bash
bash incremental/update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10
python incremental/sqlite_fts_merge.py PaperData/incremental/2026-01-27_to_2026-03-10
```

职责：

- 处理 `paper-ids` / `papers` / `abstracts` / `citations`
- 写 SQLite
- 刷新 FTS5
- 维护 `INCR_DIR/_merge_progress.json`
- 完成后生成 `INCR_DIR/_qdrant_task.json`
- 不直接执行 Qdrant
- 不更新 `corpus/current_release.txt`

### 2.4 Qdrant embedding

入口：

```bash
python incremental/qdrant_manifest.py PaperData/incremental/2026-01-27_to_2026-03-10
python incremental/qdrant_encode.py PaperData/incremental/2026-01-27_to_2026-03-10 --gpu 0 --shard 0 --total-shards 3
```

职责：

- 读取 `_qdrant_task.json`
- 严格按当前 `arxiv_to_paper` 过滤
- 多卡并行编码增量向量
- 输出到：
  - `INCR_DIR/qdrant_embeddings/incremental_embeddings_shard_{i}.npz`

### 2.5 Qdrant load

入口：

```bash
python incremental/qdrant_load.py PaperData/incremental/2026-01-27_to_2026-03-10
```

职责：

- 只读取 `_qdrant_task.json`
- 先做 delete，再 upsert embedding shard
- 成功后把 `_qdrant_task.json` 标记为 loaded
- 如果 embedding 已经算完，可以单独重复执行这一阶段
- 由 `incremental/update_qdrant_incremental.sh` 在整条链成功后更新 `corpus/current_release.txt`

---

## 3. 关键状态文件

### `_download_validation_progress.json`

位置：

- `PaperData/incremental/.../_download_validation_progress.json`

作用：

- 仅供校验阶段使用
- 记录哪些 diff 文件已经完整校验通过

### `_merge_progress.json`

位置：

- `PaperData/incremental/.../_merge_progress.json`

作用：

- 仅供 SQLite/FTS merge 使用
- 只记录：
  - `completed_steps`
  - `step_offsets`
- 不再包含任何 Qdrant 待办集合

### `_qdrant_task.json`

位置：

- `PaperData/incremental/.../_qdrant_task.json`

作用：

- 供 Qdrant 流水线使用
- 记录：
  - `upsert_corpus_ids`
  - `delete_paper_ids`
  - `task_status`
  - `summary`

### `corpus/current_release.txt`

位置：

- `corpus/current_release.txt`

作用：

- 表示当前系统对外声明的 corpus release 版本
- 下载阶段会把它作为 `start_release`
- 后续增量目录命名也依赖它，例如：
  - `PaperData/incremental/2026-01-27_to_2026-03-10`

维护规则：

- `incremental/update_merge.sh` 完成后不要更新它
- 只有在 Qdrant delete + upsert 全部成功后，才更新它
- 原因是：
  - SQLite + FTS 完成，不代表整条增量链完成
  - 只有 Qdrant 也完成，检索链路才是完整一致的新版本

更新方式：

- 使用一键 Qdrant 入口时：
  - `bash incremental/update_qdrant_incremental.sh ...`
  - 会自动更新 `corpus/current_release.txt`
- 如果你是手动执行：
  - `python incremental/qdrant_encode.py ...`
  - `python incremental/qdrant_load.py ...`
  - 那么在 `qdrant_load.py` 成功后，需要手动执行：

```bash
echo 2026-03-10 > corpus/current_release.txt
```

日常建议：

- 把 `current_release.txt` 当成“整条增量链是否完成”的最终标记
- 不要因为 SQLite 已完成就提前改它
- 若中途失败，保留旧 release 更安全，下一次增量仍能基于真实已完成版本继续

---

## 4. 任务生成规则

`incremental/qdrant_manifest.py` 会按当前 SQLite 状态重新生成 Qdrant 任务：

- `papers/updates`
  - 只保留 diff 里带 `ArXiv/arXiv`
  - 且当前 `paper_id` 仍属于 `arxiv_to_paper`
- `abstracts/updates`
  - 只保留当前 `paper_id` 仍属于 `arxiv_to_paper`
- `paper-ids/papers/abstracts deletes`
  - 只保留当前 arXiv 论文对应的删除项

这一步替代了旧版本中把 Qdrant 待办直接塞进 `_merge_progress.json` 的做法。

---

## 5. 主键说明

| 数据集 | 主键字段 |
|------|------|
| `papers` | `corpusid` |
| `abstracts` | `corpusid` |
| `paper-ids updates` | `corpusid` |
| `paper-ids deletes` | `sha` |
| `authors` | `authorid` |
| `citations` | `citationid` |

---

## 6. 相关文件

| 路径 | 作用 |
|------|------|
| `incremental/download.py` | 下载增量 diff |
| `incremental/validate.py` | 校验增量 diff |
| `incremental/sqlite_fts_merge.py` | SQLite + FTS 增量 merge |
| `incremental/qdrant_manifest.py` | 生成 `_qdrant_task.json` |
| `incremental/qdrant_encode.py` | 多卡编码增量向量 |
| `incremental/qdrant_load.py` | 将增量向量写入 Qdrant |
| `incremental/rebuild_qdrant_progress.py` | 历史修复工具：重建 `_qdrant_task.json` |
| `incremental/update.sh` | 一键增量更新 |

---

## 7. 注意事项

- `authors` 仍然只下载，不参与当前 SQLite/FTS/Qdrant 增量链路。
- SQLite + FTS 成功不代表整个增量完成；还需要 Qdrant 步骤。
- `corpus/current_release.txt` 只会在 `incremental/update_qdrant_incremental.sh` 成功后更新。
- 若你手动执行 `qdrant_load.py`，记得在成功后手动更新 `corpus/current_release.txt`。
- 如果只想重复 Qdrant，不需要重跑 SQLite/FTS；直接使用已有的 `_qdrant_task.json` 即可。
- `incremental/rebuild_qdrant_progress.py` 仅用于修复历史脏状态，不属于日常标准步骤。
