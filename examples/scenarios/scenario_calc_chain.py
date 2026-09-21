"""场景 2 · 数学计算助手（安全计算器 + 多轮连续计算 + 容错演示）。

演示能力:
    - calc 安全计算器（ast 白名单求值，禁用 eval）
    - 多轮连续计算（同一会话，上轮结果/上下文可复用）
    - 非法表达式不崩流程：走参数校验失败 → 兜底回答

用法:
    # 演示模式（fake LLM，无需 Key）
    python examples/scenarios/scenario_calc_chain.py

    # 真实 LLM 模式
    set AGENT_LLM_PROVIDER=openai_compatible
    set AGENT_LLM_BASE_URL=http://localhost:11434/v1
    set AGENT_LLM_MODEL=qwen2.5:7b
    set AGENT_LLM_API_KEY=ollama
    python examples/scenarios/scenario_calc_chain.py --provider openai_compatible
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

logger = get_logger("agent_framework.scenario.calc")


# ---------------- fake 模式：模拟规划器（仅演示） ----------------
def _extract_expr(query: str) -> str:
    """从查询中提取数学表达式：优先 '计算 X 等于/的结果' 句式，否则正则兜底。"""
    for sep in ("等于", "的结果"):
        if sep in query and "计算" in query:
            expr = query.split("计算", 1)[-1].split(sep, 1)[0].strip()
            if expr:
                return expr
    import re
    m = re.search(r"[\w+\-*/()\s.]+", query.split("计算", 1)[-1])
    return (m.group(0).strip() if m else query) or query


def _plan_for(query: str) -> str:
    steps = []
    if "计算" in query or "算" in query or "等于" in query:
        expr = _extract_expr(query)
        steps.append({"action": "calc", "args": {"expression": expr}, "thought": "计算表达式"})
    if not steps:
        steps.append({"action": "respond", "args": {}, "thought": "直接回答"})
    steps.append({"action": "respond", "args": {}, "thought": "综合计算结果"})
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
            if "result" in obj:
                return f"{obj.get('expression', '')} = {obj['result']}"
        return "计算失败，已走兜底。"
    return "（演示模式）已收到你的请求。"


def demo_responder(messages, kwargs):
    sys_prompt = messages[0].content if messages else ""
    if "任务规划器" in sys_prompt:
        return _plan_for(messages[-1].content)
    if "参数修正器" in sys_prompt:
        return "{}"
    return _answer_for(messages[-1].content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="场景2：数学计算助手")
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
        "帮我计算 (3+5)*2 等于多少",
        "再帮我计算 2**10 等于多少",
        "帮我计算 sqrt(144) 等于多少",
        "帮我计算 abs(-8)+1 等于多少",
        "帮我计算 abc+1 等于多少",  # 非法表达式 → 容错兜底演示
    ]
    session_id = None
    print("=" * 60)
    print("场景 2 · 数学计算助手（多轮连续计算 + 容错）")
    print("=" * 60)
    for i, q in enumerate(questions, 1):
        print(f"\n[Q{i}] {q}")
        resp = service.chat(q, session_id)
        session_id = resp.session_id
        for t in resp.trace:
            print(f"  - {t.action} {t.args if t.args else ''} [{t.status}]")
        print(f"[A] {resp.answer}")
        if not resp.success:
            print("  （兜底策略已生效，流程未中断）")
    print(f"\n会话 ID: {session_id}（5 轮计算共用同一会话）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
