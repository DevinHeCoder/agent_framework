# 配置与环境变量

所有运行时选型集中在 `config/settings.yaml`，支持两种覆盖方式，**运行时切换实现不碰代码**。

## 覆盖机制

1. **`${ENV_VAR}` / `${ENV_VAR:默认值}`**：YAML 中直接展开环境变量，用于密钥等敏感信息。未设置且无默认值时启动即报 `ConfigError`（避免静默用错配置）。
2. **`AGENT_` 前缀 + 双下划线**：`AGENT_LLM__MODEL=x` 等价于覆盖 YAML 中 `llm.model` 路径。

## 配置表

### app / logging

| 路径 | 默认 | 说明 |
|------|------|------|
| `app.name` | `agent_framework` | 服务名（健康检查返回） |
| `app.version` | `0.1.0` | 版本号 |
| `logging.config_path` | `config/logging.yaml` | 日志配置 |

### P1 工具层

| 路径 | 默认 | 说明 |
|------|------|------|
| `tool.enabled` | `["calc","time","weather","kb_search"]` | 启用工具白名单（= 暴露给 LLM 的能力） |
| `tool.retry` | `2` | 工具执行失败重试次数 |
| `tool.param_fix_attempts` | `2` | 参数校验失败回喂 LLM 修正的最大次数 |

### P2 记忆层

| 路径 | 默认 | 说明 |
|------|------|------|
| `memory.provider` | `${AGENT_MEMORY_PROVIDER:in_memory}` | `in_memory` / `redis` / `hybrid` |
| `memory.short_term.window_size` | `20` | 短时滑动窗口消息条数 |
| `memory.long_term.ttl_seconds` | `86400` | 长时记忆 TTL（秒） |
| `memory.long_term.redis_url` | `${AGENT_REDIS_URL:redis://localhost:6379/0}` | Redis 连接 |

### P3 LLM 客户端

| 路径 | 默认 | 说明 |
|------|------|------|
| `llm.provider` | `${AGENT_LLM_PROVIDER:fake}` | `fake`（无 Key 演示）/ `openai_compatible` |
| `llm.base_url` | `${AGENT_LLM_BASE_URL:}` | OpenAI 兼容端点（Ollama/DeepSeek/通义/豆包…） |
| `llm.api_key` | `${AGENT_LLM_API_KEY:}` | API Key |
| `llm.model` | `${AGENT_LLM_MODEL:}` | 模型名 |
| `llm.temperature` | `0.2` | 采样温度 |
| `llm.max_tokens` | `1024` | 单次生成上限 |

### P4 规划层 / Agent 核心

| 路径 | 默认 | 说明 |
|------|------|------|
| `planner.provider` | `llm` | `llm`（LLM 拆解）/ `none`（不拆解） |
| `planner.max_steps` | `6` | 单任务最大规划步数 |
| `agent.provider` | `react` | Agent 实现 |
| `agent.max_loop` | `5` | 最大工具调用轮次（防死循环） |
| `agent.json_parse_retries` | `2` | LLM 输出 JSON 解析失败重试轮次 |

### P5 服务

| 路径 | 默认 | 说明 |
|------|------|------|
| `server.host` | `0.0.0.0` | 监听地址 |
| `server.port` | `8000` | 监听端口 |

## 完整真实 LLM 配置示例（环境变量方式）

```bash
# Linux / macOS
export AGENT_LLM_PROVIDER=openai_compatible
export AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
export AGENT_LLM_MODEL=deepseek-chat
export AGENT_LLM_API_KEY=sk-xxx
export AGENT_MEMORY_PROVIDER=hybrid
export AGENT_REDIS_URL=redis://localhost:6379/0

# Windows PowerShell
set AGENT_LLM_PROVIDER=openai_compatible
set AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
set AGENT_LLM_MODEL=deepseek-chat
set AGENT_LLM_API_KEY=sk-xxx
```

> 说明：框架本体对 `provider` 为 `fake` 时**不读取** `api_key/base_url/model`（避免误配置报错）；
> 为 `openai_compatible` 时才要求这三个字段合法。
