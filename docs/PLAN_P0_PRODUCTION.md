# P0 生产化开发计划（交付前必补五项）

> 目标：把 agent_framework 从"演示级项目"提升为"可交付级产品"。
> 原则：所有改动先在本地实现并验证，再同步服务器与 GitHub。
> 顺序：P0-3 密钥管理 → P0-1 可观测性 → P0-4 安全加固 → P0-2 备份恢复 → P0-5 压测容量。
> 总工作量：约 7~8 个工作日。

---

## P0-1 错误监控与可观测性（约 2 天）

**目标**：任何异常能第一时间被发现；客户能自主查看系统健康状态；一次请求可从日志完整回放。

### 涉及文件
- `src/api/main.py`（FastAPI 入口）
- `src/common/logger.py`、`config/logging.yaml`
- 新增 `src/monitoring/`（可观测性模块）
- `requirements.txt`（可选 sentry-sdk）

### 执行步骤
1. **健康检查端点**
   - `GET /healthz`：进程存活探针，返回 `200 {"status":"ok","version":...}`，不依赖任何外部组件。
   - `GET /readyz`：就绪探针，依次检查 Redis ping、配置加载、LLM client 初始化状态；任一失败返回 `503` 并列出失败项。用 try/except 包住每个检查，禁止探针自身抛 500。
2. **结构化日志**
   - `logging.yaml` 增加 JSON formatter：`time / level / module / msg / request_id / session_id / tool / step / duration_ms / retry_count`。
   - 在 API middleware 中生成 `request_id`（uuid4 短版）并注入日志 context，全链路复用。
3. **全局异常兜底**
   - FastAPI 增加 `@app.exception_handler(Exception)`：返回统一错误 JSON（`code/message/request_id`），同时记录完整 traceback；复用现有 `LLMError / ToolError / PlanError` 异常体系区分错误类型与 HTTP 状态码。
4. **Agent 执行链路追踪**
   - 在 Agent 执行循环（planner → tool → memory）每步打结构化 trace 日志：步骤序号、选中工具、入参摘要、耗时、重试次数、成功/失败。
   - 会话结束时输出一条 summary 日志（总步数、总耗时、结果状态）。
5. **可选 Sentry（可插拔）**
   - `config/settings.yaml` 增加 `MONITORING_SENTRY_DSN`（默认空）。
   - DSN 非空才 `sentry_sdk.init(...)`，为空则完全跳过（客户私有化环境不依赖云服务）。
6. **测试与验收**
   - 新增 `tests/test_health.py`：`/healthz` 200；停 Redis 后 `/readyz` 503；伪造工具异常时响应含 `request_id`。
   - 验收：本地启动，`curl /healthz` 返回 200；制造一次工具失败，日志中出现完整 JSON 链路且可按 request_id 串起；`/readyz` 在 Redis 停止时返回 503。

---

## P0-2 备份与恢复（约 1 天）

**目标**：会话、用量、记忆数据不因 Redis 崩溃/容器重启丢失；提供可执行的备份与恢复流程。

### 涉及文件
- `docker-compose.yml`（redis 服务）
- 新增 `scripts/backup.py`（或 `_deploy/backup.py`）
- 新增 `docs/RECOVERY.md`

### 执行步骤
1. **Redis 持久化**
   - `docker-compose.yml` 的 redis 服务增加：`command: redis-server --appendonly yes --appendfsync everysec`。
   - 确认 redis 已有 volume 挂载（如 `redis-data:/data`），没有则补。
2. **数据落盘兜底**
   - 核查 session 持久化路径：若会话/用量只存 Redis，在 `src/session/` 增加"定期快照"任务（每 5 分钟把活跃会话导出为 JSON 到挂载卷），作为双写兜底。
   - 用量数据若为 SQLite 文件，确保其落在持久化 volume 且纳入备份清单。
