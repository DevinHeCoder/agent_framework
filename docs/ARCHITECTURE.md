# 架构说明

> 配套阅读：[架构图](../docs/architecture.svg)（SVG 可视化）与 README 中的 Mermaid 分层图。

## 设计目标

市面 Agent 大多是一次性脚本：工具写死在业务里、无记忆、无状态、无法复用。本项目把 **工具、规划、记忆、容错** 做成可插拔、可复用、可部署的六层流水线：

```
用户请求（HTTP / CLI）
   │
   ▼
P5 API 服务层     FastAPI 路由 · AgentService · SessionManager
   │
   ▼
P4 Agent 核心      ReactAgent（plan → execute → respond）· LLMPlanner · RetryPolicy
   │
   ▼
P3 LLM 客户端      fake（无 Key 演示） / openai_compatible（OpenAI 兼容协议）
   │
   ▼
P2 记忆层          BaseMemory → in_memory / redis / hybrid（冷热分层）
   │
   ▼
P1 工具层          工具注册中心 · validator 参数校验 · 4 个内置工具
   │
   ▼
P0 公共基础        Registry 泛型注册表 · 分层异常 · YAML 配置 · 日志 · JSON 容错解析
```

## 每层的"三件套"模式

每层统一为「**抽象基类定义契约 → Registry 管理实现 → @register 装饰器注册**」：

| 层 | 抽象基类 | Registry | 注册实现 |
|----|----------|----------|----------|
| 工具 | `BaseTool` | `tool_registry` | calc / time / weather / kb_search |
| 记忆 | `BaseMemory` | `memory_registry` | in_memory / redis / hybrid |
| LLM | `LLMClient` | `llm_registry` | fake / openai_compatible |
| 规划 | `BasePlanner` | `planner_registry` | llm |
| Agent | `BaseAgent` | `agent_registry` | react |

**新增能力 = 新增一个实现文件 + 一行 `@register`，改 YAML 启用，零侵入。** 这是框架对"可插拔"的具体定义。

## 一次请求的完整链路

1. **会话挂载**：`POST /api/v1/chat` → `SessionManager.get_or_create(session_id)`（幂等，多轮复用）。
2. **任务拆解**：`LLMPlanner` 把用户指令拆成多步 JSON 计划（强制 JSON 输出，`json_parser` 容错解析，`max_steps` 截断，自动补 `respond` 收尾步）。
3. **逐步执行**：`ReactAgent` 顺序执行每步——注册中心取工具 → `validator` 按 schema 校验参数 → 执行 → 观察结果写回记忆与轨迹。
4. **容错决策**：异常按语义路由——`ToolNotFound` 换工具 / `ToolParam` 回喂 LLM 自愈 / `ToolExecution` 指数退避重试后兜底。
5. **生成回答**：最后一步 `respond` 把工具观察结果交给 LLM 综合成自然语言，记录完整 `TraceEntry` 轨迹。
6. **持久化**：`hybrid` 记忆写时双写（内存 + Redis），重启后冷启动恢复；会话元数据由 `SessionManager` 维护。

## 容错设计（与 LangChain 默认行为的差异点）

```
错误类型 = 决策依据
├─ ToolNotFoundError → 引导 LLM 换工具 / 跳过该步
├─ ToolParamError    → 回喂 LLM 重新生成参数（param_fix_attempts 上限防死循环）
└─ ToolExecutionError → RetryPolicy 指数退避重试 → 兜底回答（流程不崩）
```

- 所有异常**收敛在 Agent 层**，不向 API 泄漏（响应始终含 `answer` + `trace` + `success`）。
- `RetryPolicy` 统一管理重试次数、退避策略与兜底，测试可通过配置注入验证。

## 记忆分层

| 实现 | 特性 | 适用 |
|------|------|------|
| `in_memory` | 滑动窗口（限条数/容量） | 单进程演示、测试 |
| `redis` | TTL 过期 + session_id 前缀隔离 | 多实例共享长时记忆 |
| `hybrid` | 写时双写 + 冷启动从 Redis 预载回内存 | 生产默认推荐 |

## 可测试性

- 121 个 pytest 用例逐层覆盖；`fake` LLM 驱动全链路（无需任何 Key）。
- Redis 集成测试：本机有 Redis 自动真实运行，无 Redis 自动 `skip`（CI 兼容）。
- `examples/validate_real_llm.py`：真实 LLM 端到端验证脚本（6 场景 + 多轮记忆），可作交付信任证据。
