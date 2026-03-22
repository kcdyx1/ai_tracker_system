#!/usr/bin/env python3
"""
AI Tracker - 幽灵任务救援车
专门用于把卡在 SQLite 里的 pending 任务，重新打入 Redis 队列。
"""

import sqlite3
from pathlib import Path
from worker import process_intel_task

# 指向你的数据库
DB_PATH = Path(__file__).parent / "ai_tracker.db"

def rescue_pending_tasks():
    print("🚑 幽灵救援车出动：正在扫描 SQLite 寻找失联任务...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 抓出所有 pending 状态的任务
    cursor.execute("SELECT id, url FROM task_queue WHERE status = 'pending'")
    stranded_tasks = cursor.fetchall()
    
    if not stranded_tasks:
        print("✅ 扫描完毕，没有发现失联任务。")
        conn.close()
        return

    print(f"🚨 警报：发现 {len(stranded_tasks)} 个被困任务！准备装填至 Redis 导弹舱...")
    
    count = 0
    for task in stranded_tasks:
        task_id = task['id']
        url = task['url']
        # ⚡️ 核心动作：重新调用 Celery 的 delay 方法打入队列
        process_intel_task.delay(task_id, url)
        print(f"  -> 🚀 已重新发射任务 #{task_id}: {url}")
        count += 1
        
    print(f"🎉 救援圆满完成！共向 V8 引擎补发了 {count} 个任务。")
    conn.close()

if __name__ == "__main__":
    rescue_pending_tasks()