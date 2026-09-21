# API 文档

Base URL：`http://localhost:8000`（Docker 部署后为宿主机 8000 端口）

## 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（探针用） |
| GET | `/` | 服务信息与各层选型 |
| POST | `/api/v1/chat` | 多轮对话（核心入口） |
| GET | `/api/v1/tools` | 已启用工具 schema 列表 |
| GET | `/api/v1/sessions` | 会话列表（最近活跃倒序） |
| DELETE | `/api/v1/sessions/{session_id}` | 删除会话（联动清空记忆） |

## 核心接口：POST /api/v1/chat

### 请求

```json
{
  "query": "帮我查一下杭州天气，然后计算 2**10 等于多少",
  "session_id": "demo-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 用户指令 |
| `session_id` | string | 否 | 缺省自动创建；传入已存在 ID 则继续多轮上下文 |

### 响应

```json
{
  "session_id": "demo-001",
  "answer": "综合结果：杭州今天 26°C，小雨；2**10 = 1024",
  "success": true,
  "steps_taken": 3,
  "trace": [
    {"step_id": 1, "action": "weather", "args": {"city": "杭州"}, "observation": "{...}", "status": "success"},
    {"step_id": 2, "action": "calc", "args": {"expression": "2**10"}, "observation": "{...}", "status": "success"},
    {"step_id": 3, "action": "respond", "args": {}, "observation": "...", "status": "success"}
  ]
}
```

| 字段 | 说明 |
|------|------|
| `answer` | 最终回答文本 |
| `success` | 是否完全成功（false = 已走兜底策略，流程未中断） |
| `steps_taken` | 实际执行步数 |
| `trace` | 全链路执行轨迹（每步工具 + 参数 + 观察 + 状态），可直接透传给前端展示 |

### 多轮记忆语义

- 同一 `session_id` 连续调用即多轮对话：短时记忆（内存滑动窗口）+ 长时记忆（Redis TTL，可选）自动保持上下文。
- `hybrid` 模式下服务重启后，`session_id` 会话可从 Redis 冷启动恢复。

## 其他接口示例

```bash
# 工具列表
curl http://localhost:8000/api/v1/tools

# 会话列表
curl http://localhost:8000/api/v1/sessions

# 删除会话（联动清空该会话全部记忆）
curl -X DELETE http://localhost:8000/api/v1/sessions/demo-001
```

## 错误处理

| 情况 | 行为 |
|------|------|
| 请求体非法 | 400（FastAPI 自动校验） |
| 工具不存在 | 不报 500：Agent 引导换工具或跳过，`trace` 中标记失败 |
| 参数校验失败 | 回喂 LLM 自动修正（上限后降级兜底），`success=false` |
| 工具执行异常 | 指数退避重试后兜底，流程不崩 |

> 设计原则：**异常不向 API 层泄漏**，全部收敛为 `success` + `trace`，前端只需渲染。
