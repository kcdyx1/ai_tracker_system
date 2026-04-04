# System operations API endpoints
import subprocess
import asyncio
from pathlib import Path
from fastapi import HTTPException

LOG_FILES = {
    "celery_worker": "/tmp/celery_worker.log",
    "feeder": "/home/kangchen/.openclaw/workspace/ai_tracker_system/feeder.log",
    "reporter": "/home/kangchen/.openclaw/workspace/ai_tracker_system/reporter.log",
    "server": "/home/kangchen/.openclaw/workspace/ai_tracker_system/server.log",
    "celery_beat": "/home/kangchen/.openclaw/workspace/ai_tracker_system/celery_beat.log",
}

SYSTEMD_SERVICES = {
    "ai-celery": "ai-celery.service",
    "ai-server": "ai-server.service",
    "ai-mcp": "ai-mcp.service",
    "rsshub": "docker-rsshub.service",
}

PROJECT_DIR = "/home/kangchen/.openclaw/workspace/ai_tracker_system"

def register_sys_ops_endpoints(app):
    @app.get("/api/logs")
    async def get_logs(log_name: str = "celery_worker", lines: int = 100):
        log_path = LOG_FILES.get(log_name)
        if not log_path:
            raise HTTPException(status_code=400, detail=f"Unknown log: {log_name}")
        try:
            if not Path(log_path).exists():
                return {"log_name": log_name, "lines": [], "total_lines": 0, "error": None}
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
            total_lines = len(all_lines)
            recent_lines = all_lines[-lines:] if lines > 0 else all_lines
            return {
                "log_name": log_name,
                "lines": [line.rstrip() for line in recent_lines],
                "total_lines": total_lines,
                "error": None
            }
        except Exception as e:
            return {"log_name": log_name, "lines": [], "total_lines": 0, "error": str(e)}

    @app.get("/api/logs/names")
    async def get_log_names():
        available = {}
        for name, path in LOG_FILES.items():
            exists = Path(path).exists()
            size = Path(path).stat().st_size if exists else 0
            available[name] = {"exists": exists, "size": size, "path": path}
        return available

    @app.post("/api/service/control")
    async def control_service(action: str = "status", service_name: str = "ai-celery"):
        if action not in ("start", "stop", "restart", "status"):
            raise HTTPException(status_code=400, detail="action must be start/stop/restart/status")
        if service_name not in SYSTEMD_SERVICES:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
        svc = SYSTEMD_SERVICES[service_name]
        try:
            if action == "status":
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=10
                )
                return {
                    "service": service_name,
                    "action": action,
                    "unit": svc,
                    "active": result.stdout.strip() == "active",
                    "output": result.stdout.strip(),
                    "error": None
                }
            result = subprocess.run(
                ["sudo", "systemctl", action, svc],
                capture_output=True, text=True, timeout=30
            )
            return {
                "service": service_name,
                "action": action,
                "unit": svc,
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.stderr else None
            }
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Service operation timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/service/worker/restart")
    async def restart_celery_worker():
        try:
            kill_result = subprocess.run(
                ["pkill", "-f", "celery.*worker.celery_app"],
                capture_output=True, text=True, timeout=10
            )
            await asyncio.sleep(2)
            start_result = subprocess.Popen(
                ["./venv/bin/python", "-m", "celery", "-A", "worker.celery_app", "worker",
                 "--loglevel=info"],
                cwd=PROJECT_DIR,
                stdout=open("/tmp/celery_worker.log", "a"),
                stderr=subprocess.STDOUT
            )
            await asyncio.sleep(2)
            check = subprocess.run(
                ["pgrep", "-f", "celery.*worker.celery_app"],
                capture_output=True, text=True, timeout=5
            )
            pids = [p for p in check.stdout.strip().split(chr(10)) if p]
            return {
                "success": len(pids) > 0,
                "action": "restart",
                "pids": pids,
                "kill_output": kill_result.stdout.strip(),
                "start_output": str(start_result.pid),
                "error": None
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/service/worker/start")
    async def start_celery_worker():
        try:
            check = subprocess.run(
                ["pgrep", "-f", "celery.*worker.celery_app"],
                capture_output=True, text=True, timeout=5
            )
            pids_before = [p for p in check.stdout.strip().split(chr(10)) if p]
            subprocess.Popen(
                ["./venv/bin/python", "-m", "celery", "-A", "worker.celery_app", "worker",
                 "--loglevel=info"],
                cwd=PROJECT_DIR,
                stdout=open("/tmp/celery_worker.log", "a"),
                stderr=subprocess.STDOUT
            )
            await asyncio.sleep(3)
            check = subprocess.run(
                ["pgrep", "-f", "celery.*worker.celery_app"],
                capture_output=True, text=True, timeout=5
            )
            pids_after = [p for p in check.stdout.strip().split(chr(10)) if p]
            return {
                "success": len(pids_after) > len(pids_before),
                "action": "start",
                "pids": pids_after
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/service/worker/stop")
    async def stop_celery_worker():
        try:
            result = subprocess.run(
                ["pkill", "-f", "celery.*worker.celery_app"],
                capture_output=True, text=True, timeout=10
            )
            return {
                "success": result.returncode == 0,
                "action": "stop",
                "output": result.stdout.strip()
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/feeder/run")
    async def run_feeder():
        try:
            lock_file = Path(PROJECT_DIR) / ".auto_feeder.lock"
            if lock_file.exists():
                return {"success": False, "output": "auto_feeder already running"}
            proc = subprocess.Popen(
                ["./venv/bin/python", "-u", "auto_feeder.py"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            return {"success": True, "action": "started", "pid": proc.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
