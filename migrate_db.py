#!/usr/bin/env python3
"""
数据库迁移脚本 - 为 events 表添加 published_date 字段
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ai_tracker.db"


def migrate():
    """执行数据库迁移"""
    print("🔄 开始数据库迁移...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查 events 表结构
    cursor.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"当前 events 表字段: {columns}")
    
    # 检查是否已存在 published_date
    if "published_date" in columns:
        print("✅ published_date 字段已存在，跳过迁移")
    else:
        print("📦 添加 published_date 字段...")
        # 对于已有数据，设置 published_date = date（兼容旧数据）
        cursor.execute("ALTER TABLE events ADD COLUMN published_date TEXT")
        cursor.execute("UPDATE events SET published_date = date WHERE published_date IS NULL")
        conn.commit()
        print("✅ 迁移完成!")
    
    # 验证
    cursor.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"迁移后 events 表字段: {columns}")
    
    conn.close()
    print("🎉 数据库迁移完成!")


if __name__ == "__main__":
    migrate()
