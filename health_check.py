#!/usr/bin/env python3
import subprocess, json, os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path("/home/kangchen/.openclaw/workspace/ai_tracker_system")
FEEDER_METADATA_FILE = PROJECT_DIR / "config" / "feeder_metadata.json"

env_file = PROJECT_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "openclaw2026")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

PG_HOST = os.environ.get("AI_TRACKER_PG_HOST", "172.20.0.4")
PG_PORT = int(os.environ.get("AI_TRACKER_PG_PORT", "5432"))
PG_USER = os.environ.get("POSTGRES_USER", "postgres")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "difyai123456")
PG_DATABASE = os.environ.get("POSTGRES_DB", "ai_tracker")

REDIS_CONTAINER = "docker-redis-1"
NEO4J_CONTAINER = "ai_tracker_neo4j"
RSSHUB_CONTAINER = "rsshub"

SYSTEMD_SERVICES = {
    "worker":   "ai_tracker_ai_tracker_worker.service",
    "server":   "ai_tracker_ai_tracker_server.service",
    "beat":     "ai_tracker_ai_tracker_beat.service",
    "feeder":   "ai_tracker_ai_tracker_feeder.service",
    "rescue":   "ai_tracker_ai_tracker_rescue.service",
    "watchdog": "ai_tracker_ai_tracker_watchdog.service",
    "reporter": "ai_tracker_ai_tracker_reporter.service",
    "mcp":      "ai_tracker_ai_tracker_mcp.service",
}

def check_docker_container(name):
    try:
        r = subprocess.run(["docker", "ps", "--filter", "name=" + name, "--format", "{{.Status}}"], capture_output=True, text=True, timeout=5)
        s = r.stdout.strip()
        if "Up" in s: return {"status": "healthy", "detail": s, "running": True}
        elif not s: return {"status": "stopped", "detail": "not found", "running": False}
        else: return {"status": "unhealthy", "detail": s, "running": False}
    except Exception as e: return {"status": "error", "detail": str(e), "running": False}

def check_systemd_service(name):
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", name], capture_output=True, text=True, timeout=5)
        s = r.stdout.strip()
        if s == "active": return {"status": "healthy", "detail": s, "running": True}
        elif s == "failed": return {"status": "failed", "detail": s, "running": False}
        else: return {"status": "unknown", "detail": s, "running": False}
    except Exception as e: return {"status": "error", "detail": str(e), "running": False}

def check_redis():
    try:
        r = subprocess.run(["docker", "exec", REDIS_CONTAINER, "redis-cli", "ping"], capture_output=True, text=True, timeout=5)
        if r.stdout.strip() == "PONG": return {"status": "healthy", "detail": "PONG", "host": "docker-redis-1:6379"}
        return {"status": "unhealthy", "detail": r.stdout.strip(), "host": "docker-redis-1:6379"}
    except Exception as e: return {"status": "error", "detail": str(e), "host": "docker-redis-1:6379"}

def check_neo4j():
    try:
        r = subprocess.run(["docker", "exec", NEO4J_CONTAINER, "cypher-shell", "-u", "neo4j", "-p", NEO4J_PASSWORD, "-d", "neo4j", "RETURN 1 as n"], capture_output=True, text=True, timeout=8)
        if "1 row" in r.stdout or r.returncode == 0: return {"status": "healthy", "detail": "connected", "host": NEO4J_CONTAINER + ":7687"}
        return {"status": "unhealthy", "detail": r.stdout[:100], "host": NEO4J_CONTAINER + ":7687"}
    except Exception as e: return {"status": "error", "detail": str(e), "host": NEO4J_CONTAINER + ":7687"}

