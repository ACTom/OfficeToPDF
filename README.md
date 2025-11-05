# OfficeToPDF API

基于 FastAPI + LibreOffice 的 Office 文档转 PDF 服务。

## 功能概述
- 同步与异步转换接口，支持 `--convert-to` 自定义参数，参数说明详见 [LibreOffice 文档](https://help.libreoffice.org/latest/zh-CN/text/shared/guide/pdf_params.html)。
- 异步任务查询状态与结果下载。
- 限制同时转换数量（信号量控制）。
- LibreOffice 超时自动杀进程并重试，超出重试次数失败。
- 简单鉴权（HTTP Header `X-API-Key`）。
- 请求与任务日志记录到 `LOG_DIR`。
- 文件自动清理任务（默认 3600 秒）。
- 提供在线测试界面 `/ui` 与自动生成的 API 文档 `/docs`。
- Docker 与 docker-compose 部署。

## 环境变量
- `APIKEY`: API 鉴权 Key（必填，默认 `changeme`）
- `CONVERT_TIMEOUT`: 转换超时时间（秒，默认 `600`）
- `MAX_CONCURRENCY`: 同时可转换数量（默认 CPU 核心数）
- `CLEANUP_AFTER_SECONDS`: 文件清理时间（秒，默认 `3600`）
- `LOG_DIR`: 日志目录（默认 `/tmp/o2plog`）
- `DATA_DIR`: 数据目录（默认 `/tmp/o2pdata`）
- `MAX_RETRIES`: 失败重试次数（不含首次，默认 `2`）
- `MAX_QUEUE_SIZE`: 队列长度上限（默认 `1000`，`0` 表示不限制）
- `JOB_RECORD_TTL_SECONDS`: 任务记录保留时长（默认 `86400`，一天）
- `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` / `LOG_LEVEL`: 日志轮转与级别，默认 `10MB` / `10` / `INFO`


使用步骤：
- 复制为 `.env` 并修改 `APIKEY` 等值：`cp .env.sample .env`
- Docker Compose 会自动读取 `.env`（同目录下）进行变量替换。
- 本地运行可加载 `.env`：
  - `set -a && source .env && set +a`
  - 或 `export $(grep -v '^#' .env | xargs)`
  然后执行 `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## 运行（本地）
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export APIKEY=yourkey
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
打开 `http://localhost:8000/ui` 测试，或访问 `http://localhost:8000/docs` 看 API 文档。

## Docker 运行
```bash
docker build -t officetopdf:latest .
APIKEY=yourkey docker run -p 8000:8000 officetopdf:latest
```
或使用 docker-compose：
```bash
APIKEY=yourkey docker compose up --build -d
```

## API 使用说明
- `POST /convert/sync`
  - Form: `file` (上传文件), `convert_to` (可选，如 `pdf:writer_pdf_Export`)
  - Header: `X-API-Key: <APIKEY>`
  - 返回: `{ job_id, status, download_url }`
- `POST /convert/async`
  - 同上，返回立即的 `{ job_id, status }`，可用 `/status/{job_id}` 查询。
- `GET /status/{job_id}`
  - Header: `X-API-Key: <APIKEY>`
  - 返回: `{ job_id, status, message?, download_url?, waiting_count?, retries? }`
    - `waiting_count`: 若任务在队列中，表示前面还有多少个任务
    - `retries`: 已尝试次数（从 0 计数），例如 2 表示第 3 次尝试
- `GET /download/{job_id}`
  - Header: `X-API-Key: <APIKEY>`
  - 下载转换后的 PDF。
 - `GET /health`
  - 返回: `{ status: "ok" }`（健康检查，无需鉴权）
 - `GET /system/status`
  - Header: `X-API-Key: <APIKEY>`
  - 返回系统运行状态与指标：
    - `uptime_seconds`, `convert_timeout`, `max_concurrency`, `cleanup_after_seconds`
    - `total_jobs`, `queue_length`, `running_jobs`, `done_jobs`, `failed_jobs`
    - `cpu_cores`
    - `data_dir_used_bytes`, `data_dir_free_bytes`
    - `log_dir_used_bytes`, `log_dir_free_bytes`

## 备注
- 部分复杂 Office 文档可能需要指定合适的 `--convert-to` 过滤器。
- 为减少资源占用，上传文件以流式方式保存。
 - 清理策略：从任务完成后的最后修改时间开始计算保留时间；清理后状态为 `cleaned`，记录会根据 TTL 回收。

## 协议
- 本项目基于 MIT 协议开源，您可以在遵守协议的前提下自由使用、修改和分发本项目的代码。

## 感谢
- 本项目基于 FastAPI 与 LibreOffice 构建，感谢开源社区的贡献。

## 其他
本项目使用 [Trae](https://trae.ai) 开发，初始提示词为：
```
现在请你编写一个 Office转PDF的API服务，要求如下：
功能要求：
1、转换服务使用 LibreOffice 实现
2、提供同步转换和异步转换两个API接口，API接口可选设置转换自定义参数，即 --convert-to 参数的内容
3、提供转换后文件下载接口，提供查询异步转换状态接口
4、限制同时转换数量，超出后将排队等待
5、LibreOffice 存在卡死的问题，超时将自动杀掉 LibreOffice，并重试，超出重试次数后将状态设置为转换失败
6、需提供 API 文档及在线测试界面
7、API 需简单鉴权
8、接口调用、转换状态等需记录日志
9、服务需在 docker 中运行，需提供 docker 构建文件和 docker-compose.yml 文件

可设置的环境变量：
1、APIKEY
2、转换超时时间（秒），默认值600
3、同时可转换数量，默认值为CPU内核数
4、文件清理时间（秒），默认值3600
5、日志存放目录，默认值/tmp/o2plog
```