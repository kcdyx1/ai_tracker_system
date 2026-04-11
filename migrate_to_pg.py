#!/usr/bin/env python3
"""
从 SQLite 迁移数据到 PostgreSQL
运行一次即可
"""
import sqlite3
import psycopg2
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SQLITE_PATH = Path(__file__).parent / "ai_tracker.db"
PG_HOST = os.environ.get("AI_TRACKER_PG_HOST", "172.20.0.4")
PG_PORT = int(os.environ.get("AI_TRACKER_PG_PORT", "5432"))
PG_USER = os.environ.get("AI_TRACKER_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("AI_TRACKER_PG_PASSWORD", "difyai123456")
PG_DATABASE = os.environ.get("AI_TRACKER_PG_DATABASE", "ai_tracker")


def _format_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        s = dt.strip()
        try:
            if s.endswith("+00:00"):
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.fromisoformat(s.replace("+00:00", ""))
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return dt
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def migrate():
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, database=PG_DATABASE
    )
    pg_conn.autocommit = False
    pg_cursor = pg_conn.cursor()

    # 1. entities
    print("迁移 entities...")
    sqlite_cursor.execute("SELECT * FROM entities")
    entities = sqlite_cursor.fetchall()
    for row in entities:
        d = dict(row)
        pg_cursor.execute("""
            INSERT INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            d["id"], d["type"], d["name"],
            d.get("aliases_json"), d.get("description"),
            _format_dt(d.get("created_at")),
            d.get("attributes_json")
        ))
    pg_conn.commit()
    print(f"  entities: {len(entities)} 条")

    # 2. events
    print("迁移 events...")
    sqlite_cursor.execute("SELECT * FROM events")
    events = sqlite_cursor.fetchall()
    for row in events:
        d = dict(row)
        pg_cursor.execute("""
            INSERT INTO events (id, title, date, published_date, involved_entities_json,
                                summary, source_url, created_at, risk_level, sentiment, attributes_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            d["id"], d["title"], _format_dt(d.get("date")),
            _format_dt(d.get("published_date")),
            d.get("involved_entities_json"), d.get("summary"),
            d.get("source_url"), _format_dt(d.get("created_at")),
            d.get("risk_level"), d.get("sentiment"),
            d.get("attributes_json")
        ))
    pg_conn.commit()
    print(f"  events: {len(events)} 条")

    # 3. task_queue
    print("迁移 task_queue...")
    sqlite_cursor.execute("SELECT * FROM task_queue")
    tasks = sqlite_cursor.fetchall()
    for row in tasks:
        d = dict(row)
        pg_cursor.execute("""
            INSERT INTO task_queue (id, url, status, error_message, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
        """, (
            d["id"], d["url"], d.get("status", "pending"),
            d.get("error_message"), _format_dt(d.get("created_at"))
        ))
    pg_conn.commit()
    print(f"  task_queue: {len(tasks)} 条")

    # 4. relationships
    print("迁移 relationships...")
    sqlite_cursor.execute("SELECT * FROM relationships")
    rels = sqlite_cursor.fetchall()
    for row in rels:
        d = dict(row)
        pg_cursor.execute("""
            INSERT INTO relationships (id, source_id, target_id, relation_type, start_date, end_date, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, target_id, relation_type) DO NOTHING
        """, (
            d["id"], d["source_id"], d["target_id"],
            d.get("relation_type"), _format_dt(d.get("start_date")),
            _format_dt(d.get("end_date")), d.get("evidence")
        ))
    pg_conn.commit()
    print(f"  relationships: {len(rels)} 条")

    sqlite_conn.close()
    pg_conn.close()
    print("✅ 迁移完成！")


if __name__ == "__main__":
    migrate()
