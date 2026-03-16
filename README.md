# Lewen Academic Search API

A RESTful API for academic paper search, supporting semantic retrieval, title matching, paper metadata lookup, and citation graph queries. Covers ~3M arXiv papers.

## Attention!

For internal network testing: 172.16.100.204

## Quick Start

**Search papers**

```bash
curl "http://210.45.70.162:4000/paper/search?query=transformer+attention&limit=5"
```

**Get paper by arXiv ID**

```bash
curl "http://210.45.70.162:4000/paper/2309.06180?fields=*"
```

**Get citations**

```bash
curl "http://210.45.70.162:4000/paper/1706.03762/citations?limit=10"
```

## Documentation

Full documentation is available at **[ustclewen.github.io/Lewen-API](https://ustclewen.github.io/Lewen-API/)**.

## License

MIT
