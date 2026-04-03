#!/usr/bin/env python3
"""
AI Tracker - Ghost Task Rescue Vehicle
Re-queues pending and failed SQLite tasks to Redis queue.
"""

import sqlite3
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from database import DB_PATH, update_task_status
from worker import process_intel_task

def rescue_pending_tasks():
    print("SOS: Scanning SQLite for stranded tasks...")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, url FROM task_queue WHERE status IN ('pending', 'failed')")
    stranded_tasks = cursor.fetchall()

    if not stranded_tasks:
        print("OK: No stranded tasks found.")
        conn.close()
        return

    print(f"ALERT: Found {len(stranded_tasks)} stranded tasks! Re-queuing...")

    count = 0
    for task in stranded_tasks:
        tid = task["id"]
        url = task["url"]
        process_intel_task.delay(tid, url)
        update_task_status(tid, "processing")
        print(f"  -> Re-queued task #{tid}: {url}")
        count += 1

    print(f"Done: Re-queued {count} tasks to V8 Engine.")
    conn.close()

if __name__ == "__main__":
    rescue_pending_tasks()
