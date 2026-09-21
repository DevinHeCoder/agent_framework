# 快速开始（5 分钟跑通）

本文档面向**第一次接触本项目的人**：5 分钟内从零跑通「安装 → 测试 → 无 Key 演示 → 真实 LLM → API 服务」。

## 0. 环境要求

- Python ≥ 3.10（开发环境 3.14 已验证）
- pip
- （可选）Docker / Ollama，用于 Redis 记忆与真实 LLM

## 1. 安装依赖（约 1 分钟）

```bash
pip install -r requirements.txt
```

## 2. 运行全部测试（约 30 秒）

```bash
python -m pytest tests -q
# 预期输出: 121 passed（Redis 集成测试在本机有 Redis 时自动真实运行）
```

## 3. 无 Key 端到端演示（约 1 分钟）

内置 fake LLM 驱动全链路，不需要任何 API Key：

```bash
python examples/run_agent_demo.py
```

```
你> 帮我查一下杭州天气
你> 计算一下 3*8
你> 现在几点了
你> 退出
```

也可以一键跑完三个业务场景（知识库问答 / 连续计算 / 多工具编排）：

```bash
python examples/scenarios/scenario_qa_knowledge.py
python examples/scenarios/scenario_calc_chain.py
python examples/scenarios/scenario_multi_tool.py
```

## 4. 切换真实 LLM（约 1 分钟）

框架使用 OpenAI 兼容协议，本地 Ollama 或任意云端模型均可：

```bash
# 方式 A · 本地 Ollama（免费）
ollama pull qwen2.5:7b
set AGENT_LLM_PROVIDER=openai_compatible
set AGENT_LLM_BASE_URL=http://localhost:11434/v1
set AGENT_LLM_MODEL=qwen2.5:7b
set AGENT_LLM_API_KEY=ollama

# 方式 B · DeepSeek / 通义 / 豆包等云端
set AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
set AGENT_LLM_MODEL=deepseek-chat
set AGENT_LLM_API_KEY=sk-xxx

# 跑真实模型端到端验证（6 个场景 + 多轮记忆）
python examples/validate_real_llm.py
```

## 5. 启动 API 服务（可选）

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "帮我算 (3+5)*2", "session_id": "demo-1"}'
```

## 下一步

| 想做什么 | 看这里 |
|----------|--------|
| 了解架构与分层 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Docker 一键部署（含 Redis 长时记忆） | [DEPLOYMENT.md](DEPLOYMENT.md) |
| API 完整文档与示例 | [API.md](API.md) |
| 配置项与全部环境变量 | [CONFIGURATION.md](CONFIGURATION.md) |
| 三个业务场景与扩展点 | [examples/scenarios/README.md](../examples/scenarios/README.md) |
