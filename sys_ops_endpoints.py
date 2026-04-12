# System operations API endpoints
import subprocess
import asyncio
from pathlib import Path
from fastapi import HTTPException

PROJECT_DIR = Path("/home/kangchen/.openclaw/workspace/ai_tracker_system")

# 实际注册的 systemd user service 名称
SYSTEMD_SERVICES = {
    # 日志选项
    "ai-celery":    "ai_tracker_ai_tracker_worker.service",
    "ai-server":     "ai_tracker_ai_tracker_server.service",
    "celery-beat":   "ai_tracker_ai_tracker_beat.service",
    "rsshub":        "docker-rsshub.service",
    # 额外选项（显示用）
    "ai-feeder":     "ai_tracker_ai_tracker_feeder.service",
    "ai-rescue":     "ai_tracker_ai_tracker_rescue.service",
    "ai-watchdog":   "ai_tracker_ai_tracker_watchdog.service",
    "ai-reporter":   "ai_tracker_ai_tracker_reporter.service",
}

LOG_FILES = {
    "celery_worker":  "/tmp/celery_worker.log",
    "celery_worker2": "/tmp/celery_worker2.log",
    "feeder":         "/home/kangchen/.openclaw/workspace/ai_tracker_system/feeder.log",
    "reporter":       "/home/kangchen/.openclaw/workspace/ai_tracker_system/reporter.log",
    "server":         "/home/kangchen/.openclaw/workspace/ai_tracker_system/server.log",
    "celery_beat":    "/home/kangchen/.openclaw/workspace/ai_tracker_system/celery_beat.log",
}

# journalctl 实际用户服务
USER_JOURNAL_SERVICES = {
    "ai-celery":    "ai_tracker_ai_tracker_worker.service",
    "ai-server":    "ai_tracker_ai_tracker_server.service",
    "celery-beat":  "ai_tracker_ai_tracker_beat.service",
    "ai-feeder":    "ai_tracker_ai_tracker_feeder.service",
    "ai-rescue":    "ai_tracker_ai_tracker_rescue.service",
    "ai-watchdog":  "ai_tracker_ai_tracker_watchdog.service",
    "ai-reporter":  "ai_tracker_ai_tracker_reporter.service",
}


def register_sys_ops_endpoints(app):
    @app.get("/api/logs")
    async def get_logs(log_name: str = "ai-celery", lines: int = 200):
        # journalctl-based logs (user systemd services)
        svc = USER_JOURNAL_SERVICES.get(log_name)
        if svc:
            try:
                result = subprocess.run(
                    ["journalctl", "--user", "-u", svc, "-n", str(lines), "--no-pager", "--no-full", "-o", "short-iso"],
                    capture_output=True, text=True, timeout=15
                )
                raw_lines = result.stdout.splitlines()
                return {
                    "log_name": log_name,
                    "lines": [line.rstrip() for line in raw_lines],
                    "total_lines": len(raw_lines),
                    "source": "journalctl",
                    "service": svc,
                    "error": None
                }
            except subprocess.TimeoutExpired:
                return {"log_name": log_name, "lines": [], "total_lines": 0, "source": "journalctl", "service": svc, "error": "journalctl timeout"}
            except Exception as e:
                return {"log_name": log_name, "lines": [], "total_lines": 0, "source": "journalctl", "service": svc, "error": str(e)}

        # Docker container logs
        if log_name == "rsshub":
            try:
                result = subprocess.run(
                    ["docker", "logs", "--tail", str(lines), "rsshub"],
                    capture_output=True, text=True, timeout=10
                )
                raw_lines = (result.stdout + result.stderr).splitlines()[-lines:]
                return {
                    "log_name": log_name,
                    "lines": [line.rstrip() for line in raw_lines],
                    "total_lines": len(raw_lines),
                    "source": "docker",
                    "service": "rsshub",
                    "error": None
                }
            except Exception as e:
                return {"log_name": log_name, "lines": [], "total_lines": 0, "source": "docker", "service": "rsshub", "error": str(e)}

        # file-based logs
        log_path = LOG_FILES.get(log_name)
        if not log_path:
            raise HTTPException(status_code=400, detail=f"Unknown log: {log_name}")
        try:
            if not Path(log_path).exists():
                return {"log_name": log_name, "lines": [], "total_lines": 0, "source": "file", "path": log_path, "error": None}
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            total_lines = len(all_lines)
            recent_lines = all_lines[-lines:] if lines > 0 else all_lines
            return {
                "log_name": log_name,
                "lines": [line.rstrip() for line in recent_lines],
                "total_lines": total_lines,
                "source": "file",
                "path": log_path,
                "error": None
            }
        except Exception as e:
            return {"log_name": log_name, "lines": [], "total_lines": 0, "source": "file", "path": log_path, "error": str(e)}

    @app.get("/api/logs/names")
    async def get_log_names():
        available = {}
        for name, path in LOG_FILES.items():
            exists = Path(path).exists()
            size = Path(path).stat().st_size if exists else 0
            mtime = Path(path).stat().st_mtime if exists else 0
            available[name] = {"exists": exists, "size": size, "path": path, "mtime": mtime, "source": "file"}
        for name, svc in USER_JOURNAL_SERVICES.items():
            available[name] = {"exists": True, "size": 0, "path": f"journalctl --user -u {svc}", "source": "journalctl", "service": svc}
        return available

    @app.post("/api/service/control")
    async def control_service(action: str = "status", service_name: str = "ai-celery"):
        if action not in ("start", "stop", "restart", "status"):
            raise HTTPException(status_code=400, detail="action must be start/stop/restart/status")
        svc = USER_JOURNAL_SERVICES.get(service_name)
        if not svc:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
        try:
            if action == "status":
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", svc],
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
                ["systemctl", "--user", action, svc],
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
        svc = "ai_tracker_ai_tracker_worker.service"
        try:
            subprocess.run(["systemctl", "--user", "restart", svc], capture_output=True, timeout=30)
            await asyncio.sleep(3)
            check = subprocess.run(["pgrep", "-f", "celery.*worker.celery_app"], capture_output=True, text=True, timeout=5)
            pids = [p for p in check.stdout.strip().split("\n") if p]
            return {"success": len(pids) > 0, "action": "restart", "pids": pids, "error": None}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/service/worker/start")
    async def start_celery_worker():
        svc = "ai_tracker_ai_tracker_worker.service"
        try:
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=30)
            await asyncio.sleep(3)
            check = subprocess.run(["pgrep", "-f", "celery.*worker.celery_app"], capture_output=True, text=True, timeout=5)
            pids = [p for p in check.stdout.strip().split("\n") if p]
            return {"success": len(pids) > 0, "action": "start", "pids": pids}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/service/worker/stop")
    async def stop_celery_worker():
        svc = "ai_tracker_ai_tracker_worker.service"
        try:
            subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=30)
            return {"success": True, "action": "stop"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/feeder/run")
    async def run_feeder():
        svc = "ai_tracker_ai_tracker_feeder.service"
        try:
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=10)
            return {"success": True, "action": "triggered", "service": svc}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/health")
    async def get_health():
        from health_check import get_full_health_report
        return get_full_health_report()