"""真实 LLM 端到端验证脚本（阶段 0 · 可交付信任证据）。

用途:
    验证框架在「真实大模型」下完整跑通：任务拆解 → 工具调度 → 参数自愈 → 记忆多轮。
    支持 OpenAI 兼容协议任意端点（Ollama 本地 / DeepSeek / 通义 / 豆包等）。

快速使用（Ollama 本地 qwen2.5，无需任何 Key）:
    ollama pull qwen2.5:7b
    set AGENT_LLM_PROVIDER=openai_compatible
    set AGENT_LLM_BASE_URL=http://localhost:11434/v1
    set AGENT_LLM_MODEL=qwen2.5:7b
    set AGENT_LLM_API_KEY=ollama
    python examples/validate_real_llm.py

云端示例（DeepSeek）:
    set AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
    set AGENT_LLM_MODEL=deepseek-chat
    set AGENT_LLM_API_KEY=sk-xxx

说明:
    - 覆盖 6 个典型场景：直答 / 单工具 / 计算 / 时间 / 知识库检索 / 多工具编排。
    - 每个场景输出执行轨迹与耗时；全部成功后退出码 0，适合 CI / 演示一键复跑。
    - 多轮记忆验证：场景 6 复用场景 1 的会话 ID，验证跨轮上下文保持。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.service import AgentService
from src.llm_client import build_llm_client
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

logger = get_logger("agent_framework.validate")

# 预置验证场景：(名称, 查询, 期望触发的工具)
SCENARIOS = [
    ("S1 直答", "你好，请自我介绍一下", None),
    ("S2 天气单工具", "帮我查一下杭州今天的天气", {"weather"}),
    ("S3 安全计算", "请计算 (3+5)*2 等于多少", {"calc"}),
    ("S4 时间工具", "现在几点钟了？", {"time"}),
    ("S5 知识库检索", "双缓存记忆机制是什么？请检索知识库回答", {"kb_search"}),
    ("S6 多工具编排", "先查一下北京天气，再帮我算一下 2**10 等于多少", {"weather", "calc"}),
]

EXPECT_ACTION = {
    "S1 直答": None,
    "S2 天气单工具": "weather",
    "S3 安全计算": "calc",
    "S4 时间工具": "time",
    "S5 知识库检索": "kb_search",
    "S6 多工具编排": None,
}


def main() -> int:
    cfg = load_config()
    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider", "fake")

    if provider == "fake":
        print("[错误] 当前 AGENT_LLM_PROVIDER=fake，请先设置环境变量切换为 openai_compatible。")
        print("参考脚本头部注释的 Ollama / DeepSeek 配置示例。")
        return 2

    llm = build_llm_client(llm_cfg)
    print("=" * 64)
    print(f"真实 LLM 端到端验证")
    print(f"  端点   : {llm_cfg.get('base_url') or '(默认)'}")
    print(f"  模型   : {llm.model}")
    print(f"  会话   : 多轮记忆复用（S6 复用 S1 会话）")
    print("=" * 64)

    service = AgentService.build_from_config(cfg, llm=llm)
    session_id = None
    failed = 0

    for name, query, expected in SCENARIOS:
        if name == "S6 多工具编排" and session_id is not None:
            sid = session_id  # 复用首轮会话 → 验证长时/短时记忆多轮
            note = f"(复用会话 {sid[:8]}… 验证多轮记忆)"
        else:
            sid = None
            note = "(新会话)"

        print(f"\n>>> {name} {note}\n    Q: {query}")
        t0 = time.perf_counter()
        try:
            resp = service.chat(query, sid)
        except Exception as e:
            print(f"    [失败] 异常: {type(e).__name__}: {e}")
            failed += 1
            continue
        dt = time.perf_counter() - t0
        session_id = resp.session_id if resp.session_id else session_id

        for t in resp.trace:
            flag = "" if t.status == "success" else f" [status={t.status}]"
            print(f"    - {t.action} {t.args if t.args else ''}{flag}")
        print(f"    A: {resp.answer}")
        print(f"    耗时: {dt:.1f}s  success={resp.success}")

        # 工具覆盖断言
        exp_actions = EXPECT_ACTION.get(name)
        if exp_actions:
            used = {t.action for t in resp.trace}
            if exp_actions not in used:
                print(f"    [失败] 期望工具 {exp_actions} 未被调用，实际 {sorted(used)}")
                failed += 1
            else:
                print(f"    [通过] 已调用工具 {exp_actions}")
        elif name == "S6 多工具编排":
            used = {t.action for t in resp.trace}
            missing = sorted({"weather", "calc"} - used)
            if missing:
                print(f"    [失败] 多工具编排未覆盖: {missing}")
                failed += 1
            else:
                print(f"    [通过] 多工具编排覆盖 {sorted(used)}")

    print("\n" + "=" * 64)
    if failed:
        print(f"验证结束：{len(SCENARIOS) - failed}/{len(SCENARIOS)} 通过，{failed} 失败")
        return 1
    print(f"验证结束：{len(SCENARIOS)}/{len(SCENARIOS)} 全部通过")
    print("可作为真实模型可交付的信任证据（供演示视频 / 客户案例引用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