def check_rss_proxy():
    try:
        import urllib.request
        proxy_url = os.environ.get("ANTHROPIC_BASE_URL", "http://")
        req = urllib.request.Request(proxy_url + "v1/models", headers={"Authorization": "Bearer " + MINIMAX_API_KEY})
        resp = urllib.request.urlopen(req, timeout=5)
        data = resp.read().decode()
        if "MiniMax" in data:
            models = json.loads(data).get("data", [])
            names = ", ".join([m.get("id", "") for m in models[:3]])
            return {"status": "healthy", "detail": "models: " + names, "host": proxy_url.rstrip("/")}
        return {"status": "unknown", "detail": "unexpected response", "host": proxy_url.rstrip("/")}
    except Exception as e:
        proxy_url = os.environ.get("ANTHROPIC_BASE_URL", "http://")
        return {"status": "error", "detail": str(e), "host": proxy_url.rstrip("/")}

def check_postgresql():
    try:
        import psycopg2
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DATABASE, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SELECT pg_postmaster_start_time()")
        start_time = cur.fetchone()[0]
        cur.execute("SELECT pg_database_size(%s)", (PG_DATABASE,))
        db_size = cur.fetchone()[0]
        conn.close()
        size_mb = round(db_size / 1024 / 1024, 1)
        detail = "%s:%d/%s (%.1fMB)" % (PG_HOST, PG_PORT, PG_DATABASE, size_mb)
        return {"status": "healthy", "host": "%s:%d" % (PG_HOST, PG_PORT), "database": PG_DATABASE, "version": version[:60], "uptime": str(start_time), "size_mb": size_mb, "detail": detail}
    except Exception as e:
        return {"status": "error", "host": "%s:%d" % (PG_HOST, PG_PORT), "database": PG_DATABASE, "detail": str(e)}

def check_task_queue():
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM task_queue WHERE created_at >= CURRENT_DATE")
        today = c.fetchone()["count"]
        c.execute("SELECT COUNT(*) FROM task_queue WHERE status = 'failed'")
        failed = c.fetchone()["count"]
        conn.close()
        counts = {row["status"]: row["count"] for row in rows}
        return {"status": "healthy" if failed < 50 else "warning", "counts": counts, "today_new": today, "failed_count": failed, "total": sum(counts.values())}
    except Exception as e: return {"status": "error", "detail": str(e)}

def check_celery_workers():
    try:
        r = subprocess.run(["pgrep", "-f", "celery.*worker.celery_app", "-c"], capture_output=True, text=True, timeout=5)
        count = int(r.stdout.strip())
        if count >= 8: return {"status": "healthy", "detail": str(count) + " workers", "count": count}
        elif count >= 1: return {"status": "degraded", "detail": str(count) + " worker(s)", "count": count}
        else: return {"status": "stopped", "detail": "no workers", "count": 0}
    except Exception as e: return {"status": "error", "detail": str(e)}

def check_feed_health():
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
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                days = (now - dt).total_seconds() / 86400
                if days > 7: stale_feeds.append({"url": url[:80], "last_crawl": last_crawl[:16], "days": int(days)})
            except: pass
        stale_sorted = sorted(stale_feeds, key=lambda x: x.get("days") or 0, reverse=True)
        return {"status": "warning" if len(stale_feeds) >= 5 else "healthy" if len(stale_feeds) == 0 else "ok", "total_monitored": len(metadata), "stale_count": len(stale_feeds), "stale_feeds": stale_sorted[:10]}
    except Exception as e: return {"status": "error", "detail": str(e)}

def get_full_health_report():
    services = {
        "redis": check_redis(), "neo4j": check_neo4j(),
        "rsshub": check_docker_container(RSSHUB_CONTAINER),
        "postgresql": check_postgresql(),
    }
    for k, v in SYSTEMD_SERVICES.items(): services[k] = check_systemd_service(v)
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "services": services, "workers": check_celery_workers(), "proxy": check_rss_proxy(), "task_queue": check_task_queue(), "feed_health": check_feed_health()}

if __name__ == "__main__":
    print(json.dumps(get_full_health_report(), indent=2, ensure_ascii=False))