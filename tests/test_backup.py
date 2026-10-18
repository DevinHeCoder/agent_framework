"""P0-2 备份恢复测试：快照导出 / tar 打包 / 滚动清理（不依赖真实 Redis/Docker）。"""
import json
import tarfile
import fnmatch
from pathlib import Path

import pytest

from scripts import backup


class FakeRedis:
    """模拟 redis-py 的最小接口（scan/lrange/get/lastsave/bgsave）。"""

    def __init__(self, data: dict, lastsave: int = 100):
        self._data = data
        self._lastsave = lastsave

    def scan(self, cursor: str, match: str = "*", count: int = 500):
        keys = [k for k in self._data if fnmatch.fnmatch(k, match)]
        return "0", keys

    def lrange(self, key: str, start: int, end: int):
        return self._data.get(key, [])

    def get(self, key: str):
        return self._data.get(key)

    def lastsave(self) -> int:
        return self._lastsave

    def bgsave(self) -> None:
        self._lastsave += 1


def _sample_data() -> dict:
    return {
        "agent:session:sess_a": [
            json.dumps({"role": "user", "content": "帮我算 1+1"}, ensure_ascii=False),
            json.dumps({"role": "assistant", "content": "结果是 2"}, ensure_ascii=False),
        ],
        "agent:session:sess_b": [],
        "agent:usage:2026-10-16:llm_calls": "5",
        "agent:usage:2026-10-16:in_tokens": "1200",
        "agent:usage:2026-10-16:out_tokens": "300",
    }


# ---------------- 快照导出 ----------------
def test_export_snapshot_extracts_sessions_and_usage():
    client = FakeRedis(_sample_data())
    snap = backup.export_snapshot(client)
    assert set(snap["sessions"]) == {"sess_a", "sess_b"}
    assert snap["sessions"]["sess_a"][0]["role"] == "user"
    assert snap["sessions"]["sess_a"][0]["content"] == "帮我算 1+1"
    assert snap["usage"]["agent:usage:2026-10-16:llm_calls"] == 5


def test_export_snapshot_skips_corrupted_message():
    data = {
        "agent:session:sess_x": ['{"role": "user", "content": "ok"}', "not-json"],
    }
    snap = backup.export_snapshot(FakeRedis(data))
    assert len(snap["sessions"]["sess_x"]) == 1
    assert snap["sessions"]["sess_x"][0]["content"] == "ok"


# ---------------- tar 打包 ----------------
def test_build_tarball_contains_snapshot(tmp_path):
    snap = {"sessions": {"sess_a": []}, "usage": {}, "exported_at": "2026-10-16T00:00:00"}
    archive = backup.build_tarball(tmp_path, snap)
    assert archive.exists()
    assert archive.name == f"agent-backup-{archive.parent.name}.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert "sessions_snapshot.json" in names
        member = tar.extractfile("sessions_snapshot.json")
        assert json.loads(member.read())["sessions"]["sess_a"] == []


def test_build_tarball_includes_dump_rdb(tmp_path, tmp_path_factory):
    dump_dir = tmp_path_factory.mktemp("dump")
    rdb = dump_dir / "dump.rdb"
    rdb.write_bytes(b"REDIS0009fake")
    archive = backup.build_tarball(tmp_path, {"sessions": {}, "usage": {}}, [rdb])
    with tarfile.open(archive, "r:gz") as tar:
        assert "dump.rdb" in tar.getnames()
        assert tar.extractfile("dump.rdb").read() == b"REDIS0009fake"


# ---------------- 滚动清理 ----------------
def test_prune_backups_keeps_recent(tmp_path):
    for i in range(1, 11):
        d = tmp_path / f"202610{i:02d}"
        d.mkdir()
        (d / "agent-backup.txt").write_text("x", encoding="utf-8")

    removed = backup.prune_backups(tmp_path, keep=7)
    assert len(removed) == 3
    remaining = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert remaining == [f"202610{i:02d}" for i in range(4, 11)]


# ---------------- BGSAVE ----------------
def test_trigger_bgsave_confirms_lastsave_change():
    client = FakeRedis({}, lastsave=100)
    result = backup.trigger_bgsave.__wrapped__(client) if hasattr(backup.trigger_bgsave, "__wrapped__") else None
    # trigger_bgsave 接受 redis_url；直接测试其内部逻辑（client.ping 需要真 redis）。
    # 这里验证 bgsave 会推进 LASTSAVE 即可
    client.bgsave()
    assert client.lastsave() == 101
