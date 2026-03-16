# Lewen API Documentation

User-facing API reference for the Lewen academic search service.

---

## 1. Overview

Lewen API provides academic paper search and retrieval with the following capabilities:

- **Semantic search**: Sparse (BM25), dense (vector), and hybrid retrieval
- **Title search**: Match papers by title similarity
- **Paper details**: Lookup by multiple ID formats
- **Citation graph**: Citations and references (arXiv-internal only)

All endpoints return JSON.

---

## 2. Base Information

| Item | Description |
|------|-------------|
| **Base URL** | `http://210.45.70.162:4000` |
| **Authentication** | API Key required (see below) |
| **Content-Type** | `application/json` |

### 2.1 Authentication

All `/paper/*` endpoints require an API key. Pass it via one of:

**Option 1: Request header (recommended)**

```bash
curl -H "X-API-Key: lw-your-api-key" "http://210.45.70.162:4000/paper/search?query=transformer"
```

**Option 2: Query parameter**

```bash
curl "http://210.45.70.162:4000/paper/search?query=transformer&apiKey=lw-your-api-key"
```

**Python example**

```python
import requests

headers = {"X-API-Key": "lw-your-api-key"}
r = requests.get("http://210.45.70.162:4000/paper/search",
                  params={"query": "transformer"},
                  headers=headers)
print(r.json())
```

To request an API key, please contact us via email.

!!! warning "Keep your API key safe"
    The API key is shown only once at creation time. The server does not store the plaintext key. If lost, it cannot be recovered — you will need to request a new one.

**Authentication error responses**

| HTTP Status | Description |
|-------------|-------------|
| 401 | No API key provided |
| 403 | Invalid or inactive API key |

---

## 3. Endpoints

| Endpoint | Method | Path | Description |
|----------|--------|------|-------------|
| Semantic search | GET | `/paper/search` | Search by query relevance |
| Title search | GET | `/paper/search/title` | Search by title similarity |
| Paper details | GET | `/paper/{paper_id}` | Get single paper metadata |
| Citations | GET | `/paper/{paper_id}/citations` | Papers that cite this paper |
| References | GET | `/paper/{paper_id}/references` | Papers cited by this paper |

---

## 4. Endpoint Reference

### 4.1 Semantic Search `GET /paper/search`

Search papers by semantic relevance. Supports sparse, dense, and hybrid retrieval modes.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search keywords or natural language |
| `retrieval` | string | No | `hybrid` | Mode: `sparse` / `dense` / `hybrid` |
| `fields` | string | No | - | Comma-separated fields to return, e.g. `abstract,year,authors`. Use `fields=*` or `fields=all` for full metadata. Default: `paperId` and `title` only. |
| `year` | string | No | - | Year filter, e.g. `2019`, `2016-2020`, `2010-`, `-2015` |
| `venue` | string | No | - | Comma-separated venue filter |
| `fieldsOfStudy` | string | No | - | Comma-separated fields of study |
| `publicationTypes` | string | No | - | Comma-separated publication types |
| `openAccessPdf` | string | No | - | Any non-empty value: only papers with public PDF |
| `minCitationCount` | int | No | - | Minimum citation count |
| `offset` | int | No | 0 | Pagination offset |
| `limit` | int | No | 10 | Results per page (1–100) |

#### Retrieval Modes

| Value | Description | GPU Required |
|-------|-------------|--------------|
| `sparse` | BM25 full-text search | No |
| `dense` | Vector semantic search | Yes |
| `hybrid` | Sparse + dense + RRF fusion (recommended) | Yes |

#### Example Requests

**curl**

```bash
# Hybrid retrieval (default)
curl "http://210.45.70.162:4000/paper/search?query=transformer%20attention&limit=5"

# Sparse retrieval (when GPU unavailable)
curl "http://210.45.70.162:4000/paper/search?query=transformer&retrieval=sparse&limit=10"

# With filters
curl "http://210.45.70.162:4000/paper/search?query=BERT&year=2018-2020&minCitationCount=100&fields=abstract,year,authors"

# Return all metadata (fields=* or fields=all)
curl "http://210.45.70.162:4000/paper/search?query=BERT&fields=*&limit=5"
```

**Python**

```python
import requests

BASE = "http://210.45.70.162:4000"

# Hybrid retrieval (default)
r = requests.get(f"{BASE}/paper/search", params={"query": "transformer attention", "limit": 5})
print(r.json())

# Sparse retrieval
r = requests.get(f"{BASE}/paper/search", params={"query": "transformer", "retrieval": "sparse", "limit": 10})

# With filters
r = requests.get(f"{BASE}/paper/search", params={
    "query": "BERT",
    "year": "2018-2020",
    "minCitationCount": 100,
    "fields": "abstract,year,authors",
})

# Return all metadata
r = requests.get(f"{BASE}/paper/search", params={"query": "BERT", "fields": "*", "limit": 5})
```

#### Example Response

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

### 4.2 Title Search `GET /paper/search/title`

