# 部署指南（Docker 一键编排）

默认编排 **app + Redis** 两个容器：app 提供 Agent API 服务，Redis 承载长时记忆（hybrid 双缓存冷热分层）。

## 1. 前置条件

- Docker Engine ≥ 24（含 compose 插件）
- （可选）真实 LLM 的 API Key；不配则用内置 fake LLM 演示

## 2. 一键启动

```bash
docker compose up --build -d

# 确认两个容器健康
docker compose ps
```

| 容器 | 说明 | 端口 |
|------|------|------|
| agent-app | FastAPI 服务（healthcheck 自动恢复） | 8000 |
| agent-redis | Redis 7（长时记忆 TTL 存储） | 6379 |

## 3. 验证部署

```bash
curl http://localhost:8000/health
# {"status":"ok","app":"agent_framework","version":"0.1.0","enabled_tools":["calc",...]}

curl -X POST http://localhost:8000/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "帮我查一下杭州天气", "session_id": "deploy-test"}'
```

## 4. 接入真实 LLM

在 `.env`（与 docker-compose.yml 同目录）中配置，再重启：

```bash
# .env
AGENT_LLM_PROVIDER=openai_compatible
AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
AGENT_LLM_MODEL=deepseek-chat
AGENT_LLM_API_KEY=sk-xxxx
```

```bash
docker compose up -d   # 环境变量变化后重建容器
```

## 5. 记忆选型

| AGENT_MEMORY_PROVIDER | 行为 |
|-----------------------|------|
| `hybrid`（默认） | 短时内存 + 长时 Redis：写时双写、重启从 Redis 恢复 |
| `in_memory` | 仅内存（重启丢失），适合纯演示/单进程 |
| `redis` | 仅 Redis（依赖长时存储） |

```bash
# 示例：切换为纯内存
docker compose run -e AGENT_MEMORY_PROVIDER=in_memory agent-app
```

## 6. 运维

```bash
docker compose logs -f agent-app     # 查看服务日志
docker compose restart agent-app     # 重启服务
docker compose down                  # 停止（保留数据卷）
docker compose down -v               # 停止并清空 Redis 数据
```

## 7. 自定义与扩展

- **新增工具**：`src/tool/implementations/` 新增实现 + `config/settings.yaml` 的 `tool.enabled` 加入名字，重启即生效，无需改部署。
- **换记忆/LLM/规划器**：全部为 YAML/环境变量选型，见 [CONFIGURATION.md](CONFIGURATION.md)。
- **Dockerfile 安全基线**：多阶段构建、非 root 用户、依赖缓存分层、healthcheck 健康探针。
