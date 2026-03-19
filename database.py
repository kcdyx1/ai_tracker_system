#!/usr/bin/env python3
"""
AI Tracker System - 数据存储层 (超高并发防御版)
全面加固：所有数据库直连均已配备 try...finally 强行关门机制
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from ontology import ExtractionResult, Entity, Event, Relationship

DB_PATH = Path(__file__).parent / "ai_tracker.db"

def get_connection() -> sqlite3.Connection:
    # 延长超时至 60 秒，保证极端负载不报错
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db() -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
                aliases_json TEXT, description TEXT, created_at TEXT NOT NULL
            )
        """)
        # 包含全量 L2 字段的事件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, date TEXT NOT NULL,
                published_date TEXT NOT NULL, involved_entities_json TEXT,
                summary TEXT, source_url TEXT, created_at TEXT NOT NULL,
                risk_level TEXT, sentiment TEXT
            )
        """)
        # 智能对齐旧数据库的列结构
        for col in ["published_date", "attributes_json", "risk_level", "sentiment"]:
            try: cursor.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
            except: pass
        try: cursor.execute("ALTER TABLE entities ADD COLUMN attributes_json TEXT")
        except: pass
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL, target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL, start_date TEXT, end_date TEXT,
                evidence TEXT,
                UNIQUE(source_id, target_id, relation_type)
            )
        """)
        try: cursor.execute("ALTER TABLE relationships ADD COLUMN evidence TEXT")
        except: pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending', error_message TEXT, created_at TEXT NOT NULL
            )
        """)
        try: cursor.execute("ALTER TABLE task_queue ADD COLUMN error_message TEXT")
        except: pass
        
        conn.commit()
        print(f"✅ 数据库底座就绪: {DB_PATH}")
    finally:
        conn.close()

def save_extraction_result(result: ExtractionResult) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for entity in result.entities:
            entity_type = entity.entity_type.value if hasattr(entity.entity_type, 'value') else str(entity.entity_type)
            entity_dict = entity.model_dump()
            base_keys = {'id', 'entity_type', 'name', 'aliases', 'description', 'created_at'}
            attributes = {k: v for k, v in entity_dict.items() if k not in base_keys and v is not None and v != []}

            cursor.execute("""
                INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (entity.id, entity_type, entity.name, json.dumps(entity.aliases), entity.description, 
                  entity.created_at.isoformat() if isinstance(entity.created_at, datetime) else str(entity.created_at), json.dumps(attributes, ensure_ascii=False)))
        
        for event in result.events:
            cursor.execute("""
                INSERT OR REPLACE INTO events (id, title, date, published_date, involved_entities_json, summary, source_url, created_at, risk_level, sentiment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event.id, event.title, event.date.isoformat() if isinstance(event.date, datetime) else str(event.date),
                  event.published_date.isoformat() if isinstance(event.published_date, datetime) else str(event.published_date),
                  json.dumps(event.involved_entity_ids), event.summary, event.source_url,
                  event.created_at.isoformat() if isinstance(event.created_at, datetime) else str(event.created_at),
                  getattr(event, 'risk_level', None), getattr(event, 'sentiment', None)))
        
        for rel in result.relationships:
            cursor.execute("""
                INSERT OR IGNORE INTO relationships (source_id, target_id, relation_type, start_date, end_date, evidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (rel.source_id, rel.target_id, rel.relation_type.value if hasattr(rel.relation_type, 'value') else str(rel.relation_type),
                  rel.start_date.isoformat() if rel.start_date and isinstance(rel.start_date, datetime) else (rel.start_date if rel.start_date else None),
                  rel.end_date.isoformat() if rel.end_date and isinstance(rel.end_date, datetime) else (rel.end_date if rel.end_date else None),
                  getattr(rel, 'evidence', None)))
        conn.commit()
    finally:
        conn.close()

def query_all_entities() -> list:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities")
        return [dict(r) for r in cursor.fetchall()]
    finally: conn.close()

def query_entity_by_id(entity_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally: conn.close()

def get_recent_events(days: int = 7) -> list:
    from datetime import timedelta
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("SELECT * FROM events WHERE published_date >= ? ORDER BY published_date DESC", (cutoff_date,))
        return [dict(r) for r in cursor.fetchall()]
    finally: conn.close()

def push_task(url: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM task_queue WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO task_queue (url, status, created_at) VALUES (?, 'pending', ?)", (url, datetime.now().isoformat()))
            conn.commit(); return True
        else:
            if row[0] in ('failed', 'completed'):
                cursor.execute("UPDATE task_queue SET status = 'pending', error_message = NULL, created_at = ? WHERE url = ?", (datetime.now().isoformat(), url))
                conn.commit(); return True
            return False
    finally: conn.close()

def get_pending_task() -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE task_queue SET status = 'processing' 
            WHERE id = (SELECT id FROM task_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1)
            RETURNING id, url
        """)
        row = cursor.fetchone()
        conn.commit()
        if row: return {"id": row['id'], "url": row['url']}
        return None
    except Exception as e:
        print(f"❌ get_pending_task 报错: {e}")
        return None
    finally: conn.close()

def update_task_status(task_id: int, status: str, error_msg: str = None) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE task_queue SET status = ?, error_message = ? WHERE id = ?", (status, error_msg, task_id))
        conn.commit()
    finally: conn.close()

def get_events_for_entity(entity_id: str) -> list:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE involved_entities_json LIKE ? ORDER BY date DESC", (f'%"{entity_id}"%',))
        return [dict(r) for r in cursor.fetchall()]
    finally: conn.close()

def get_smart_rag_context(query: str) -> str:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, aliases_json FROM entities")
        all_entities = cursor.fetchall()
        matched_entity_ids = set()
        for row in all_entities:
            eid, name, aliases_str = row[0], row[1], row[2]
            if name.lower() in query.lower(): matched_entity_ids.add(eid)
            if aliases_str:
                try:
                    for alias in json.loads(aliases_str):
                        if alias.lower() in query.lower(): matched_entity_ids.add(eid)
                except: pass

        if not matched_entity_ids:
            cursor.execute("SELECT title, date, summary FROM events ORDER BY date DESC LIMIT 30")
            events = cursor.fetchall()
            return "\n".join(["【全局动态】："] + [f"- [{e[1][:10]}] {e[0]}: {e[2]}" for e in events])

        matched_ids_list = list(matched_entity_ids)
        context_parts = [f"【精准检索】档案：\n"]
        for eid in matched_ids_list:
            cursor.execute("SELECT title, date, summary, risk_level, sentiment FROM events WHERE involved_entities_json LIKE ? ORDER BY date DESC LIMIT 20", (f'%"{eid}"%',))
            events = cursor.fetchall()
            if events:
                context_parts.append("\n--- 关联事件 ---")
                for e in events:
                    risk_tag = f"[{e['risk_level']}] " if dict(e).get('risk_level') else ""
                    context_parts.append(f"- [{e[1][:10]}] {risk_tag}{e[0]}: {e[2]}")

        placeholders = ','.join(['?'] * len(matched_ids_list))
        cursor.execute(f"SELECT r.relation_type, e1.name, e2.name, r.evidence FROM relationships r JOIN entities e1 ON r.source_id = e1.id JOIN entities e2 ON r.target_id = e2.id WHERE r.source_id IN ({placeholders}) OR r.target_id IN ({placeholders}) LIMIT 50", matched_ids_list * 2)
        relationships = cursor.fetchall()
        if relationships:
            context_parts.append("\n--- 关系网 ---")
            for r in relationships:
                evid = f" (证据: {r[3]})" if r[3] else ""
                context_parts.append(f"- {r[1]} --[{r[0]}]--> {r[2]}{evid}")

        return "\n".join(context_parts)
    finally:
        conn.close()