# 密钥与安全配置规范（SECURITY）

本文件说明 agent_framework 的密钥管理规范、客户环境注入方式与生产环境安全基线。
对应 P0-3 密钥管理 / P0-4 安全加固。

---

## 1. 密钥存放原则

- **密钥只允许出现在 `.env`**（已被 `.gitignore` 忽略），或部署平台的环境变量 / 密钥管理服务中；
- **禁止**：硬编码在源码、提交进 git 历史、写进 Docker 镜像（`ENV`/`ARG`）、出现在日志；
- **占位示例**：`.env.example` 中所有值为占位符（如 `sk-你的百炼APIKey`），不含真实密钥。

### 本地

```bash
cp .env.example .env   # 然后填入真实值
```

项目启动时 `config_loader.load_dotenv()` 自动读取项目根目录 `.env`；
已存在的系统环境变量优先，`.env` 不会覆盖它们。

### Docker 部署（推荐 env_file）

```yaml
services:
  agent-app:
    env_file: .env          # 密钥不进 compose 文件、不进镜像层
    environment:
      AGENT_LLM_PROVIDER: ${AGENT_LLM_PROVIDER:-fake}
```

### 云平台 / 密钥管理服务

1. 在平台注入环境变量（如 1Password/Vault 导出为环境变量）；
2. 保持 compose 中 `AGENT_LLM_API_KEY: ${AGENT_LLM_API_KEY:-}` 写法，让值来自宿主环境；
3. 绝不要把密钥明文写进 CI 配置、部署脚本或聊天记录。

---

## 2. 配置覆盖机制（客户只需配环境变量）

`.env → config/settings.yaml 的 ${VAR:默认} 展开 → AGENT_ 前缀多级路径覆盖`：

| 配置项 | 环境变量 |
| --- | --- |
| LLM API Key | `AGENT_LLM_API_KEY` |
| LLM Base URL | `AGENT_LLM_BASE_URL` |
| LLM 模型 | `AGENT_LLM_MODEL` |
| 运行环境 | `AGENT_APP_ENV`（development / production）|
| 鉴权开关 | `AGENT_AUTH_ENABLED` |
| 访问令牌 | `AGENT_AUTH_TOKEN` |
| 限流 | `AGENT_AUTH_RATE_LIMIT` |

---

## 3. 生产环境防裸奔（fail-fast）

`AGENT_APP_ENV=production` 启动时，`validate_runtime_security()` 强制校验：

- **LLM 为真实 provider（非 fake）且 API Key 为空或占位值 → 启动直接报错**，拒绝运行；
- 生产环境未开启 API 鉴权 → 输出告警日志（建议 `AGENT_AUTH_ENABLED=true`）。

本地开发默认 `AGENT_APP_ENV=development`，不触发上述校验。

## 4. 日志脱敏

所有日志输出经过 `RedactingFormatter`（`src/utils/logger.py`）统一打码：

- `sk-xxxx...` 格式密钥 → `sk-***`；
- `Authorization: Bearer <token>` → `Bearer ***`；
- `api_key= / password= / token= ...` 键值对 → `key=***`。

保证密钥不会因工具入参、异常信息、调用链路日志而落盘。

## 5. 安全加固配置（P0-4）

| 配置项 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| CORS 白名单 | `AGENT_SECURITY_CORS_ORIGINS` | 空（仅同源） | 逗号分隔；禁止 `*` |
| SSRF 追加黑名单 | `AGENT_SECURITY_BLOCKED_HOSTS` | 空 | 逗号分隔的主机名 |
| 请求体上限 | `AGENT_SECURITY_MAX_BODY_MB` | 1 | 超限返回 413 |

- **SSRF**：`src/common/net.py::validate_public_url()` 在工具发起外部请求前调用；拒绝
  环回/内网/链路本地/CGNAT/云元数据地址，域名解析后复验解析 IP（防 DNS rebinding）。
  当前 weather / kb_search 为 mock 实现，接入真实外部工具时必须先调用该校验器。
- **安全响应头**：统一注入 `X-Content-Type-Options: nosniff`、
  `X-Frame-Options: DENY`、`Content-Security-Policy`（前端控制台放行内联样式/脚本）。
- **请求体限制**：超过 `max_body_mb` 的请求直接返回 413 `PayloadTooLarge`。

## 6. 定期检查命令

```bash
# 扫描源码中的疑似硬编码密钥（应无输出）
# 注意：脱敏正则本身会命中，扫描时排除 src/common/security.py
rg -n "sk-[A-Za-z0-9]{10,}" --glob '!src/common/security.py' .

# 依赖漏洞扫描
pip-audit -r requirements.txt
# 验收基线：无 high/critical 漏洞（P0-4 实测 No known vulnerabilities found）
```

## 7. 权限与泄露处置

- 密钥疑似泄露：立即到百炼控制台 **吊销/重置该 Key**，然后更新 `.env` 并重新部署；
- 日志中发现明文密钥：说明脱敏未覆盖该模式，请提交 issue 补充 `_REDACT_PATTERNS`。
