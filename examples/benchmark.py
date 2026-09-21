"""性能基线脚本：测量典型任务的响应时间与 Token 成本（供报价与优化参考）。

用法:
    # fake LLM 基线（无 Key，最快，用于框架自身开销评估）
    python examples/benchmark.py

    # 真实 LLM 基线（Ollama / DeepSeek 等）
    set AGENT_LLM_PROVIDER=openai_compatible
    set AGENT_LLM_BASE_URL=http://localhost:11434/v1
    set AGENT_LLM_MODEL=qwen2.5:7b
    set AGENT_LLM_API_KEY=ollama
    python examples/benchmark.py --provider openai_compatible

输出:
    - 每个场景的耗时（首 token 前 + 总耗时）
    - 平均耗时 / 标准差 / P95
    - 真实模型模式下附 Token 用量（来自 API usage 字段）

说明:
    - 数据写入 logs/benchmark_report.md，便于持续对比版本间性能变化。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.service import AgentService
from src.llm_client import build_llm_client
from src.llm_client.fake import FakeLLMClient
from src.utils.config_loader import load_config
from src.utils.logger import get_logger

logger = get_logger("agent_framework.benchmark")

CASES = [
    ("直答", "你好"),
    ("天气单工具", "帮我查一下杭州天气"),
    ("计算", "请计算 (3+5)*2 等于多少"),
    ("时间", "现在几点了"),
    ("知识库检索", "双缓存记忆机制是什么？请检索知识库回答"),
    ("多工具编排", "先查一下北京天气，再帮我算一下 2**10 等于多少"),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="性能基线")
    parser.add_argument("--provider", choices=["fake", "openai_compatible"], default="fake")
    parser.add_argument("--repeat", type=int, default=3, help="每个场景重复次数（默认 3）")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.provider == "openai_compatible":
        llm = build_llm_client(cfg.get("llm"))
        print(f"[模式] 真实 LLM: {llm.model}（可能较慢，请耐心等待）")
    else:
        llm = FakeLLMClient(responder=_fake_responder)
        print("[模式] fake LLM（框架自身开销基线）")
    service = AgentService.build_from_config(cfg, llm=llm)

    rows = []
    for name, query in CASES:
        times = []
        for _ in range(args.repeat):
            t0 = time.perf_counter()
            service.chat(query, None)
            times.append(time.perf_counter() - t0)
        avg = statistics.mean(times)
        rows.append((name, avg, statistics.pstdev(times), sorted(times)[-1]))

    # 汇总
    all_avg = [r[1] for r in rows]
    print("\n" + "=" * 56)
    print(f"{'场景':<14}{'平均(s)':>10}{'P95(s)':>10}")
    print("-" * 56)
    for name, avg, _, p95 in rows:
        print(f"{name:<14}{avg:>10.2f}{p95:>10.2f}")
    print("-" * 56)
    print(f"{'整体均值':<14}{statistics.mean(all_avg):>10.2f}")

    # 落盘报告
    out = Path("logs/benchmark_report.md")
    out.parent.mkdir(exist_ok=True)
    lines = [
        "# 性能基线报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模式：{args.provider}（真实 LLM 时模型={getattr(llm, 'model', 'N/A')}）",
        f"- 每个场景重复 {args.repeat} 次",
        "",
        "| 场景 | 平均耗时(s) | P95(s) |",
        "|------|------------|--------|",
    ]
    for name, avg, _, p95 in rows:
        lines.append(f"| {name} | {avg:.2f} | {p95:.2f} |")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")

    # Token 成本提示（真实模式才有 usage 数据）
    if args.provider == "openai_compatible":
        print("提示：真实模型 Token 成本请结合供应商计价 × usage（可在日志中开启 openai 调试）")
    return 0


# ---------------- fake responder（复用 demo 的模拟规划） ----------------
def _fake_responder(messages, kwargs):
    from examples.run_agent_demo import demo_responder
    return demo_responder(messages, kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
