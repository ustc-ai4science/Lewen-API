# 乐问学术搜索 API 使用文档

面向用户的 API 使用说明。

---

## 1. 概述

乐问学术搜索 API 提供学术论文检索服务，支持：

- **语义搜索**：稀疏检索、稠密向量检索、混合检索
- **标题检索**：按标题相似度匹配
- **论文详情**：按多种 ID 格式查询
- **引用关系**：获取引用与被引用论文列表

所有接口返回 JSON。

---

## 2. 基础信息

| 项目 | 说明 |
|------|------|
| **Base URL** | `http://210.45.70.162:4000` |
| **认证** | 需要 API Key（见下方认证说明） |
| **Content-Type** | `application/json` |

### 2.1 认证

所有 `/paper/*` 接口需要通过 API Key 认证。通过以下方式之一传递：

**方式一：请求头（推荐）**

```bash
curl -H "X-API-Key: lw-your-api-key" "http://210.45.70.162:4000/paper/search?query=transformer"
```

**方式二：查询参数**

```bash
curl "http://210.45.70.162:4000/paper/search?query=transformer&apiKey=lw-your-api-key"
```

**Python 示例**

```python
import requests

headers = {"X-API-Key": "lw-your-api-key"}
r = requests.get("http://210.45.70.162:4000/paper/search",
                  params={"query": "transformer"},
                  headers=headers)
print(r.json())
```

如需申请 API Key，请通过邮件联系我们。

!!! warning "请妥善保管 API Key"
    API Key 在创建时仅展示一次，服务器端不保留明文。如果遗失，无法找回，只能重新申请。

**认证错误响应**

| HTTP 状态码 | 说明 |
|-------------|------|
| 401 | 未提供 API Key |
| 403 | API Key 无效或已被禁用 |

---

## 3. 接口列表

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 语义搜索 | GET | `/paper/search` | 按查询语义检索论文 |
| 标题检索 | GET | `/paper/search/title` | 按标题相似度检索 |
| 论文详情 | GET | `/paper/{paper_id}` | 获取单篇论文元数据 |
| 引用列表 | GET | `/paper/{paper_id}/citations` | 引用该论文的论文 |
| 参考文献 | GET | `/paper/{paper_id}/references` | 该论文引用的论文 |

---

## 4. 接口详情

### 4.1 语义搜索 `GET /paper/search`

按查询文本的语义相关性检索论文，支持稀疏、稠密、混合三种模式。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | - | 搜索关键词或自然语言描述 |
| `retrieval` | string | 否 | `hybrid` | 检索模式：`sparse` / `dense` / `hybrid` |
| `fields` | string | 否 | - | 逗号分隔的返回字段，如 `abstract,year,authors`。使用 `fields=*` 或 `fields=all` 可返回完整元数据。默认仅返回 `paperId` 和 `title`。 |
| `year` | string | 否 | - | 年份过滤，如 `2019`、`2016-2020`、`2010-`、`-2015` |
| `venue` | string | 否 | - | 逗号分隔的会议/期刊过滤 |
| `fieldsOfStudy` | string | 否 | - | 逗号分隔的学科过滤 |
| `publicationTypes` | string | 否 | - | 逗号分隔的出版类型过滤 |
| `openAccessPdf` | string | 否 | - | 任意非空值表示仅返回有公开 PDF 的论文 |
| `minCitationCount` | int | 否 | - | 最小引用数 |
| `offset` | int | 否 | 0 | 分页偏移 |
| `limit` | int | 否 | 10 | 每页数量（1–100） |

#### 检索模式说明

| 值 | 说明 | 依赖 |
|----|------|------|
| `sparse` | BM25 全文检索 | 无 GPU |
| `dense` | 向量语义检索 | 需 GPU |
| `hybrid` | 稀疏 + 稠密 + RRF 融合（推荐） | 需 GPU |

#### 请求示例

**curl**

```bash
# 混合检索（默认）
curl "http://210.45.70.162:4000/paper/search?query=transformer%20attention&limit=5"

# 稀疏检索（无 GPU 时使用）
curl "http://210.45.70.162:4000/paper/search?query=transformer&retrieval=sparse&limit=10"

# 带过滤条件
curl "http://210.45.70.162:4000/paper/search?query=BERT&year=2018-2020&minCitationCount=100&fields=abstract,year,authors"

# 返回全部元数据（fields=* 或 fields=all）
curl "http://210.45.70.162:4000/paper/search?query=BERT&fields=*&limit=5"
```

**Python**

