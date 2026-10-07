# API 部署指南

先完成 [本地配置](setup.md) 和 [语料库下载](data.md)。下面使用“宿主机 Python API + 独立 Qdrant Server”的部署方式。

## 1. 启动与验收 Qdrant

安装适配宿主机系统与 CPU 架构的 [Qdrant 二进制](https://github.com/qdrant/qdrant/releases)。发布的 `qdrant_storage.tar.gz` 是服务端存储目录归档，不是 `.snapshot` 文件，也不是嵌入式 Python 客户端数据库；恢复时应核对存储格式与 Qdrant 版本兼容性，不要盲目升级存储。

将二进制放在项目根目录并命名为 `qdrant`，或放到 `PATH`：

```bash
chmod +x qdrant
bash start_qdrant.sh
```

脚本使用 `config/qdrant_config.yaml`。存储路径是 `./corpus/qdrant_storage`，HTTP 端口 6333、gRPC 端口 6334。二进制服务必须从项目根目录启动，脚本会自动切换目录。

```bash
curl --fail http://localhost:6333/collections/papers
```

确认 `result.config.params.vectors.size` 为 1024、距离为 Cosine，点数量与所用语料版本合理对应。若没有 `papers` 集合，先核对下载包与解压路径。不要用其他集合名绕过错误。

### 可选：用 Docker 运行 Qdrant

根据数据存储兼容性选择并固定镜像版本，再执行下面的 Bash 命令：

```bash
export QDRANT_IMAGE=qdrant/qdrant:替换为兼容版本

docker run -d --name lewen-qdrant --restart unless-stopped \
  -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 \
  -v "$PWD/corpus/qdrant_storage:/qdrant/storage" \
  "$QDRANT_IMAGE"
```

Docker 挂载目录必须指向已解压的 `qdrant_storage/`，宿主机 API 仍通过 localhost:6334 连接。不要同时启动二进制服务和容器访问同一存储。持久化磁盘要求参见 [Qdrant 官方安装文档](https://qdrant.tech/documentation/installation/)。

## 2. 启动 API

在另一个终端进入项目并激活环境：

```bash
source .venv/bin/activate
bash start_api.sh
```

API 默认地址为 `http://localhost:4000`，OpenAPI 交互页面为 `http://localhost:4000/docs`。默认监听 `0.0.0.0`；仅本机试用时可将 `config.py` 中 `API_HOST` 改为 `127.0.0.1`。

`start_api.sh` 调用 `python main.py`，会读取 `UVICORN_WORKERS`、`UVICORN_TIMEOUT_KEEP_ALIVE` 和 `UVICORN_LIMIT_CONCURRENCY`。建议先使用 `.env.example` 的单 worker 配置，避免多个 worker 在同一 GPU 重复加载模型造成显存不足。

## 3. 启用 API Key

本地默认 `AUTH_ENABLED=false`。对外部署前修改 `.env`：

```dotenv
AUTH_ENABLED=true
ADMIN_SECRET=替换为随机生成的管理密钥
ADMIN_HOST=127.0.0.1
```

可用 `python -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成管理密钥。`ADMIN_SECRET` 仅用于管理接口，不能当作普通用户 API Key。

创建用户 Key：

```bash
python manage_keys.py create --name 'local-user' --email 'user@example.com'
```

保存只展示一次的 Key，再重启 API。启用鉴权后，在请求头添加 `X-API-Key`。`corpus/auth.db` 是本部署的鉴权数据，需单独备份；不要从开放语料复制他人的数据库。

## 4. 独立管理员服务

```bash
bash start_admin.sh
```

访问 `http://localhost:4100/admin/panel` 并输入 `ADMIN_SECRET`。该进程支持 Key 管理、状态检查、API 测试、压测与增量更新任务，修改或重启管理员后端不会重启 Paper API。

`main.py` 也包含 `/admin/*` 管理路由；采用独立看板不等于公开 API 已自动隔离所有管理端点。反向代理应只公开需要的 `/paper/*`，或显式阻断对外的 `/admin/*`，并将 Qdrant 与看板限制为本机 / 可信网络。详见 [管理员指南](api-key-admin.md)。

## 5. systemd 长期运行示例

以下示例适用于 Linux，将 `YOUR_USER` 和 `/srv/Lewen-API` 替换为实际用户和**绝对项目路径**。两个服务均依赖正确的工作目录；Qdrant 二进制假定放在项目根目录。

`/etc/systemd/system/lewen-qdrant.service`：

```ini
[Unit]
Description=Lewen Qdrant
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/srv/Lewen-API
ExecStart=/srv/Lewen-API/qdrant --config-path /srv/Lewen-API/config/qdrant_config.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/lewen-api.service`：

```ini
[Unit]
Description=Lewen Paper API
Wants=lewen-qdrant.service
After=network.target lewen-qdrant.service

[Service]
User=YOUR_USER
WorkingDirectory=/srv/Lewen-API
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/Lewen-API/.venv/bin/python /srv/Lewen-API/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

API 通过 `python-dotenv` 从工作目录读取 `.env`，无需额外把 `.env` 同时配置为 systemd `EnvironmentFile`。启动顺序不等于 Qdrant 已就绪，应先确认集合可以查询。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lewen-qdrant
curl --fail http://localhost:6333/collections/papers
sudo systemctl enable --now lewen-api
sudo systemctl status lewen-qdrant lewen-api
journalctl -u lewen-api -n 100 --no-pager
```

线上建议由 Nginx 等代理负责 HTTPS，并限制可访问的路由、请求量和超时。二进制 Qdrant 配置默认监听 `0.0.0.0`，仅本机使用时将 YAML 中 `service.host` 改为 `127.0.0.1` 或配置防火墙。

## 6. 验收与日志

关闭鉴权时可直接执行；开启后为各请求加上 `-H 'X-API-Key: lw-你的Key'`：

```bash
curl --fail --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' \
  --data-urlencode 'retrieval=sparse' --data-urlencode 'limit=5'

curl --fail --get 'http://localhost:4000/paper/search' \
  --data-urlencode 'query=transformer attention' \
  --data-urlencode 'retrieval=hybrid' --data-urlencode 'limit=5'

curl --fail 'http://localhost:4000/paper/search/title?query=Attention%20Is%20All%20You%20Need&limit=5'
curl --fail 'http://localhost:4000/paper/2309.06180?fields=*'
curl --fail 'http://localhost:4000/paper/1706.03762/references?limit=5'
```

逐项检查返回 HTTP 200、JSON 结构与论文结果合理。API 启动会捕获模型 / Qdrant 预热异常，端口已监听或 `/docs` 可访问不代表 hybrid 已可用。

| 日志 | 内容 |
| --- | --- |
| `logs/api.log` | API、模型预热、检索与鉴权 |
| `logs/admin.log` | 管理员服务 |
| `logs/admin_jobs/` | 管理员启动的后台任务 |
| systemd journal / Qdrant 终端输出 | 进程启动、服务端存储与版本错误 |

## 7. 更新与备份

数据更新参见 [增量更新指南](incremental-update.md)。更新前备份匹配版本的 `papers.db`（包括尚未 checkpoint 的 WAL）、Qdrant 数据与 `current_release.txt`，另存 `.env` 与 `auth.db`。

需要严格一致性时，暂停 API 和管理员更新任务后进行备份 / 更新，成功验收后再开放查询。不能把在线 SQLite 文件复制和在线 Qdrant 目录复制视为一致性备份；Qdrant 在线备份机制参见 [官方快照文档](https://qdrant.tech/documentation/snapshots/)。恢复时成套恢复同一 release 的数据库与向量索引。