Search papers by closest title match. Best for known or partial titles.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Title search keywords |
| `fields` | string | No | - | Comma-separated fields to return. Use `fields=*` or `fields=all` for full metadata. Default: `paperId` and `title` only. |
| `year` | string | No | - | Year filter |
| `venue` | string | No | - | Venue filter |
| `fieldsOfStudy` | string | No | - | Fields of study filter |
| `publicationTypes` | string | No | - | Publication types filter |
| `openAccessPdf` | string | No | - | Any non-empty: only open-access PDF |
| `minCitationCount` | int | No | - | Minimum citation count |
| `offset` | int | No | 0 | Pagination offset |
| `limit` | int | No | 10 | Results per page (1–100) |

#### Example Requests

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

### 4.3 Paper Details `GET /paper/{paper_id}`

Get full metadata for a single paper.

#### Supported paper_id Formats

| Format | Example |
|--------|---------|
| SHA | `83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05` |
| arXiv ID | `2309.06180`, `2309.06180v1` |
| Corpus ID | `215416146`, `CorpusId:215416146` |
| arXiv URL | `https://arxiv.org/abs/2309.06180` |

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `paper_id` | string | Yes | Path parameter, supports formats above |
| `fields` | string | No | Comma-separated fields to return. Use `fields=*` or `fields=all` for full metadata. |

#### Example Requests

**curl**

```bash
# By arXiv ID
curl "http://210.45.70.162:4000/paper/2309.06180"

# By SHA with selected fields
curl "http://210.45.70.162:4000/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05?fields=abstract,year,authors"

# Return all metadata
curl "http://210.45.70.162:4000/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05?fields=*"
```

**Python**

```python
import requests

BASE = "http://210.45.70.162:4000"

# By arXiv ID
r = requests.get(f"{BASE}/paper/2309.06180")
print(r.json())

# By SHA with field filter
r = requests.get(f"{BASE}/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05", params={"fields": "abstract,year,authors"})

# Return all metadata
r = requests.get(f"{BASE}/paper/83b90f4a0ae4cc214eb3cc140ccfef9cd99fac05", params={"fields": "*"})
```

#### Example Response

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

#### Error Response

- **404**: Paper not found or not in corpus

```json
{
  "detail": "Paper not found: invalid_id"
}
```

---

### 4.4 Citations `GET /paper/{paper_id}/citations`

Get papers that cite this paper. **Note**: Only citations where both citing and cited papers are in arXiv.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `paper_id` | string | Yes | - | Path parameter |
| `limit` | int | No | 10 | Results per page (1–100) |
| `offset` | int | No | 0 | Pagination offset |
| `fields` | string | No | - | Comma-separated fields for citingPaper. Use `fields=*` or `fields=all` for full metadata. Default: `paperId` and `title` only. |

#### Example Requests

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

#### Example Response

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

### 4.5 References `GET /paper/{paper_id}/references`

Get papers cited by this paper. **Note**: Only references where both citing and cited papers are in arXiv.

#### Parameters

Same as citations.

#### Example Requests

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

#### Example Response

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

## 5. General

### 5.1 Pagination

List endpoints (search, citations, references) use:

| Field | Description |
|-------|-------------|
| `total` | Total matching count |
| `offset` | Current offset |
| `next` | Next page offset, or `null` if no more |
| `data` | Current page items |

To fetch next page: set `offset` to the value of `next`.

### 5.2 Field Filtering (fields)

`fields` controls which paper metadata is returned. Supported on search, paper detail, citations, and references endpoints.

| Value | Behavior |
|-------|----------|
| Omitted | Returns only `paperId` and `title` |
| `fields=*` or `fields=all` | Returns **all** paper metadata |
| `fields=abstract,year,authors` | Returns `paperId`, `title`, plus the specified fields |

**Available fields** (when specifying explicitly):

| Field | Description |
|-------|-------------|
| `paperId` | Paper SHA (always returned) |
| `title` | Title (always returned) |
| `abstract` | Abstract |
| `year` | Publication year |
| `authors` | Author list |
| `venue` | Venue (conference/journal) |
| `citationCount` | Citation count |
| `referenceCount` | Reference count |
| `fieldsOfStudy` | Fields of study |
| `publicationTypes` | Publication types |
| `publicationDate` | Publication date |
| `openAccessPdf` | Open-access PDF info |
| `externalIds` | External IDs (ArXiv, DOI, etc.) |
| `journal` | Journal info |

**Examples**:
- `fields=abstract,year,authors,citationCount` — return selected fields
- `fields=*` or `fields=all` — return all metadata

### 5.3 Year Filter (year)

| Format | Example | Meaning |
|--------|---------|---------|
| Single year | `2019` | 2019 only |
| Range | `2016-2020` | 2016 through 2020 |
| From year | `2010-` | 2010 and later |
| Until year | `-2015` | 2015 and earlier |

### 5.4 Data Scope

- **Paper corpus**: Papers with ArXiv ID and abstract only
- **Citations/references**: Only edges where both citing and cited papers are in arXiv; some papers may have 0 citations/references

---

## 6. Error Handling

| HTTP Status | Description |
|-------------|-------------|
| 200 | Success |
| 401 | No API key provided |
| 403 | Invalid or inactive API key |
| 404 | Resource not found (e.g. paper not found) |
| 422 | Validation error (e.g. limit out of range) |
| 500 | Server error |

Error response format:

```json
{
  "detail": "Error message"
}
```

---

## 7. Version

- **API version**: 0.2.0