```python
import requests

BASE = "http://210.45.70.162:4000"

# 混合检索（默认）
r = requests.get(f"{BASE}/paper/search", params={"query": "transformer attention", "limit": 5})
print(r.json())

# 稀疏检索
r = requests.get(f"{BASE}/paper/search", params={"query": "transformer", "retrieval": "sparse", "limit": 10})

# 带过滤条件
r = requests.get(f"{BASE}/paper/search", params={
    "query": "BERT",
    "year": "2018-2020",
    "minCitationCount": 100,
    "fields": "abstract,year,authors",
})

# 返回全部元数据
r = requests.get(f"{BASE}/paper/search", params={"query": "BERT", "fields": "*", "limit": 5})
```

#### 响应示例

```json
{
  "total": 42,
  "offset": 0,
  "next": 10,
  "data": [
    {
      "paperId": "83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05",
      "title": "Attention Is All You Need",
      "abstract": "The dominant sequence transduction models...",
      "year": 2017,
      "authors": [
        {"authorId": null, "name": "Ashish Vaswani"},
        {"authorId": null, "name": "Noam Shazeer"}
      ],
      "venue": "NeurIPS",
      "citationCount": 50000,
      "referenceCount": 31,
      "fieldsOfStudy": ["Computer Science"],
      "publicationTypes": ["Journal", "Conference"],
      "publicationDate": "2017-06-12",
      "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf", "status": "GREEN"},
      "externalIds": {"ArXiv": "1706.03762", "DOI": "10.48550/arXiv.1706.03762"}
    }
  ]
}
```

---

### 4.2 标题检索 `GET /paper/search/title`

按与查询最接近的标题匹配检索论文，适合已知部分标题的精确查找。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | - | 标题搜索关键词 |
| `fields` | string | 否 | - | 逗号分隔的返回字段。使用 `fields=*` 或 `fields=all` 可返回完整元数据。默认仅返回 `paperId` 和 `title`。 |
| `year` | string | 否 | - | 年份过滤 |
| `venue` | string | 否 | - | 会议/期刊过滤 |
| `fieldsOfStudy` | string | 否 | - | 学科过滤 |
| `publicationTypes` | string | 否 | - | 出版类型过滤 |
| `openAccessPdf` | string | 否 | - | 任意非空值表示仅公开 PDF |
| `minCitationCount` | int | 否 | - | 最小引用数 |
| `offset` | int | 否 | 0 | 分页偏移 |
| `limit` | int | 否 | 10 | 每页数量（1–100） |

#### 请求示例

**curl**

```bash
curl "http://210.45.70.162:4000/paper/search/title?query=Attention%20is%20all%20you%20need&limit=5"
```

**Python**

```python
import requests

r = requests.get("http://210.45.70.162:4000/paper/search/title", params={
    "query": "Attention is all you need",
    "limit": 5,
})
print(r.json())
```

---

### 4.3 论文详情 `GET /paper/{paper_id}`

获取单篇论文的完整元数据。

#### paper_id 支持格式

| 格式 | 示例 |
|------|------|
| SHA | `83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05` |
| arXiv ID | `2309.06180`、`2309.06180v1` |
| Corpus ID | `215416146`、`CorpusId:215416146` |
| arXiv URL | `https://arxiv.org/abs/2309.06180` |

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | ✅ | 路径参数，支持上述多种格式 |
| `fields` | string | 否 | 逗号分隔的返回字段。使用 `fields=*` 或 `fields=all` 可返回完整元数据。 |

#### 请求示例

**curl**

```bash
# 使用 arXiv ID
curl "http://210.45.70.162:4000/paper/2309.06180"

# 使用 SHA 并指定返回字段
curl "http://210.45.70.162:4000/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05?fields=abstract,year,authors"

# 返回全部元数据
curl "http://210.45.70.162:4000/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05?fields=*"
```

**Python**

```python
import requests

BASE = "http://210.45.70.162:4000"

# 使用 arXiv ID
r = requests.get(f"{BASE}/paper/2309.06180")
print(r.json())

# 使用 SHA 并指定返回字段
r = requests.get(f"{BASE}/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05", params={"fields": "abstract,year,authors"})

# 返回全部元数据
r = requests.get(f"{BASE}/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05", params={"fields": "*"})
```

#### 响应示例

```json
{
  "paperId": "83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05",
  "title": "Attention Is All You Need",
  "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
  "year": 2017,
  "authors": [...],
  "venue": "NeurIPS",
  "citationCount": 50000,
  "referenceCount": 31,
  "fieldsOfStudy": ["Computer Science"],
  "publicationTypes": ["Journal", "Conference"],
  "publicationDate": "2017-06-12",
  "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf", "status": "GREEN"},
  "externalIds": {"ArXiv": "1706.03762", "DOI": "10.48550/arXiv.1706.03762"},
  "journal": null
}
```

#### 错误响应

- **404**：论文不存在或不在库中