3. **备份脚本**
   - `scripts/backup.py`：连接 Redis 执行 `BGSAVE` → 拷贝 `dump.rdb` + AOF 到 `backup/`（带日期目录）→ 导出会话快照 JSON → 打包为 `agent-backup-YYYYMMDD.tar.gz` → 只保留最近 7 份。
4. **定时执行**
   - 服务器 cron：`0 3 * * *`（每日凌晨 3 点）执行备份脚本；脚本本身支持 `--dry-run` 便于验证。
5. **恢复文档**
   - `docs/RECOVERY.md`：分场景写清恢复步骤（Redis 数据恢复 / 会话快照回灌 / 整机重建），并写明"恢复演练"操作。
6. **测试与验收**
   - 验收：docker-compose 起 redis（appendonly on）→ 写入会话数据 → `docker compose stop redis` 再 start → 数据仍在；执行 `backup.py` 产出 tar.gz；按 RECOVERY.md 演练一次恢复成功。

---

## P0-3 密钥管理（约 1 天）

**目标**：密钥不进代码、不进镜像、不进日志；客户环境可独立注入；裸奔配置在启动时被拒绝。

### 涉及文件
- `.gitignore`（确认 .env 已忽略）
- `config/settings.yaml`、`src/config/`（加载层）
- `docker-compose.yml`
- 新增 `docs/SECURITY.md`
- `src/common/logger.py`（脱敏 filter）

### 执行步骤
1. **密钥扫描**
   - 全仓 grep 扫描 `sk-`、`password`、`api_key = "`、`Bearer ` 硬编码；发现即移入 `.env`（已被 .gitignore 忽略）。
   - 确认 `.env.example` 只含占位符，不含真实值。
2. **注入规范（写进 docs/SECURITY.md）**
   - 三种注入方式：① docker `env_file: .env`；② 系统环境变量（compose 直接读宿主环境）；③ 外部密钥管理（如 1Password/Vault，通过环境变量透传）。
   - 说明现有机制：`.env → settings.yaml 的 ${VAR:默认} 展开 → AGENT_ 前缀多级覆盖`，客户只需配 `AGENT_LLM__API_KEY` 等。
3. **生产 fail-fast**
   - `config/settings.yaml` 增加 `APP_ENV`（默认 development）。
   - 加载逻辑：`APP_ENV=production` 时，若 `LLM_API_KEY` 为空或等于 `.env.example` 占位符 → 启动抛错并拒绝启动（防裸奔）。
4. **日志脱敏**
   - `logger.py` 加 filter：对 `sk-[a-zA-Z0-9]+`、`Authorization: Bearer ...` 等模式打码。
   - 工具入参摘要中若含疑似密钥（长串 token），截断为前 4 位 + `***`。
5. **测试与验收**
   - 新增 `tests/test_secrets.py`：production + 空 key → 启动抛错；日志 filter 能打码明文 key。
   - 验收：`grep -r "sk-" src/ config/`（除脱敏正则）无真实密钥；本地以 production 模式无 key 启动直接报错；写一条含 key 的日志确认被打码。

---

## P0-4 安全加固（约 1.5 天）

**目标**：防 SSRF、防跨域滥用、依赖无已知高危漏洞、请求体可控。

### 涉及文件
- 新增 `src/common/net.py`（URL 校验器）
- `src/tool/`（weather / kb_search 等外部调用工具）
- `src/api/main.py`（CORS、安全响应头、body 限制）
- `.github/workflows/`（依赖扫描 CI）
- `docs/SECURITY.md`（扫描命令）

### 执行步骤
1. **SSRF 防护**
   - `src/common/net.py` 实现 `validate_public_url(url)`：
     - 仅允许 `http/https`；
     - 解析 host 后检查 IP：拒绝环回（127/8、::1）、内网（10/8、172.16/12、192.168/16）、链路本地（169.254/16）、云元数据（169.254.169.254）；
     - 拒绝 `localhost` 等内网主机名，DNS 解析结果再次校验（防 DNS rebinding）；
     - 支持配置 `SECURITY_BLOCKED_HOSTS` 追加黑名单。
   - 天气、检索等所有工具在发起外部请求前调用该校验器。
