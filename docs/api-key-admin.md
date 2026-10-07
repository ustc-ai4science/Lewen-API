# 管理员运维指南

本文档面向管理员，说明如何启动管理看板，以及如何创建、查看、禁用和删除 API Key。

---

## 1. 前置配置

在 `.env` 中设置以下环境变量：

```bash
# 启用认证（不设置或设为 false 则所有接口无需 Key）
AUTH_ENABLED=true

# 管理员 API 密钥（用于远程管理 Key，为空则管理员 API 不可用）
ADMIN_SECRET=your-secret-here

# 可选：Key 缓存 TTL，默认 60 秒
# AUTH_CACHE_TTL=60
```

设置后重启 API 服务生效。

---

## 2. 管理员看板

管理员看板不需要前端构建工具。推荐把它作为独立服务启动，这样更新或重启管理员看板不会中断 `4000` 端口上的 Paper Search API。

### 2.1 启动服务

先完成 [环境配置](setup.md) 和 [语料库安装](data.md)。在三个独立终端中分别启动 Qdrant、Paper API 和管理员服务（以下命令均为前台进程）：

```bash
cd /path/to/Lewen-API
bash start_qdrant.sh
bash start_api.sh
bash start_admin.sh
```

默认端口：

| 服务 | 默认地址 | 说明 |
|------|----------|------|
| Paper API | `http://localhost:4000` | 对外搜索 API |
| Admin Panel | `http://localhost:4100/admin/panel` | 管理员看板 |

如果需要临时指定环境变量启动管理员服务：

```bash
cd /path/to/Lewen-API
ADMIN_SECRET=your-secret-here \
ADMIN_PORT=4100 \
ADMIN_TARGET_API_BASE_URL=http://localhost:4000 \
python admin_main.py
```

如果使用 `.env`，确认至少包含：

```bash
AUTH_ENABLED=true
ADMIN_SECRET=your-secret-here
```

管理员服务可选配置：

```bash
# 管理员看板监听地址，默认 0.0.0.0
ADMIN_HOST=0.0.0.0

# 管理员看板端口，默认 4100
ADMIN_PORT=4100

# 管理员看板调用的 Paper API 地址，默认 http://localhost:4000
ADMIN_TARGET_API_BASE_URL=http://localhost:4000
```

### 2.2 打开看板

浏览器访问：

```text
http://localhost:4100/admin/panel
```

在页面顶部输入 `.env` 中的 `ADMIN_SECRET` 后即可解锁。看板支持：

- 查看 API、SQLite、Qdrant、当前 release 和 API key 概览
- 管理 API key
- 对 `/paper/*` 接口做单次测试（未手动填写 API key 时使用 `.env` 中的 `Lewen_API_KEY` / `PAPER_SEARCH_API_KEY` / `API_KEY`）
- 启动压测任务并查看日志（未手动填写 API key 时使用 `.env` 中的 API key）
- 启动增量更新的 full/download/validate/merge/qdrant 阶段
- 中断正在运行的后台任务
- 后台刷新大表精确统计，避免打开页面时扫描大型 SQLite 数据库

### 2.3 更新看板是否需要重启

| 修改内容 | 是否影响 Paper API | 是否需要重启 |
|----------|--------------------|--------------|
| 只修改 `api/admin_panel.html` | 不影响 | 不需要，浏览器刷新即可 |
| 修改管理员后端逻辑（如 `api/admin.py`、`core/admin_jobs.py`） | 不影响 | 只重启 `start_admin.sh` 对应的管理员服务 |
| 修改 Paper API 检索逻辑（如 `main.py`、`api/paper.py`、`core/retrieve/*`） | 影响 | 需要重启 Paper API |

!!! warning "高风险操作"
    增量更新、Qdrant 更新、压测等操作会在服务器本地执行命令。请只在可信内网或本机环境使用管理看板，并妥善保管 `ADMIN_SECRET`。

### 2.4 日志位置

管理看板启动的后台任务日志保存在：

```text
logs/admin_jobs/
```

管理员服务自身日志保存在：

```text
logs/admin.log
```

API 服务自身日志仍保存在：

```text
logs/api.log
```

---

## 3. CLI 管理（服务器本地操作）

需要 SSH 到服务器，在项目根目录执行。

### 3.1 创建 Key

```bash
python manage_keys.py create --name "用户A" --email "a@example.com"
```

输出：

```
✅ API Key created (shown ONCE, save it now):

   Key:     lw-a3f8c7e2d1b5094f6e3a2c8d7b1e4f09
   Prefix:  lw-a3f8c7e2
   Name:    用户A
   Email:   a@example.com
```

