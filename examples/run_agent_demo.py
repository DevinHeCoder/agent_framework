"""Agent Framework 命令行多轮演示。

用法:
    # 演示模式（fake LLM，无需任何 Key，内置模拟规划器）
    python examples/run_agent_demo.py

    # 指定会话 ID（多轮连续可复现）
    python examples/run_agent_demo.py --session-id demo-1

    # 真实 LLM 模式（需设置 AGENT_LLM_API_KEY / AGENT_LLM_BASE_URL / AGENT_LLM_MODEL）
    python examples/run_agent_demo.py --provider openai_compatible

退出: 输入 exit / quit / 退出

演示查询示例:
    - 帮我查一下杭州天气
    - 计算一下 3*8
    - 现在几点了
    - 你好
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.service import AgentService
from src.llm_client import build_llm_client
from src.llm_client.fake import FakeLLMClient
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

logger = get_logger("agent_framework.examples.demo")


# ---------------- 演示模式：内置"模拟 LLM" ----------------
def _plan_for(query: str) -> str:
    """模拟 LLM 规划：按关键词拆解任务（仅演示，非真实推理）。"""
    steps = []
    if "天气" in query:
        steps.append({"action": "weather", "args": {"city": "杭州"}, "thought": "查杭州天气"})
    if "计算" in query or "算" in query:
        steps.append({"action": "calc", "args": {"expression": "3*8"}, "thought": "计算 3*8"})
    if "时间" in query or "几点" in query:
        steps.append({"action": "time", "args": {}, "thought": "查当前时间"})
    if not steps:
        steps.append({"action": "respond", "args": {}, "thought": "直接回答"})
    steps.append({"action": "respond", "args": {}, "thought": "综合工具结果"})
    return json.dumps({"steps": steps}, ensure_ascii=False)


def _answer_for(content: str) -> str:
    """模拟 LLM 回答：把工具观察结果格式化成自然语句（仅演示）。"""
    if "工具观察结果" in content:
        obs = content.split("工具观察结果：", 1)[-1].split("\n规划建议", 1)[0]
        lines = [
            ln.strip()
            for ln in obs.splitlines()
            if ln.strip() and "无工具结果" not in ln and "失败" not in ln
        ]
        if lines:
            parts = []
            for ln in lines[:3]:
                try:
                    obj = json.loads(ln)
                except (json.JSONDecodeError, TypeError):
                    parts.append(ln)
                    continue
                if "city" in obj and "temperature" in obj:
                    parts.append(f"{obj['city']}今天 {obj['temperature']}°C，{obj['condition']}")
                elif "result" in obj:
                    parts.append(f"{obj.get('expression', '')} = {obj['result']}")
                elif "datetime" in obj:
                    parts.append(f"当前时间 {obj['datetime']}")
                else:
                    parts.append(ln)
            return "根据工具结果：" + "；".join(parts)
    return "（演示模式）已收到你的请求。"


def demo_responder(messages, kwargs):
    sys_prompt = messages[0].content if messages else ""
    if "任务规划器" in sys_prompt:
        return _plan_for(messages[-1].content)
    if "参数修正器" in sys_prompt:
        return "{}"
    return _answer_for(messages[-1].content)


def build_demo_service(provider: str) -> AgentService:
    """按 provider 组装服务：fake（内置模拟）或 openai_compatible（真实 LLM）。"""
    cfg = load_config()
    if provider == "openai_compatible":
        llm = build_llm_client(cfg.get("llm"))
        print(f"[模式] 真实 LLM: {llm.model}")
    else:
        llm = FakeLLMClient(responder=demo_responder)
        print("[模式] 演示 LLM（fake，无 Key；真实 LLM 请加 --provider openai_compatible）")
    return AgentService.build_from_config(cfg, llm=llm)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Agent Framework 命令行演示")
    parser.add_argument("--session-id", default=None, help="会话 ID（缺省自动创建）")
    parser.add_argument(
        "--provider",
        choices=["fake", "openai_compatible"],
        default="fake",
        help="LLM 提供方（默认 fake）",
    )
    args = parser.parse_args(argv)

    service = build_demo_service(args.provider)
    session_id = args.session_id

    print("=" * 60)
    print("轻量智能 Agent 工具编排框架 · 多轮演示")
    print("输入 exit / quit / 退出 结束")
    print("=" * 60)

    while True:
        try:
            query = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in ("exit", "quit") or query == "退出":
            break

        resp = service.chat(query, session_id)
        session_id = resp.session_id
        print(f"Agent> {resp.answer}")
        for t in resp.trace:
            print(f"  [{t.status}] {t.action} {t.args if t.args else ''}")
        if not resp.success:
            print("  （注意：本步骤未完全成功，已走兜底策略）")

    if session_id:
        print(f"会话 ID: {session_id}（多轮连续可复现）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
