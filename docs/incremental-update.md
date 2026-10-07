# 增量更新指南

首次部署使用 [ModelScope 发布语料](data.md)。已有语料通过 Semantic Scholar Datasets API 拉取 diffs，依次更新 SQLite、FTS5 和 Qdrant，无需重新下载全量原始数据。

增量更新不是从 ModelScope 自动同步新快照。若选择替换为更新的完整发布包，按 [语料库指南](data.md) 停服、备份和成套替换，不与下面的增量流程混用。

## 1. 前置条件

- 已安装 `requests`：`python -m pip install requests`。
- `.env` 已配置可访问 S2 Datasets API 的 `S2_API_KEY`。
- `corpus/current_release.txt` 包含本地 SQLite 与 Qdrant 实际对应的 S2 release；使用下载的标记，不自行填写今天日期。
- Qdrant Server 已启动，`papers` 集合可查询；增量编码使用已配置的 BGE-M3 和 CUDA GPU。
- 目标 release 晚于本地版本，源 release 到目标 release 的 diffs 仍可由上游取得。
- 已备份匹配版本的 SQLite、Qdrant 与 release 标记，预留下载、临时文件与向量分片空间。

流程分阶段写入，SQLite 合并与 Qdrant 入库不是跨系统原子事务。严格一致性场景请在维护窗口暂停 API 查询和其他更新任务。不要并发运行两条更新链。

## 2. 单卡推荐流程

以下变量与命令在**同一个 Bash 会话**中执行。示例日期不代表最新 release，应按实际版本替换。

```bash
bash
TARGET=2026-04-07  # 替换为期望日期，或 latest
START=$(tr -d '[:space:]' < corpus/current_release.txt)
cat corpus/current_release.txt
bash incremental/update_download.sh "$TARGET"
```

下载脚本会输出类似：

```text
📦 END_RELEASE=2026-04-07
📦 INCR_DIR=.../PaperData/incremental/2026-03-10_to_2026-04-07
```

**以实际输出为准**：日期目标会解析为不晚于目标的最近可用 release，`latest` 会解析为具体日期。若输出 Already up to date，则无需合并。

复制真实的 `END_RELEASE` 与 `INCR_DIR`，再执行：

```bash
END_RELEASE=2026-04-07  # 替换为实际 END_RELEASE
INCR_DIR="PaperData/incremental/${START}_to_${END_RELEASE}"

bash incremental/update_validate.sh "$END_RELEASE"
bash incremental/update_merge.sh "$INCR_DIR"
bash incremental/update_qdrant_incremental.sh "$INCR_DIR" 0
```

最后的参数 `0` 表示用 GPU 0 编码一个完整分片；多卡可写 `0,2,3`。GPU 列表是脚本第二个位置参数，不能仅通过 `.env` 的 `GPU_DEVICE_ID` 改写该列表。

若编码显存不足，可以减小批大小：

```bash
QDRANT_INCREMENTAL_ENCODE_BATCH_SIZE=16 \
  bash incremental/update_qdrant_incremental.sh "$INCR_DIR" 0
```

默认批大小为 64。重试同一任务时保持 GPU / shard 划分一致，不要复用不匹配的历史分片。

## 3. 一键入口

```bash
bash incremental/update.sh latest
# 或指定日期
bash incremental/update.sh 2026-04-07
```

顺序为下载 → 校验 → SQLite/FTS 合并 → Qdrant 编码 → Qdrant 入库。

**当前一键入口调用 Qdrant 脚本时不传 GPU 列表，使用默认的 `0,2,3` 三张卡。** 仅在这些卡都可用时使用；单卡部署使用上一节分步流程。

## 4. 每个阶段做什么

| 阶段 | 入口 | 输出 / 状态 |
| --- | --- | --- |
| 下载 | `update_download.sh` / `download.py` | `PaperData/incremental/{start}_to_{end}/` 下的 diff 文件 |
| 校验 | `update_validate.sh` / `validate.py` | 完整 gzip/UTF-8 检查，重下坏文件，维护 `_download_validation_progress.json` |
| SQLite/FTS 合并 | `update_merge.sh` / `sqlite_fts_merge.py` | 更新元数据、映射、引用和 FTS；生成 `_qdrant_task.json` |
| 编码 | `qdrant_encode.py` | `qdrant_embeddings/incremental_embeddings_shard_{i}.npz` |
| Qdrant 入库 | `qdrant_load.py` | 先 delete 再 upsert，成功后标记 `task_status.loaded` |

