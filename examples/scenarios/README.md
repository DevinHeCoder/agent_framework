# 示例场景库（业务场景示例）

每个场景均为**单文件自包含**脚本：无 Key 可跑（fake 模式），一行切换真实 LLM（OpenAI 兼容协议），
可直接复制进客户项目做原型验证。

| 场景 | 脚本 | 演示能力 | 运行 |
|------|------|----------|------|
| 1 · 知识库问答助手 | `scenario_qa_knowledge.py` | kb_search 检索（中文 bigram 分词）、多轮问答、知识库即插即换 | `python scenario_qa_knowledge.py` |
| 2 · 数学计算助手 | `scenario_calc_chain.py` | 安全计算器（ast 白名单）、多轮连续计算、非法表达式容错兜底 | `python scenario_calc_chain.py` |
| 3 · 多工具编排助手 | `scenario_multi_tool.py` | 一条指令多步规划、weather+calc+time 协同、结果综合回答 | `python scenario_multi_tool.py` |

## 快速开始

```bash
# 1. 安装依赖并跑通测试（可选）
pip install -r requirements.txt
python -m pytest tests -q

# 2. 无 Key 直接演示
python examples/scenarios/scenario_qa_knowledge.py
python examples/scenarios/scenario_calc_chain.py
python examples/scenarios/scenario_multi_tool.py
```

## 切换真实 LLM（三选一）

所有场景脚本都接受 `--provider openai_compatible`，配合环境变量即可：

```bash
# 方案 A · 本地 Ollama（免费，推荐演示）
set AGENT_LLM_PROVIDER=openai_compatible
set AGENT_LLM_BASE_URL=http://localhost:11434/v1
set AGENT_LLM_MODEL=qwen2.5:7b
set AGENT_LLM_API_KEY=ollama

# 方案 B · DeepSeek
set AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
set AGENT_LLM_MODEL=deepseek-chat
set AGENT_LLM_API_KEY=sk-xxx

# 方案 C · 任意 OpenAI 兼容端点（通义/豆包/智谱/OpenAI 等）

python examples/scenarios/scenario_qa_knowledge.py --provider openai_compatible
```

## 场景 → 业务转化点

| 客户场景 | 用哪个场景改 | 改什么 |
|----------|--------------|--------|
| 企业知识库问答（规章制度/产品手册/客服FAQ） | 场景 1 | 替换 `kb_search_tool.py` 的 `_DEFAULT_KB` 为客户的文档集 |
| 财务/报表计算助手 | 场景 2 | 增加计算类工具（汇率/利息/税） |
| 工作流编排（查询+计算+提醒组合） | 场景 3 | 挂接客户的真实工具（订单查询/库存/日程） |
| 多轮客户跟进对话 | 任一场景 | 开启 `hybrid` 记忆 + Redis，长时保存会话 |