2. **CORS 白名单**
   - `config/settings.yaml` 增加 `SECURITY_CORS_ORIGINS`（默认仅同源 `[]`）。
   - main.py 中间件按白名单动态生成 `allow_origins`，禁止 `*`。
3. **安全响应头**
   - middleware 统一加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Content-Security-Policy: default-src 'self'`（前端接口场景按需放宽）。
4. **请求约束**
   - 确认限流（60/min）覆盖全部端点（含 usage/chat）；按压测结果校准（见 P0-5）。
   - 请求体大小限制（如 1MB），超限返回 413。
5. **依赖漏洞扫描**
   - `requirements.txt` 全部固定精确版本（去掉 `>=`）。
   - 新增 CI job：`pip install pip-audit && pip-audit`，高危漏洞阻止合并。
   - 文档化本地命令：`pip-audit -r requirements.txt`。
6. **测试与验收**
   - 新增 `tests/test_security.py`：校验器拒绝 `http://169.254.169.254/`、`http://127.0.0.1/`、`http://192.168.1.1/`，放行公网 URL；跨域请求被 CORS 拒绝。
   - 验收：安全测试全绿；`pip-audit` 无 high/critical；浏览器跨域调用被拒。

---

## P0-5 压测与容量（约 2 天）

**目标**：产出真实容量结论（单机并发上限、P95 延迟、建议限流值），支撑容量规划与部署建议。

### 涉及文件
- 扩展 `examples/benchmark.py`（或新增 `examples/load_test.py`）
- 新增 `docs/CAPACITY.md`
- `docker-compose.yml`（资源上限）

### 执行步骤
1. **压测脚本**
   - `examples/load_test.py`：基于 httpx 并发请求 `/api/v1/chat`（或 agent 端点），支持参数：并发数（10/20/50/100）、持续时间（60s）、模式（`fake` 框架自身吞吐 / `real` 千问端到端）。
   - 统计：QPS、P50/P95/P99 延迟、错误率、成功率；输出 JSON 报告。
2. **分档测试**
   - fake 模式测框架极限（纯框架开销）；real 模式测端到端（含 LLM 网络延迟）。
   - 每种并发档跑 60s，采样 3 次取中位数。
3. **资源观测**
   - 压测同时记录容器 CPU/内存峰值（`docker stats --format` 或 cAdvisor 简版脚本）。
4. **结论沉淀**
   - `docs/CAPACITY.md`：写明测试机规格（CPU/内存/网络）、容器资源限制、各档位 QPS/P50/P95/错误率表格、结论（建议最大并发、是否需横向扩展、限流建议值）。
5. **限流校准**
   - 根据容量结论调整 `RATE_LIMIT` 默认值（避免过度保守或超卖）；在 docs/CAPACITY.md 记录调整依据。
6. **资源上限**
   - `docker-compose.yml` 给 agent-app 加 `mem_limit`（如 1g）与 `cpus`（如 1.0），防单客户打满整机；在 README 部署章节说明可调。
7. **测试与验收**
   - 验收：`docs/CAPACITY.md` 有真实测试数字；能回答"单机支持 N 并发、P95 延迟 X ms、错误率 < Y%"；限流值与容量结论一致。

---

## 执行顺序与依赖

```text
P0-3 密钥管理（安全基础，最先）
  ↓
P0-1 可观测性（开发过程即可用，便于后续排障）
  ↓
P0-4 安全加固（复用 P0-1 的中间件结构）
  ↓
P0-2 备份恢复（上线前完成，独立无依赖）
  ↓
P0-5 压测容量（最后，产出容量结论支撑容量规划）
```

每项完成标准：代码改动在本地 + 测试通过 → 本地全量回归（现有 146 测试不回归）→ 部署服务器验证 → 再同步 GitHub。