`authors` 会下载，但不参与当前 SQLite/FTS/Qdrant 合并。下载器看到目标文件已存在会跳过，临时 `.tmp` 文件支持续传；下载完成不等于完整性校验通过，不能跳过校验阶段。

### 手动编码与入库

通常使用 `update_qdrant_incremental.sh` 自动执行；调试时可拆开。单卡示例：

```bash
python incremental/qdrant_encode.py "$INCR_DIR" \
  --gpu 0 --shard 0 --total-shards 1
python incremental/qdrant_load.py "$INCR_DIR"
```

多卡时必须为 `0..total_shards-1` 每个 shard 完成一次编码。仅执行 `--shard 0 --total-shards 3` 只编码约三分之一的输入，不是完整更新。当前 loader 按目录中实际存在的 NPZ 入库，**不要把 loaded 标记当成所有计划分片都已到齐的证明**，应同时核对编码日志和 `encoded_shards`。

手动调用 `qdrant_load.py` 不更新 `current_release.txt`。确认所有计划分片完成、delete/upsert 成功并完成下面的验收后，才手动写入实际目标 release：

```bash
printf '%s\n' "$END_RELEASE" > corpus/current_release.txt
```

使用 `update_qdrant_incremental.sh` 则会在其编码 / 入库流程成功结束后自动写入；仍须检查是否有 GPU 子进程报错及分片遗漏。

## 5. 状态文件与版本规则

| 文件 | 意义 |
| --- | --- |
| `_download_validation_progress.json` | 已完整校验的 diff 文件 |
| `_merge_progress.json` | SQLite/FTS 的 `completed_steps` 与 `step_offsets`，用于续跑 |
| `_qdrant_task.json` | `upsert_corpus_ids`、`delete_paper_ids`、`task_status` 与摘要 |
| `qdrant_embeddings/*.checkpoint` | 编码断点，保留后可继续同一分片 |
| `corpus/current_release.txt` | 对外声明的数据版本，也是下一次下载的起点 |

**只完成 SQLite/FTS 时不能推进 release。** 必须等 Qdrant 更新完整成功。发布标记也不是数据备份；出错时修改标记不会撤销数据库写入。

## 6. 失败恢复

| 失败位置 | 处理方法 |
| --- | --- |
| 网络下载中断 | 用相同源版本与目标版本重跑下载，继续 `.tmp` 或跳过已存在文件 |
| gzip / UTF-8 校验失败 | 重跑校验，确认坏文件已重新下载并验证 |
| SQLite/FTS 合并中断 | 保留 `_merge_progress.json`，对相同 `INCR_DIR` 重跑 merge |
| GPU 编码失败 | 修正模型路径、GPU 编号或批大小，对同一任务和相同分片划分重跑 Qdrant 阶段 |
| Qdrant 入库失败 | 确认服务正常与分片完整后，重跑 `python incremental/qdrant_load.py "$INCR_DIR"`；按手动流程处理版本标记 |
| 需要回滚 | 停服后成套恢复更新前的 SQLite、Qdrant 和 release，而非只改日期 |

不要随意删除任务、进度或 checkpoint 文件。历史状态修复工具 `rebuild_qdrant_progress.py` 不属于日常更新步骤，使用前应检查实际数据状态。

## 7. 更新后验收

```bash
cat corpus/current_release.txt
curl --fail http://localhost:6333/collections/papers

python - "$INCR_DIR" <<'PY'
import json, sys
from pathlib import Path
task = json.loads((Path(sys.argv[1]) / '_qdrant_task.json').read_text())
print('task_status:', task.get('task_status'))
print('summary:', task.get('summary'))
PY
```

核对目标 release、所有编码分片与 loaded 状态，检查增量日志中没有失败，再通过 [部署指南](deployment.md) 的 sparse、hybrid、详情及引用请求验证服务。若更新期间暂停了 API，应在恢复后验收。

SQLite 与 Qdrant 的论文 ID 应保持对应关系，但引用边数量、collection 点数、FTS 行数不是同一种计数，不能简单要求全部相等。
