# 数据备份与恢复手册（RECOVERY）

> P0-2 目标：会话记忆、用量数据不因 Redis 崩溃 / 容器重启而丢失；提供可执行、可演练的备份与恢复流程。
> 本地执行：所有命令在项目根目录运行。服务器执行：按 _deploy/ 部署手册中对应章节操作（注意服务器无沙箱，改动先本地验证）。

---

## 1. 数据落盘架构

```text
agent-app (FastAPI)
   │ 会话记忆 / 用量计数
   ▼
Redis (agent-redis, redis:7-alpine)
   ├─ AOF 持久化（appendonly yes / everysec）→ /data/appendonlydir  [主路径]
   ├─ RDB 快照（BGSAVE）→ /data/dump.rdb                        [辅助]
   └─ volume redis-data（docker 命名卷）→ 容器重启不丢
会话快照 JSON（backup/<日期>/agent-backup-<日期>.tar.gz）          [双写兜底]
```

- Redis 数据（会话记忆 `agent:session:*`、用量 `agent:usage:*`）全部落在命名卷 `redis-data`；
- docker-compose 已开启 AOF（`--appendonly yes --appendfsync everysec`）：崩溃最多丢失约 1 秒写入；
- 每日备份脚本额外导出全量快照 JSON 作为双写兜底。

## 2. 备份

### 2.1 手动备份（可执行演练）

```bash
# 本地（需可连接 Redis；无 Redis 时 --skip-redis 仅验证流程）
python scripts/backup.py

# 服务器：Redis 在容器内，先拷贝数据文件再打包（脚本支持 --dump-dir）
docker exec agent-redis redis-cli BGSAVE
docker cp agent-redis:/data/dump.rdb /tmp/agent-dump.rdb
python scripts/backup.py --dump-dir /tmp/agent-dump.rdb
```

产物：`backup/<YYYYMMDD>/agent-backup-<YYYYMMDD>.tar.gz`，内含：

| 文件 | 内容 |
| --- | --- |
| `sessions_snapshot.json` | 全部会话消息 + 用量计数（SCAN 导出，UTF-8） |
| `dump.rdb` | （可选，`--dump-dir` 提供时）Redis RDB 二进制 |

### 2.2 定时备份（服务器）

```bash
crontab -e
# 每天 03:00 备份，日志留痕
0 3 * * * cd /opt/agent_framework && /usr/bin/python3 scripts/backup.py >> logs/backup.log 2>&1
```

`backup.py --keep 7` 自动保留最近 7 份。

### 2.3 验证备份完整性

```bash
tar -tzf backup/20261016/agent-backup-20261016.tar.gz
# 期望输出：sessions_snapshot.json（及可选 dump.rdb）
python -c "import json;d=json.load(open(r'backup/20261016/sessions_snapshot.json',encoding='utf-8'));print('sessions:',len(d['sessions']),'usage:',len(d['usage']))"
```

## 3. 恢复

### 场景 A：Redis 容器数据损坏 / 误删（推荐 AOF/RDB 恢复）

```bash
# 1) 停止应用，避免写入新数据
docker compose stop agent-app

# 2) 重建 Redis（volume 内 AOF/RDB 仍在）→ 数据自动恢复
docker compose up -d redis
docker exec agent-redis redis-cli ping   # PONG

# 3) 数据核对
docker exec agent-redis redis-cli SCAN 0 MATCH 'agent:session:*' COUNT 100
# 若数据为空，见场景 B

# 4) 重启应用
docker compose up -d agent-app
```

> 如果 volume 本身被删（`docker compose down -v` 等），需用场景 B 的快照回灌。

### 场景 B：volume 整体丢失 → 会话快照回灌

```bash
# 1) 确认 Redis 已空
docker exec agent-redis redis-cli DBSIZE   # 0 或异常小

# 2) 从备份解出快照
cd backup/20261016 && tar -xzf agent-backup-20261016.tar.gz

# 3) 回灌（Python + redis-py；服务器需可连 redis://localhost:6380 或容器网络地址）
python - <<'EOF'
import json, redis
snap = json.load(open('sessions_snapshot.json', encoding='utf-8'))
r = redis.Redis.from_url('redis://localhost:6380/0', decode_responses=True)
for sid, msgs in snap.get('sessions', {}).items():
    key = f'agent:session:{sid}'
    for m in msgs:
        r.rpush(key, json.dumps(m, ensure_ascii=False))
    r.expire(key, 86400)
for k, v in snap.get('usage', {}).items():
    r.set(k, v)
print('回灌完成:', len(snap.get('sessions', {})), '个会话')
EOF
```

> 本地验证回灌时把 `redis://localhost:6380/0` 换成 `AGENT_REDIS_URL` 的实际值。

### 场景 C：整机重建（服务器）

```bash
# 1) 代码 + 配置
git clone <repo> /opt/agent_framework && cd /opt/agent_framework
cp .env.prod .env   # 从密钥管理恢复生产配置

# 2) 构建并启动
docker compose up --build -d

# 3) 恢复数据：按场景 B 回灌（或恢复 redis-data 卷备份）

# 4) 验证
curl -s http://localhost:8001/readyz    # {"status":"ready",...}
```

## 4. 恢复演练（季度一次）

| 步骤 | 命令 | 通过标准 |
| --- | --- | --- |
| 造数据 | 通过前端/API 发起 3 次对话 | sessions 列表 ≥ 3 |
| 手动备份 | `python scripts/backup.py` | tar.gz 生成且非空 |
| 破坏 | `docker compose stop redis && docker compose rm -f redis` | Redis 数据消失 |
| 重建 | `docker compose up -d redis`（AOF 自动恢复） | 数据仍在 = 场景 A 通过 |
| 双写回灌 | 清空后按场景 B 脚本回灌 | 会话消息可再次读取 = 场景 B 通过 |
| 收尾 | `docker compose up -d` | readyz 200 |

## 5. 备份策略建议（交付时写进 SLA）

- 频率：每日 03:00（服务器 cron）；
- 保留：7 份滚动（约 1 周窗口），按客户要求可调整 `--keep`；
- RPO：AOF everysec → 约 1 秒；RDB/快照 → 最近一次备份；
- RTO：场景 A 分钟级（数据在卷内）；场景 B 约 10 分钟（回灌量取决于会话数）。
