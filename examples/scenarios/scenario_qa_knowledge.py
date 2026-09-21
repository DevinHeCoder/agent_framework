"""场景 1 · 知识库问答助手（kb_search 检索 → 基于知识回答）。

演示能力:
    - 检索工具 kb_search 对内置知识库做关键词检索（中文 bigram 分词）
    - 多轮连续问答（同一会话，记忆保持上下文）
    - 无 Key 可跑（fake 模式）；接真实 LLM 一行切换

用法:
    # 演示模式（fake LLM，无需 Key）
    python examples/scenarios/scenario_qa_knowledge.py

    # 真实 LLM 模式（Ollama / DeepSeek 等 OpenAI 兼容端点）
    set AGENT_LLM_PROVIDER=openai_compatible
    set AGENT_LLM_BASE_URL=http://localhost:11434/v1
    set AGENT_LLM_MODEL=qwen2.5:7b
    set AGENT_LLM_API_KEY=ollama
    python examples/scenarios/scenario_qa_knowledge.py --provider openai_compatible

扩展为你的知识库:
    内置知识库在 src/tool/implementations/kb_search_tool.py 的 _DEFAULT_KB，
    改为 [{doc_id, title, content}, ...] 即可替换为任意文档集（定制点）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.service import AgentService
from src.llm_client import build_llm_client
from src.llm_client.fake import FakeLLMClient
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

logger = get_logger("agent_framework.scenario.qa")


# ---------------- fake 模式：模拟规划器（仅演示，非真实推理） ----------------
_KB_TRIGGERS = ("检索", "知识库", "记忆", "工具注册", "架构", "兜底", "规划", "会话", "失败")


def _plan_for(query: str) -> str:
    steps = []
    if any(k in query for k in _KB_TRIGGERS):
        steps.append({"action": "kb_search", "args": {"query": query}, "thought": "检索知识库"})
    if not steps:
        steps.append({"action": "respond", "args": {}, "thought": "直接回答"})
    steps.append({"action": "respond", "args": {}, "thought": "综合检索结果"})
    return json.dumps({"steps": steps}, ensure_ascii=False)


def _answer_for(content: str) -> str:
    if "工具观察结果" in content:
        obs = content.split("工具观察结果：", 1)[-1].split("\n规划建议", 1)[0]
        for ln in obs.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except (json.JSONDecodeError, TypeError):
                continue
            results = obj.get("results") or []
            if results:
                top = results[0]
                return f"知识库检索到《{top['title']}》：{top['content']}"
        return "知识库未检索到相关内容。"
    return "（演示模式）已收到你的请求。"


def demo_responder(messages, kwargs):
    sys_prompt = messages[0].content if messages else ""
    if "任务规划器" in sys_prompt:
        return _plan_for(messages[-1].content)
    if "参数修正器" in sys_prompt:
        return "{}"
    return _answer_for(messages[-1].content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="场景1：知识库问答助手")
    parser.add_argument("--provider", choices=["fake", "openai_compatible"], default="fake")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.provider == "openai_compatible":
        llm = build_llm_client(cfg.get("llm"))
        print(f"[模式] 真实 LLM: {llm.model}")
    else:
        llm = FakeLLMClient(responder=demo_responder)
        print("[模式] 演示 LLM（fake，无 Key）")
    service = AgentService.build_from_config(cfg, llm=llm)

    questions = [
        "工具注册中心是什么？",
        "双缓存记忆机制是怎么工作的？",
        "任务规划器如何拆解任务？",
        "工具调用失败时会怎么处理？",
    ]
    session_id = None
    print("=" * 60)
    print("场景 1 · 知识库问答助手（多轮 · 检索 → 回答）")
    print("=" * 60)
    for i, q in enumerate(questions, 1):
        print(f"\n[Q{i}] {q}")
        resp = service.chat(q, session_id)
        session_id = resp.session_id
        for t in resp.trace:
            print(f"  - {t.action} {t.args if t.args else ''} [{t.status}]")
        print(f"[A] {resp.answer}")
    print(f"\n会话 ID: {session_id}（多轮记忆已保持上下文）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
