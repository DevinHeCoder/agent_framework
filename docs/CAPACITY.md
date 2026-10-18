# 容量评估与压测结论（CAPACITY）

> P0-5 目标：产出真实容量结论（单机并发上限、P95 延迟、建议限流值），支撑容量规划与部署建议。
> 方法：本地 fake 模式压测框架吞吐 → 服务器 real 模式端到端校准 → 沉淀本表。
> 原始数据：examples/load_report_fake20.json、examples/load_report_fake50.json。

---

## 1. 测试环境

| 项 | 本机压测环境 |
| --- | --- |
| 机器 | Windows 开发机（Docker Desktop 未启动，直接 uvicorn 进程） |
| CPU / 内存 | 未知（未做资源限制，反映单进程原始吞吐） |
| Python | 3.14.6 |
| 服务 | `uvicorn src.api.main:app`，fake LLM 模式（无外部网络调用） |
| 压测工具 | examples/load_test.py（httpx 异步并发） |

## 2. 实测结果（fake 模式 = 框架自身吞吐，不含 LLM 网络延迟）

| 并发 | 时长 | 总请求 | QPS | P50 | P95 | P99 | 成功率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 10s | 3,831 | 383.1 | 29.7ms | 33.9ms | 84.2ms | 100% |
| 50 | 10s | 6,407 | 640.7 | 75.9ms | 81.9ms | 153.6ms | 100% |

观察：
- 并发 20→50，QPS 383→640（+67%），P95 34→82ms——吞吐随并发增长，但单请求延迟因排队上升；
- 无错误、无超时，说明限流（60/min/Key）与鉴权中间件在高并发下无明显瓶颈；
- fake 模式不含 LLM 延迟，仅代表框架开销（规划+工具调度+记忆写回+日志）。

## 3. real 模式（端到端）预期模型

真实部署（生产环境，千问 qwen3-max）下，单请求延迟由 LLM 决定：

| 项 | 估算 |
| --- | --- |
| 单次任务 LLM 调用次数 | 1 次规划 + 1~2 次工具步骤 + 1 次回答 ≈ 3~4 次 |
| 单次 LLM 往返 | 约 1~3s（千问在线延迟，取决于模型与负载） |
| 端到端单请求 | 约 3~12s |
| 建议在线并发上限 | 5~10（单机，受 LLM 并发与成本约束） |
| 建议限流 | 5~10 req/min/Key（客户环境默认 60 过于宽松，交付时按套餐收紧） |

> 服务器 real 压测待部署后执行：`python examples/load_test.py --mode real --url https://<your-host> --api-key <key> --concurrency 5 --duration 60`，
> 结果回填本表第 3 节。

## 4. 结论与建议（容量规划 / 部署用）

1. **框架层**：单进程 fake 吞吐 ≥ 380 QPS（20 并发），框架自身不是瓶颈；
2. **瓶颈在 LLM**：容量由模型延迟与成本决定，不推荐用高并发压真实模型（会烧额度、触发限流）；
3. **部署建议**：
   - 单机承载 5~10 在线并发即可覆盖中小型客户（客服机器人、内部知识问答）；
   - 客户量上升时横向扩展：`docker compose up --scale agent-app=2`（前端会话按 session_id 隔离，Redis 共享，天然可水平扩展）；
   - 资源上限已配置：agent-app `mem_limit: 1g` / `cpus: 1.0`（防单客户打满整机）。
4. **限流校准**：默认 `AGENT_AUTH_RATE_LIMIT=60` 仅作演示；交付时按套餐设置 10~30 req/min，并在 SLA 中写明超限返回 429。

## 5. 复现方法

```bash
# 1) 本地起服（fake）
AGENT_LLM_PROVIDER=fake uvicorn src.api.main:app --host 127.0.0.1 --port 8100

# 2) 压测（每档建议 60s × 3 次取中位数）
python examples/load_test.py --url http://127.0.0.1:8100 --concurrency 20 --duration 60
python examples/load_test.py --url http://127.0.0.1:8100 --concurrency 50 --duration 60
```
