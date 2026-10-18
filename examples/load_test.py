"""P0-5 压测脚本：并发请求 /api/v1/chat，统计 QPS / P50 / P95 / P99 / 错误率。

用法:
    python examples/load_test.py --url http://127.0.0.1:8000 --concurrency 20 --duration 60
    python examples/load_test.py --mode real --api-key <key>     # 真实模型端到端（需先起服+配 key）
    python examples/load_test.py --mode fake                     # 框架自身吞吐（fake 模式）

输出:
    stdout 摘要 + examples/load_report.json（供 docs/CAPACITY.md 沉淀）

说明:
- fake 模式测框架极限（不含 LLM 网络延迟）；real 模式测端到端。
- 各并发档建议跑 60s、3 次取中位数（见 docs/CAPACITY.md 方法）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from typing import Dict, List, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    raise SystemExit("缺少依赖：pip install httpx")

_QUERIES = [
    "帮我算 (3+5)*2 等于多少",
    "现在几点了",
    "北京天气怎么样",
    "搜索一下 Python 是什么",
    "1+1 等于几",
]


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    api_key: Optional[str],
    results: List[Dict],
    stop: asyncio.Event,
) -> None:
    headers = {"X-API-Key": api_key} if api_key else {}
    while not stop.is_set():
        query = random.choice(_QUERIES)
        started = time.perf_counter()
        try:
            resp = await client.post(
                f"{url}/api/v1/chat",
                json={"query": query},
                headers=headers,
                timeout=60.0,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "latency_ms": latency_ms,
                    "status": resp.status_code,
                    "ok": resp.status_code == 200,
                }
            )
        except httpx.HTTPError as e:  # noqa: BLE001
            results.append({"latency_ms": -1, "status": 0, "ok": False, "error": str(e)})


async def run_load(
    url: str,
    concurrency: int,
    duration: float,
    api_key: Optional[str] = None,
) -> Dict:
    """执行一轮压测，返回统计摘要。"""
    results: List[Dict] = []
    stop = asyncio.Event()
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=200)) as client:
        tasks = [
            asyncio.create_task(_worker(client, url, api_key, results, stop))
            for _ in range(concurrency)
        ]
        await asyncio.sleep(duration)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    ok = [r for r in results if r["ok"]]
    err = [r for r in results if not r["ok"]]
    latencies = sorted(r["latency_ms"] for r in ok if r["latency_ms"] >= 0)
    elapsed = duration
    total = len(results)

    def pct(p: float) -> Optional[float]:
        if not latencies:
            return None
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return round(latencies[idx], 1)

    return {
        "concurrency": concurrency,
        "duration_s": elapsed,
        "total_requests": total,
        "qps": round(total / elapsed, 2) if elapsed else 0,
        "success_rate": round(len(ok) / total * 100, 2) if total else 0.0,
        "errors": len(err),
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "mean_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "max_ms": round(max(latencies), 1) if latencies else None,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Framework 压测脚本")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--concurrency", type=int, default=20, help="并发数")
    parser.add_argument("--duration", type=float, default=10.0, help="持续时间（秒）")
    parser.add_argument("--api-key", default=None, help="X-API-Key（开启鉴权时）")
    parser.add_argument("--report", default="examples/load_report.json", help="报告输出路径")
    parser.add_argument(
        "--mode",
        default="fake",
        choices=["fake", "real"],
        help="fake=框架吞吐；real=真实模型端到端",
    )
    args = parser.parse_args(argv)

    print(f"== 压测开始: url={args.url} concurrency={args.concurrency} duration={args.duration}s mode={args.mode}")
    report = asyncio.run(run_load(args.url, args.concurrency, args.duration, args.api_key))
    report["mode"] = args.mode

    print(json.dumps(report, ensure_ascii=False, indent=2))
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已写入: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
