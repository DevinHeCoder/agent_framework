"""场景 3 · 多工具编排助手（一条指令调度多个工具）。

演示能力:
    - 一次查询被拆解为多步计划（LLM 自动规划）
    - 多工具协同：weather（天气）+ calc（计算）+ time（时间）
    - 全部结果综合成一段自然语言回答

用法:
    # 演示模式（fake LLM，无需 Key）
    python examples/scenarios/scenario_multi_tool.py

    # 真实 LLM 模式
    set AGENT_LLM_PROVIDER=openai_compatible
    set AGENT_LLM_BASE_URL=http://localhost:11434/v1
    set AGENT_LLM_MODEL=qwen2.5:7b
    set AGENT_LLM_API_KEY=ollama
    python examples/scenarios/scenario_multi_tool.py --provider openai_compatible
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

logger = get_logger("agent_framework.scenario.multi")


# ---------------- fake 模式：模拟规划器（仅演示） ----------------
_CITIES = ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉")


def _plan_for(query: str) -> str:
    steps = []
    if "天气" in query:
        # 城市提取：优先查内置城市表，兜底取“天气”前两字（演示中文城市）
        city = next((c for c in _CITIES if c + "天气" in query), None)
        if city is None:
            city = query.split("天气", 1)[0].strip()[-2:] or "杭州"
        steps.append({"action": "weather", "args": {"city": city}, "thought": f"查 {city} 天气"})
    if "计算" in query or "算" in query or "等于" in query:
        for sep in ("等于", "的结果"):
            if sep in query and "计算" in query:
                expr = query.split("计算", 1)[-1].split(sep, 1)[0].strip()
                break
        else:
            expr = "2**10"
        steps.append({"action": "calc", "args": {"expression": expr}, "thought": "计算"})
    if "时间" in query or "几点" in query:
        steps.append({"action": "time", "args": {}, "thought": "查时间"})
    if not steps:
        steps.append({"action": "respond", "args": {}, "thought": "直接回答"})
    steps.append({"action": "respond", "args": {}, "thought": "综合多工具结果"})
    return json.dumps({"steps": steps}, ensure_ascii=False)


def _answer_for(content: str) -> str:
    if "工具观察结果" in content:
        obs = content.split("工具观察结果：", 1)[-1].split("\n规划建议", 1)[0]
        parts = []
        for ln in obs.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except (json.JSONDecodeError, TypeError):
                parts.append(ln)
                continue
            if "temperature" in obj:
                parts.append(f"{obj['city']}今天 {obj['temperature']}°C，{obj['condition']}")
            elif "result" in obj:
                parts.append(f"{obj.get('expression', '')} = {obj['result']}")
            elif "datetime" in obj:
                parts.append(f"当前时间 {obj['datetime']}")
            else:
                parts.append(ln)
        return "综合结果：" + "；".join(parts) if parts else "（无可用工具结果）"
    return "（演示模式）已收到你的请求。"


def demo_responder(messages, kwargs):
    sys_prompt = messages[0].content if messages else ""
    if "任务规划器" in sys_prompt:
        return _plan_for(messages[-1].content)
    if "参数修正器" in sys_prompt:
        return "{}"
    return _answer_for(messages[-1].content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="场景3：多工具编排助手")
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

    queries = [
        "帮我查一下北京天气，然后计算 2**10 等于多少",
        "顺便告诉我现在几点了",
    ]
    session_id = None
    print("=" * 60)
    print("场景 3 · 多工具编排助手（一条指令调度多个工具）")
    print("=" * 60)
    for i, q in enumerate(queries, 1):
        print(f"\n[Q{i}] {q}")
        resp = service.chat(q, session_id)
        session_id = resp.session_id
        for t in resp.trace:
            print(f"  - {t.action} {t.args if t.args else ''} [{t.status}]")
        print(f"[A] {resp.answer}")
    print(f"\n会话 ID: {session_id}（两轮查询共享上下文）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