> **Key 只展示这一次**，请立即复制给用户。数据库中只存储 SHA-256 hash。

可选参数：`--expires-at "2026-12-31T23:59:59+00:00"`（ISO 8601 格式，不指定则永不过期）。

### 3.2 列出所有 Key

```bash
python manage_keys.py list
```

输出表格包含：ID、Prefix、是否启用、名称、邮箱、创建时间、最后使用时间。

### 3.3 禁用 Key

```bash
python manage_keys.py revoke --prefix "lw-a3f8c7e2"
```

禁用操作会通知各 worker 清理缓存，通常在后续请求中生效；Key 缓存 TTL 默认为 60 秒。

### 3.4 重新启用 Key

```bash
python manage_keys.py activate --prefix "lw-a3f8c7e2"
```

### 3.5 永久删除 Key

```bash
python manage_keys.py delete --prefix "lw-a3f8c7e2"
```

---

## 4. 管理员 API（远程操作）

无需 SSH，在任何地方通过 HTTP 调用。所有请求需携带 `X-Admin-Secret` 头。

### 4.1 创建 Key

```bash
curl -X POST http://localhost:4000/admin/keys \
  -H "X-Admin-Secret: your-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"name": "用户A", "email": "a@example.com"}'
```

响应：

```json
{
  "key": "lw-a3f8c7e2d1b5094f6e3a2c8d7b1e4f09",
  "id": 1,
  "key_prefix": "lw-a3f8c7e2",
  "name": "用户A",
  "email": "a@example.com",
  "expires_at": null
}
```

### 4.2 列出所有 Key

```bash
curl http://localhost:4000/admin/keys \
  -H "X-Admin-Secret: your-secret-here"
```

### 4.3 禁用 Key

```bash
curl -X POST http://localhost:4000/admin/keys/lw-a3f8c7e2/revoke \
  -H "X-Admin-Secret: your-secret-here"
```

### 4.4 重新启用 Key

```bash
curl -X POST http://localhost:4000/admin/keys/lw-a3f8c7e2/activate \
  -H "X-Admin-Secret: your-secret-here"
```

### 4.5 删除 Key

```bash
curl -X DELETE http://localhost:4000/admin/keys/lw-a3f8c7e2 \
  -H "X-Admin-Secret: your-secret-here"
```

---

## 5. 常见操作场景

### 用户申请 Key

1. 收到用户邮件申请
2. 执行 `python manage_keys.py create --name "xxx" --email "xxx@xxx.com"`（或调管理员 API）
3. 将输出的 Key 回复给用户

### 用户 Key 泄露

1. `python manage_keys.py revoke --prefix "lw-xxxx"`
2. 重新创建一个新 Key 给用户

### 用户不再使用

1. `python manage_keys.py delete --prefix "lw-xxxx"`

### 自己使用

管理员也需要一个 API Key 来访问 `/paper/*` 接口，给自己创建一个即可：

```bash
python manage_keys.py create --name "admin" --email "admin@lewen.com"
```

---

## 6. 数据文件

| 文件 | 说明 |
|------|------|
| `corpus/auth.db` | API Key 数据库（SQLite），已在 `.gitignore` 中排除 |
| `.env` | 包含 `ADMIN_SECRET` 等敏感配置，已在 `.gitignore` 中排除 |

> 备份服务器时请一并备份 `corpus/auth.db`，否则所有 Key 将丢失。

---

## 7. 监控与流量查看

### 7.1 日志中的 Key 标识

每次认证成功的请求会在 `logs/api.log` 中记录一行，包含 **key_prefix**（不记录完整 Key，避免泄露）：

```
2026-03-16 16:30:01  INFO     auth.middleware  key_prefix=lw-72e13819 path=/paper/search method=GET
```

可根据 `key_prefix` 对应到 `manage_keys.py list` 或 `/admin/keys` 中的 Key。

### 7.2 按 Key 统计请求量

```bash
# 统计各 key_prefix 的请求次数
grep "key_prefix=" logs/api.log | sed -n 's/.*key_prefix=\([^ ]*\).*/\1/p' | sort | uniq -c | sort -rn

# 只看某个 Key 的请求
grep "key_prefix=lw-72e13819" logs/api.log
```

### 7.3 数据库中的最后使用时间

`manage_keys.py list` 或 `GET /admin/keys` 中的 `last_used_at` 会在该 Key 每次被使用时更新（有缓存时可能延迟最多约 1 分钟），可用来判断 Key 是否仍在被使用。
