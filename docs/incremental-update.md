# 增量更新指南

本文档说明如何基于 [S2 Datasets API - Incremental Updates](https://api.semanticscholar.org/api-docs/datasets#tag/Incremental-Updates) 对 PaperData 进行增量更新。

---

## 1. 一键更新（推荐）

```bash
# 更新到最新 S2 release
bash update.sh

# 更新到指定日期
bash update.sh 2026-03-10
```

脚本自动完成以下流程：

1. 从 `corpus/current_release.txt` 读取当前版本
2. 查询 S2 API 获取可用 releases，确定目标版本
3. 下载增量 diff 到 `PaperData/incremental/`
4. 合并到 SQLite（paper_metadata、citations、ID 映射）+ FTS5
5. 编码新增/修改论文的 BGE-M3 向量，upsert 到 Qdrant；删除已移除论文的向量
6. 更新 `corpus/current_release.txt` 为最新版本

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
| paper-ids   | `corpusid`   |
| authors     | `authorid`   |
| citations   | `citationid` |

---

## 4. 手动分步执行

如需手动控制每个步骤，可分开执行：

### 4.1 下载增量 diff

```bash
# 自动从 corpus/current_release.txt 读取起始版本，下载到最新
python build_corpus/data/download_incremental_diffs.py

# 指定起止版本
python build_corpus/data/download_incremental_diffs.py --start 2026-01-27 --end 2026-03-10
```

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
python build_corpus/merge_incremental.py PaperData/incremental/2026-01-27_to_2026-02-24
```

合并操作包括：

- SQLite：upsert/delete paper_metadata、corpus_id_mapping、arxiv_to_paper、citations
- FTS5：刷新 paper_fts_title 和 paper_fts_combined
- Qdrant：编码新增/修改论文的 BGE-M3 向量并 upsert，删除已移除论文的向量

### 4.3 更新版本记录

```bash
echo "2026-02-24" > corpus/current_release.txt
```

---

## 5. 相关脚本

| 脚本 | 作用 |
|------|------|
| `update.sh` | 一键更新入口（下载 + 合并 + 版本更新） |
| `build_corpus/data/download_incremental_diffs.py` | 下载增量 diff 到 PaperData 目录 |
| `build_corpus/merge_incremental.py` | 合并增量到 SQLite + FTS5 + Qdrant |
| `build_corpus/optimize_fts.py` | FTS5 索引优化（建议更新后执行） |

---

## 6. 注意事项

- 需要配置 `S2_API_KEY`（`.env` 或环境变量）以访问 Datasets API。
- diff 的 `update_files`、`delete_files` 为预签名 URL，有时效，建议下载后本地保存。
- 合并时需保证主键一致（如 `corpusid`、`citationid`、`authorid`）。
- 合并完成后增量文件保留在 `PaperData/incremental/` 中，不会自动删除。
- 合并过程中 Qdrant 向量编码需要 GPU，确保有可用的 CUDA 设备。
