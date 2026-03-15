#!/usr/bin/env python3
"""
AI Tracker System - 数据存储层

使用 SQLite 本地数据库存储实体、事件、关系
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ontology import ExtractionResult, Entity, Event, Relationship


# 数据库路径
DB_PATH = Path(__file__).parent / "ai_tracker.db"


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，创建三张表"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 实体表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            aliases_json TEXT,
            description TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 事件表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            involved_entities_json TEXT,
            summary TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 关系表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")


def save_extraction_result(result: ExtractionResult) -> None:
    """保存提取结果到数据库"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 保存实体
    for entity in result.entities:
        # 获取实体类型
        entity_type = entity.entity_type.value if hasattr(entity.entity_type, 'value') else str(entity.entity_type)
        
        cursor.execute("""
            INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            entity.id,
            entity_type,
            entity.name,
            json.dumps(entity.aliases),
            entity.description,
            entity.created_at.isoformat() if isinstance(entity.created_at, datetime) else str(entity.created_at)
        ))
    
    # 保存事件
    for event in result.events:
        cursor.execute("""
            INSERT OR REPLACE INTO events (id, title, date, involved_entities_json, summary, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event.id,
            event.title,
            event.date.isoformat() if isinstance(event.date, datetime) else str(event.date),
            json.dumps(event.involved_entity_ids),
            event.summary,
            event.source_url,
            event.created_at.isoformat() if isinstance(event.created_at, datetime) else str(event.created_at)
        ))
    
    # 保存关系
    for rel in result.relationships:
        cursor.execute("""
            INSERT OR REPLACE INTO relationships (source_id, target_id, relation_type, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            rel.source_id,
            rel.target_id,
            rel.relation_type.value if hasattr(rel.relation_type, 'value') else str(rel.relation_type),
            rel.start_date.isoformat() if rel.start_date and isinstance(rel.start_date, datetime) else (rel.start_date if rel.start_date else None),
            rel.end_date.isoformat() if rel.end_date and isinstance(rel.end_date, datetime) else (rel.end_date if rel.end_date else None)
        ))
    
    conn.commit()
    conn.close()
    print(f"✅ 保存成功: {len(result.entities)} 个实体, {len(result.events)} 个事件, {len(result.relationships)} 个关系")


def query_all_entities() -> list:
    """查询所有实体"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_all_events() -> list:
    """查询所有事件"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_all_relationships() -> list:
    """查询所有关系"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM relationships")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_entity_by_id(entity_id: str) -> Optional[dict]:
    """根据ID查询实体"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def verify_relationships_integrity() -> dict:
    """
    验证关系完整性：检查 relationships 中的 source_id 和 target_id 是否都存在于 entities 表中
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # 获取所有关系
    cursor.execute("SELECT source_id, target_id FROM relationships")
    relationships = cursor.fetchall()
    
    # 获取所有实体ID
    cursor.execute("SELECT id FROM entities")
    entity_ids = {row[0] for row in cursor.fetchall()}
    
    conn.close()
    
    # 检查完整性
    orphaned = []
    for rel in relationships:
        source_ok = rel[0] in entity_ids
        target_ok = rel[1] in entity_ids
        if not source_ok or not target_ok:
            orphaned.append({
                "source_id": rel[0],
                "source_valid": source_ok,
                "target_id": rel[1],
                "target_valid": target_ok
            })
    
    return {
        "total_relationships": len(relationships),
        "orphaned_relationships": len(orphaned),
        "orphaned_details": orphaned
    }


if __name__ == "__main__":
    # 测试
    init_db()
    print("\n📊 查询所有实体:")
    for e in query_all_entities():
        print(f"  - {e['id']}: {e['name']} ({e['type']})")