```json
{
  "detail": "Paper not found: invalid_id"
}
```

---

### 4.4 引用列表 `GET /paper/{paper_id}/citations`

获取引用该论文的论文列表。**注意**：仅包含 citing、cited 均在 arXiv 内的引用关系。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `paper_id` | string | ✅ | - | 路径参数 |
| `limit` | int | 否 | 10 | 每页数量（1–100） |
| `offset` | int | 否 | 0 | 分页偏移 |
| `fields` | string | 否 | - | 对 citingPaper 的字段过滤。使用 `fields=*` 或 `fields=all` 可返回完整元数据。默认仅返回 `paperId` 和 `title`。 |

#### 请求示例

**curl**

```bash
curl "http://210.45.70.162:4000/paper/1706.03762/citations?limit=10"
```

**Python**

```python
import requests

r = requests.get("http://210.45.70.162:4000/paper/1706.03762/citations", params={"limit": 10})
print(r.json())
```

#### 响应示例

```json
{
  "total": 1024,
  "offset": 0,
  "next": 10,
  "data": [
    {
      "citingPaper": {
        "paperId": "abc123...",
        "title": "A Survey on Transformers"
      }
    }
  ]
}
```

---

### 4.5 参考文献 `GET /paper/{paper_id}/references`

获取该论文引用的论文列表。**注意**：仅包含 citing、cited 均在 arXiv 内的引用关系。

#### 请求参数

与引用列表相同。

#### 请求示例

**curl**

```bash
curl "http://210.45.70.162:4000/paper/1706.03762/references?limit=10"
```

**Python**

```python
import requests

r = requests.get("http://210.45.70.162:4000/paper/1706.03762/references", params={"limit": 10})
print(r.json())
```

#### 响应示例

```json
{
  "total": 31,
  "offset": 0,
  "next": 10,
  "data": [
    {
      "citedPaper": {
        "paperId": "def456...",
        "title": "Neural Machine Translation by Jointly Learning to Align and Translate"
      }
    }
  ]
}
```

---

## 5. 通用说明

### 5.1 分页

列表类接口（search、citations、references）统一使用：

| 字段 | 说明 |
|------|------|
| `total` | 符合条件的总条数 |
| `offset` | 当前偏移 |
| `next` | 下一页的 offset，无下一页时为 `null` |
| `data` | 当前页数据 |

获取下一页：将 `offset` 设为 `next` 的值。

### 5.2 字段过滤（fields）

`fields` 用于控制返回的论文元数据，适用于搜索、论文详情、引用、参考文献等接口。

| 取值 | 行为 |
|------|------|
| 不传 | 仅返回 `paperId` 和 `title` |
| `fields=*` 或 `fields=all` | 返回**全部**论文元数据 |
| `fields=abstract,year,authors` | 返回 `paperId`、`title` 及指定字段 |

**可选字段**（显式指定时）：

| 字段 | 说明 |
|------|------|
| `paperId` | 论文 SHA（始终返回） |
| `title` | 标题（始终返回） |
| `abstract` | 摘要 |
| `year` | 出版年份 |
| `authors` | 作者列表 |
| `venue` | 会议/期刊 |
| `citationCount` | 引用数 |
| `referenceCount` | 参考文献数 |
| `fieldsOfStudy` | 学科列表 |
| `publicationTypes` | 出版类型列表 |
| `publicationDate` | 出版日期 |
| `openAccessPdf` | 公开 PDF 信息 |
| `externalIds` | 外部 ID（ArXiv、DOI 等） |
| `journal` | 期刊信息 |

**示例**：
- `fields=abstract,year,authors,citationCount` — 返回指定字段
- `fields=*` 或 `fields=all` — 返回全部元数据

### 5.3 年份过滤（year）

| 格式 | 示例 | 含义 |
|------|------|------|
| 单年 | `2019` | 仅 2019 年 |
| 区间 | `2016-2020` | 2016 至 2020 |
| 起始年 | `2010-` | 2010 年及以后 |
| 截止年 | `-2015` | 2015 年及以前 |

### 5.4 数据范围

- **论文库**：仅包含有 ArXiv ID 且具备 abstract 的论文
- **引用关系**：仅包含 citing、cited 均在 arXiv 内的边，部分论文的 citations/references 可能为 0

---

## 6. 错误处理

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 成功 |
| 401 | 未提供 API Key |
| 403 | API Key 无效或已被禁用 |
| 404 | 资源不存在（如论文未找到） |
| 422 | 参数校验失败（如 limit 超出范围） |
| 500 | 服务端错误 |

错误响应格式：

```json
{
  "detail": "错误描述信息"
}
```

---

## 7. 版本信息

- **API 版本**：0.2.0
