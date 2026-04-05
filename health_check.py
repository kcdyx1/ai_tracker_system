#!/usr/bin/env python3
"""
统一系统健康检查 - AI Tracker System
一次性检查所有关键服务的状态
"""

import subprocess
import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path("/home/kangchen/.openclaw/workspace/ai_tracker_system")
DB_PATH = PROJECT_DIR / "ai_tracker.db"
FEEDER_METADATA_FILE = PROJECT_DIR / "config" / "feeder_metadata.json"

# Load .env
env_file = PROJECT_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "openclaw2026")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")


def check_docker_container(name: str) -> dict:
    """检查 Docker 容器状态"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        if "Up" in status:
            return {"status": "healthy", "detail": status, "running": True}
        elif not status:
            return {"status": "stopped", "detail": "not found", "running": False}
        else:
            return {"status": "unhealthy", "detail": status, "running": False}
    except Exception as e:
        return {"status": "error", "detail": str(e), "running": False}


def check_systemd_service(name: str) -> dict:
    """检查 systemd 服务状态"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5
        )
        state = result.stdout.strip()
        if state == "active":
            return {"status": "healthy", "detail": state, "running": True}
        elif state == "failed":
            return {"status": "failed", "detail": state, "running": False}
        else:
            return {"status": "unknown", "detail": state, "running": False}
    except Exception as e:
        return {"status": "error", "detail": str(e), "running": False}


def check_redis() -> dict:
    """检查 Redis 连接"""
    try:
        result = subprocess.run(
            ["docker", "exec", "docker-redis-1", "redis-cli", "ping"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() == "PONG":
            return {"status": "healthy", "detail": "PONG"}
        return {"status": "unhealthy", "detail": result.stdout.strip()}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_neo4j() -> dict:
    """检查 Neo4j 连接"""
    try:
        result = subprocess.run(
            ["docker", "exec", "ai_tracker_neo4j", "cypher-shell",
             "-u", "neo4j", "-p", NEO4J_PASSWORD, "-d", "neo4j",
             "RETURN 1 as n"],
            capture_output=True, text=True, timeout=8
        )
        if "1 row" in result.stdout or result.returncode == 0:
            return {"status": "healthy", "detail": "connected"}
        return {"status": "unhealthy", "detail": result.stdout[:100]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_rss_proxy() -> dict:
    """检查 MiniMax 代理健康"""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://114.132.200.116:3888/v1/models",
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = resp.read().decode()
        if "MiniMax" in data:
            models = json.loads(data).get("data", [])
            model_names = [m.get("id", "") for m in models]
            return {"status": "healthy", "detail": f"models: {', '.join(model_names[:3])}"}
        return {"status": "unknown", "detail": "unexpected response"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_task_queue() -> dict:
    """检查任务队列状态"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM task_queue WHERE created_at >= date('now')")
        today = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM task_queue WHERE status = 'failed'")
        failed = c.fetchone()[0]
        conn.close()
        counts = {status: count for status, count in rows}
        return {
            "status": "healthy" if failed < 50 else "warning",
            "counts": counts,
            "today_new": today,
            "failed_count": failed,
            "total": sum(counts.values())
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_celery_workers() -> dict:
    """检查 Celery worker 进程"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "celery.*worker.celery_app", "-c"],
            capture_output=True, text=True, timeout=5
        )
        count = int(result.stdout.strip())
        if count >= 8:
            return {"status": "healthy", "detail": f"{count} worker processes", "count": count}
        elif count >= 2:
            return {"status": "degraded", "detail": f"only {count} worker processes", "count": count}
        elif count >= 1:
            return {"status": "degraded", "detail": f"only {count} worker process", "count": count}
        else:
            return {"status": "stopped", "detail": "no workers", "count": 0}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_feed_health() -> dict:
    """检查 RSS feeds 健康状态"""
    try:
        metadata = {}
        if FEEDER_METADATA_FILE.exists():
            metadata = json.loads(FEEDER_METADATA_FILE.read_text())

        now = datetime.now(timezone.utc)
        stale_feeds = []
        for url, last_crawl in metadata.items():
            if not last_crawl:
                stale_feeds.append({"url": url[:80], "last_crawl": "never", "days": None})
                continue
            try:
                dt_str = last_crawl.replace("+00:00", "").replace("Z", "")
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days = (now - dt).total_seconds() / 86400
                if days > 7:
                    stale_feeds.append({"url": url[:80], "last_crawl": last_crawl[:16], "days": int(days)})
            except Exception:
                pass

        stale_sorted = sorted(stale_feeds, key=lambda x: x.get("days") or 0, reverse=True)
        return {
            "status": "warning" if len(stale_feeds) >= 5 else "healthy" if len(stale_feeds) == 0 else "ok",
            "total_monitored": len(metadata),
            "stale_count": len(stale_feeds),
            "stale_feeds": stale_sorted[:10]
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def get_full_health_report() -> dict:
    """生成完整的健康报告"""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "redis": check_redis(),
            "neo4j": check_neo4j(),
            "rsshub": check_docker_container("rsshub"),
            "docker_redis": check_docker_container("docker-redis-1"),
            "ai_server": check_systemd_service("ai-server"),
            "ai_celery": check_systemd_service("ai-celery"),
        },
        "workers": check_celery_workers(),
        "proxy": check_rss_proxy(),
        "task_queue": check_task_queue(),
        "feed_health": check_feed_health(),
    }


if __name__ == "__main__":
    report = get_full_health_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
