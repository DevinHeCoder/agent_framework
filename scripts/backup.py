"""P0-2 备份脚本：Redis 持久化触发 + 会话/用量快照导出 + tar.gz 打包，保留最近 7 份。

用法:
    python scripts/backup.py                     # 默认：连 AGENT_REDIS_URL 执行 BGSAVE + 导出快照 + 打包
    python scripts/backup.py --dry-run           # 只打印将执行的动作，不做任何写操作
    python scripts/backup.py --skip-redis        # 无 Redis 环境：只导出可用的快照/打包（验证用）
    python scripts/backup.py --keep 7 --out-dir backup

产物:
    backup/<YYYYMMDD>/agent-backup-<YYYYMMDD>.tar.gz
    内含 sessions_snapshot.json（会话记忆 + 用量计数）与可选的 dump.rdb（--dump-dir 提供时）。

设计:
- Redis 数据恢复主路径是 AOF/RDB（volume redis-data，compose 已开启 appendonly）；
- 会话快照 JSON 是「双写兜底」：即使 Redis 整体丢失，也可按 docs/RECOVERY.md 回灌。
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backup"
DEFAULT_KEEP = 7

# 长时记忆 key 前缀（与 src/memory/redis_memory.py / src/api/usage.py 对齐）
SESSION_KEY_PREFIX = "agent:session:"
USAGE_KEY_PREFIX = "agent:usage:"

logger = logging.getLogger("agent_framework.backup")


def load_redis_url(env_file: Optional[Path] = None) -> Optional[str]:
    """读取 AGENT_REDIS_URL（环境变量优先，其次项目根 .env）。"""
    url = os.environ.get("AGENT_REDIS_URL")
    if url:
        return url
    p = env_file or (PROJECT_ROOT / ".env")
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AGENT_REDIS_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def trigger_bgsave(redis_url: str) -> dict:
    """执行 BGSAVE 并确认持久化完成（LASTSAVE 时间戳变化）。"""
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    last = int(client.lastsave() or 0)
    client.bgsave()
    # 等待持久化完成（最多 30s）
    deadline = datetime.datetime.now().timestamp() + 30
    while datetime.datetime.now().timestamp() < deadline:
        if int(client.lastsave() or 0) > last:
            return {"ok": True, "lastsave": int(client.lastsave())}
        import time

        time.sleep(0.5)
    return {"ok": False, "error": "BGSAVE 超时（30s 内 LASTSAVE 未更新）"}


def export_snapshot(client) -> dict:
    """导出会话记忆与用量计数快照（SCAN 全部 agent:* key）。"""
    sessions: Dict[str, List[dict]] = {}
    usage: Dict[str, int] = {}
    cursor = "0"
    while True:
        cursor, keys = client.scan(cursor, match="agent:*", count=500)
        for key in keys:
            if key.startswith(SESSION_KEY_PREFIX):
                raw_list = client.lrange(key, 0, -1) or []
                msgs = []
                for raw in raw_list:
                    try:
                        msgs.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        continue  # 单条损坏跳过，不导致整份快照失败
                sessions[key[len(SESSION_KEY_PREFIX):]] = msgs
            elif key.startswith(USAGE_KEY_PREFIX):
                try:
                    usage[key] = int(client.get(key) or 0)
                except (TypeError, ValueError):
                    continue
        if cursor == "0":
            break
    return {"sessions": sessions, "usage": usage}


def build_tarball(
    backup_dir: Path,
    snapshot: dict,
    dump_rdb_paths: Optional[List[Path]] = None,
) -> Path:
    """把快照 JSON 与可选 dump.rdb 打成 tar.gz，返回产物路径。"""
    stamp = datetime.date.today().strftime("%Y%m%d")
    day_dir = backup_dir / stamp
    day_dir.mkdir(parents=True, exist_ok=True)

    # 临时目录内组装内容，再打包，保证 tar 内部路径干净
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "sessions_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for i, rdb in enumerate(dump_rdb_paths or []):
            if rdb and rdb.is_file():
                name = f"dump_{i}.rdb" if i else "dump.rdb"
                shutil_copy(rdb, tmp_root / name)

        archive_path = day_dir / f"agent-backup-{stamp}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            for f in sorted(tmp_root.iterdir()):
                tar.add(f, arcname=f.name)
    return archive_path


def shutil_copy(src: Path, dst: Path) -> None:
    import shutil

    shutil.copy2(src, dst)


def prune_backups(backup_dir: Path, keep: int) -> List[Path]:
    """删除超过 keep 份的备份目录，返回被删除的目录列表。"""
    dirs = sorted(
        (d for d in backup_dir.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: d.name,
    )
    removed = []
    for d in dirs[:-keep] if keep > 0 else dirs:
        for f in d.iterdir():
            f.unlink(missing_ok=True)
        d.rmdir()
        removed.append(d)
    return removed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Framework 备份脚本")
    parser.add_argument("--redis-url", default=None, help="Redis 连接串（默认读 AGENT_REDIS_URL）")
    parser.add_argument("--out-dir", default=str(DEFAULT_BACKUP_DIR), help="备份输出目录")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="保留最近份数（默认 7）")
    parser.add_argument("--dump-dir", default=None, help="dump.rdb 所在目录（可选，容器数据卷拷贝）")
    parser.add_argument("--dry-run", action="store_true", help="只打印执行计划，不做任何写操作")
    parser.add_argument("--skip-redis", action="store_true", help="跳过 Redis 连接（快照为空，仅验证流程）")
    args = parser.parse_args(argv)

    backup_dir = Path(args.out_dir)
    actions: List[str] = []

    redis_url = args.redis_url or load_redis_url()
    bgsave_result: Optional[dict] = None
    snapshot: dict = {"sessions": {}, "usage": {}, "exported_at": None}

    if not args.skip_redis:
        if not redis_url:
            logger.error("未找到 Redis 地址（--redis-url 或 AGENT_REDIS_URL）")
            return 2
        actions.append(f"连接 Redis {redis_url} 并执行 BGSAVE")
        actions.append(f"SCAN 导出会话记忆（{SESSION_KEY_PREFIX}*）与用量（{USAGE_KEY_PREFIX}*）")
        if not args.dry_run:
            try:
                bgsave_result = trigger_bgsave(redis_url)
                import redis as redis_lib

                client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
                snapshot = export_snapshot(client)
                snapshot["exported_at"] = datetime.datetime.now().isoformat()
            except Exception as e:  # noqa: BLE001
                logger.error("Redis 备份失败: %s", e)
                return 1
    else:
        actions.append("--skip-redis：跳过 Redis，仅验证打包流程")
        snapshot["exported_at"] = datetime.datetime.now().isoformat()

    dump_sources: List[Path] = []
    if args.dump_dir:
        d = Path(args.dump_dir)
        candidates = list(d.glob("dump.rdb")) + list(d.glob("appendonlydir/*"))
        dump_sources = [c for c in candidates if c.is_file()]
        actions.append(f"打包 dump 文件: {[c.name for c in dump_sources] or '（目录内无 dump 文件）'}")

    stamp = datetime.date.today().strftime("%Y%m%d")
    actions.append(f"打包为 {backup_dir}/{stamp}/agent-backup-{stamp}.tar.gz")
    actions.append(f"清理超过 {args.keep} 份的旧备份")

    if args.dry_run:
        print("== dry-run 执行计划 ==")
        for a in actions:
            print("  -", a)
        print("（dry-run：未执行任何写操作）")
        return 0

    archive_path = build_tarball(backup_dir, snapshot, dump_sources)
    removed = prune_backups(backup_dir, args.keep)
    print(f"备份完成: {archive_path} ({archive_path.stat().st_size} bytes)")
    print(f"会话数: {len(snapshot.get('sessions', {}))} | 用量 key 数: {len(snapshot.get('usage', {}))}")
    if bgsave_result is not None:
        print(f"Redis BGSAVE: {'成功' if bgsave_result.get('ok') else '未确认（' + str(bgsave_result.get('error')) + '）'}")
    if removed:
        print(f"已清理旧备份: {[str(r) for r in removed]}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
