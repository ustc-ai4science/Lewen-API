# 增量更新指南

本文档说明如何基于 [S2 Datasets API - Incremental Updates](https://api.semanticscholar.org/api-docs/datasets#tag/Incremental-Updates) 对 PaperData 进行增量更新。

---

## 1. 执行方式

```bash
# 方式 A：一键串联（下载 + 校验 + merge）
bash update.sh

# 更新到指定目标 release
bash update.sh 2026-03-10

# 方式 B：拆分执行
# 1) 只下载增量 diff
bash update_download.sh 2026-03-10

# 2) 只校验已下载好的增量 diff
bash update_validate.sh 2026-03-10

# 3) 只 merge 已下载好的增量目录
bash update_merge.sh PaperData/incremental/2026-01-27_to_2026-03-10
```

推荐做法：

1. 网络不稳定、只想先把文件拉下来时，先运行 `update_download.sh`
2. 文件下完后，再运行 `update_validate.sh` 做完整校验与坏文件重下
3. 需要重复调试 merge、断点恢复或只想继续上次合并时，直接运行 `update_merge.sh`
4. `update.sh` 仅作为方便的一键封装，本质上顺序调用三者

`update.sh` 自动完成以下流程：

1. 从 `corpus/current_release.txt` 读取当前版本
2. 查询 S2 API 获取可用 releases，确定目标版本
3. 下载增量 diff 到 `PaperData/incremental/`
4. 校验已下载 diff，并对损坏/缺失文件重下
5. 合并到 SQLite（paper_metadata、citations、ID 映射）+ FTS5
6. 编码新增/修改论文的 BGE-M3 向量，upsert 到 Qdrant；删除已移除论文的向量
7. 更新 `corpus/current_release.txt` 为最新版本

### 前置条件

- `corpus/current_release.txt` 存在且包含当前 release 日期
- `.env` 中配置了 `S2_API_KEY`
- Qdrant 服务运行中
- GPU 可用（BGE-M3 编码需要）

### 版本跟踪

当前数据对应的 S2 release 日期记录在 `corpus/current_release.txt` 中（初始值 `2026-01-27`），每次更新成功后自动写入新版本。

---

## 2. 增量更新原理

- **全量数据**：每次 release 包含完整快照，体积大。
- **增量 diff**：只包含相邻两次 release 之间的变更（`update_files` 新增/更新，`delete_files` 删除）。
- **Release 周期**：通常每周一次（如 2026-01-27 → 2026-02-03 → 2026-02-10）。

### S2 API 端点

```
GET /diffs/{start_release_id}/to/{end_release_id}/{dataset_name}
```

- `start_release_id`：你当前持有的 release（如 `2026-01-27`）
- `end_release_id`：目标 release，或 `latest`
- `dataset_name`：`papers` | `authors` | `citations` | `abstracts` | `paper-ids`

### 返回结构

```json
{
  "dataset": "papers",
  "start_release": "2026-01-27",
  "end_release": "2026-02-24",
  "diffs": [
    {
      "from_release": "2026-01-27",
      "to_release": "2026-02-03",
      "update_files": ["https://..."],
      "delete_files": ["https://..."]
    },
    ...
  ]
}
```

- `update_files`：需按主键 upsert 的记录（JSONL）
- `delete_files`：需按主键删除的记录（JSONL）

---

## 3. 主键说明

| 数据集      | 主键字段     |
|-------------|--------------|
| papers      | `corpusid`   |
| abstracts   | `corpusid`   |
| paper-ids updates  | `corpusid` |
| paper-ids deletes  | `sha`      |
| authors     | `authorid`   |
| citations   | `citationid` |

---

## 4. 手动分步执行

如需手动控制每个步骤，可分开执行：

### 4.1 下载增量 diff

```bash
# 推荐：通过 shell 入口下载
bash update_download.sh

# 指定目标 release
bash update_download.sh 2026-03-10

# 单独校验并为损坏文件补下
bash update_validate.sh 2026-03-10

# 或直接调用 Python 脚本
python build_corpus/data/download_incremental_diffs.py
python build_corpus/data/download_incremental_diffs.py --start 2026-01-27 --end 2026-03-10
python build_corpus/data/download_incremental_diffs.py --start 2026-01-27 --end 2026-03-10 --mode validate
```

下载阶段与校验阶段现在分开：

- `update_download.sh`
  - 只负责“文件是否存在”
  - 若目标文件已存在，直接跳过
  - 若上次中断留下 `.tmp`，会自动断点续下
- `update_validate.sh`
  - 负责完整校验 `.gz/.jsonl` 内容
  - 若文件缺失或损坏，会自动重新下载
  - 会在增量目录下维护 `_download_validation_progress.json`
  - 已校验通过的文件会被记录，下次校验时直接跳过

### 输出目录结构

```
PaperData/
  incremental/
    2026-01-27_to_2026-02-24/
      papers/
        updates/   # 来自 update_files
        deletes/   # 来自 delete_files
      authors/
        updates/
        deletes/
      citations/
        updates/
        deletes/
      abstracts/
        updates/
        deletes/
      paper-ids/
        updates/
        deletes/
```

每个 `updates/`、`deletes/` 下的文件为 JSONL（或 .gz），格式与 PaperData 全量一致。

### 4.2 合并到数据库

```bash
# 推荐：通过 shell 入口 merge
bash update_merge.sh PaperData/incremental/2026-01-27_to_2026-02-24

# 或直接调用 Python 脚本
python build_corpus/merge_incremental.py PaperData/incremental/2026-01-27_to_2026-02-24
```

合并操作包括：

- SQLite：upsert/delete paper_metadata、corpus_id_mapping、arxiv_to_paper、citations
- FTS5：刷新 paper_fts_title 和 paper_fts_combined
- Qdrant：编码新增/修改论文的 BGE-M3 向量并 upsert，删除已移除论文的向量

补充说明：

- `merge_incremental.py` 会为每个数据集步骤显示文件级 `tqdm` 进度条
- Qdrant 编码阶段也会显示批量进度
- merge 过程中会在增量目录下写入 `_merge_progress.json`
- `_merge_progress.json` 记录步骤级状态；对 `papers-updates`、`abstracts-updates`、`citations-updates`、`citations-deletes` 这类重步骤，会额外记录已成功 commit 的 chunk offset
- 如果进程中断，重新执行同一 `INCR_DIR` 时会自动跳过已完成步骤并继续
- 若上述重步骤中途失败，会从上一个成功 commit 的 chunk 继续，而不是从步骤开头完全重跑
- 全部完成后 `_merge_progress.json` 会自动删除
- 如果 merge 时发现损坏或不可读的 diff 文件，会直接报错并中止；应先回到下载阶段重新拉取文件

### 4.3 更新版本记录

```bash
echo "2026-02-24" > corpus/current_release.txt
```

---

## 5. 相关脚本

| 脚本 | 作用 |
|------|------|
| `update.sh` | 一键更新入口（调用下载脚本 + merge 脚本） |
| `update_download.sh` | 只下载增量 diff，不执行完整校验、不执行 merge |
| `update_validate.sh` | 只校验增量 diff，并对缺失/损坏文件重下 |
| `update_merge.sh` | 只对指定增量目录执行 merge，并更新版本记录 |
| `build_corpus/data/download_incremental_diffs.py` | 下载增量 diff 到 PaperData 目录 |
| `build_corpus/merge_incremental.py` | 合并增量到 SQLite + FTS5 + Qdrant，支持断点续传 |
| `build_corpus/optimize_fts.py` | FTS5 索引优化（建议更新后执行） |

---

## 6. 注意事项

- 需要配置 `S2_API_KEY`（`.env` 或环境变量）以访问 Datasets API。
- diff 的 `update_files`、`delete_files` 为预签名 URL，有时效，建议下载后本地保存。
- 合并时需保证主键一致（如 `corpusid`、`citationid`、`authorid`）。
- `paper-ids` 的主键口径需要分开看：`updates` 用 `corpusid`，`deletes` 用 `sha`
- 合并完成后增量文件保留在 `PaperData/incremental/` 中，不会自动删除。
- 合并过程中 Qdrant 向量编码需要 GPU，确保有可用的 CUDA 设备。
- 如果只想补文件，不必每次完整校验；先跑 `update_download.sh` 即可。
- 如果只想重复 merge，不要先跑下载/校验；直接执行 `update_merge.sh` 即可。
- `_merge_progress.json` 属于 merge 的运行时状态文件；若一次 merge 已完整成功，它会自动被清理。
- `_download_validation_progress.json` 属于校验阶段的运行时状态文件；会保留在增量目录下，供下次继续校验时复用。
- chunk 或步骤重跑不会在 SQLite 或 Qdrant 中产生“重复数据行”；当前实现依赖 upsert/delete 的幂等性，但会产生额外耗时。
