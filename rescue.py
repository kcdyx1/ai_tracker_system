#!/usr/bin/env python3
"""
AI Tracker - Ghost Task Rescue Vehicle
Re-queues pending and failed tasks to Redis queue via PostgreSQL.
"""

import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from database import get_connection
from worker import process_intel_task


def rescue_pending_tasks():
    print("SOS: Scanning PostgreSQL for stranded tasks...")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, url FROM task_queue WHERE status IN ('pending', 'failed') LIMIT 5000")
    stranded_tasks = cursor.fetchall()

    if not stranded_tasks:
        print("OK: No stranded tasks found.")
        conn.close()
        return

    print(f"ALERT: Found {len(stranded_tasks)} stranded tasks! Re-queuing...")

    count = 0
    for row in stranded_tasks:
        tid = row["id"]
        url = row["url"]
        try:
            process_intel_task.delay(tid, url)
            print(f"  -> Re-queued task #{tid}: {url[:60]}")
            count += 1
        except Exception as e:
            print(f"  !! Failed to queue #{tid}: {e}")

    print(f"Done: Re-queued {count} tasks to V8 Engine.")
    conn.close()


if __name__ == "__main__":
    rescue_pending_tasks()
