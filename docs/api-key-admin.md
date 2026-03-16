# API Key 管理指南

本文档面向管理员，说明如何创建、查看、禁用和删除 API Key。

---

## 1. 前置配置

在 `.env` 中设置以下环境变量：

```bash
# 启用认证（不设置或设为 false 则所有接口无需 Key）
AUTH_ENABLED=true

# 管理员 API 密钥（用于远程管理 Key，为空则管理员 API 不可用）
ADMIN_SECRET=your-secret-here

# 可选：Key 缓存 TTL，默认 300 秒
# AUTH_CACHE_TTL=300
```

设置后重启 API 服务生效。

---

## 2. CLI 管理（服务器本地操作）

需要 SSH 到服务器，在项目根目录执行。

### 2.1 创建 Key

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

### 2.2 列出所有 Key

```bash
python manage_keys.py list
```

输出表格包含：ID、Prefix、是否启用、名称、邮箱、创建时间、最后使用时间。

### 2.3 禁用 Key

```bash
python manage_keys.py revoke --prefix "lw-a3f8c7e2"
```

禁用后该 Key 立即无法使用（缓存 TTL 过期后生效，默认最长 5 分钟）。

### 2.4 重新启用 Key

```bash
python manage_keys.py activate --prefix "lw-a3f8c7e2"
```

### 2.5 永久删除 Key

```bash
python manage_keys.py delete --prefix "lw-a3f8c7e2"
```

---

## 3. 管理员 API（远程操作）

无需 SSH，在任何地方通过 HTTP 调用。所有请求需携带 `X-Admin-Secret` 头。

### 3.1 创建 Key

```bash
curl -X POST http://210.45.70.162:4000/admin/keys \
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

### 3.2 列出所有 Key

```bash
curl http://210.45.70.162:4000/admin/keys \
  -H "X-Admin-Secret: your-secret-here"
```

### 3.3 禁用 Key

```bash
curl -X POST http://210.45.70.162:4000/admin/keys/lw-a3f8c7e2/revoke \
  -H "X-Admin-Secret: your-secret-here"
```

### 3.4 重新启用 Key

```bash
curl -X POST http://210.45.70.162:4000/admin/keys/lw-a3f8c7e2/activate \
  -H "X-Admin-Secret: your-secret-here"
```

### 3.5 删除 Key

```bash
curl -X DELETE http://210.45.70.162:4000/admin/keys/lw-a3f8c7e2 \
  -H "X-Admin-Secret: your-secret-here"
```

---

## 4. 常见操作场景

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

## 5. 数据文件

| 文件 | 说明 |
|------|------|
| `corpus/auth.db` | API Key 数据库（SQLite），已在 `.gitignore` 中排除 |
| `.env` | 包含 `ADMIN_SECRET` 等敏感配置，已在 `.gitignore` 中排除 |

> 备份服务器时请一并备份 `corpus/auth.db`，否则所有 Key 将丢失。
