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
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    # 开启 WAL 模式，提高并发性能
    conn.execute('PRAGMA journal_mode=WAL;')
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
            published_date TEXT NOT NULL,
            involved_entities_json TEXT,
            summary TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 兼容旧数据：尝试添加 published_date 字段
    
    # 兼容旧数据：尝试添加 attributes_json 字段用于弹性存储
    try:
        cursor.execute("ALTER TABLE entities ADD COLUMN attributes_json TEXT")
    except:
        pass  # 字段已存在则忽略

    try:
        cursor.execute("ALTER TABLE events ADD COLUMN published_date TEXT")
    except:
        pass  # 字段已存在则忽略
    
    # 关系表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            -- 确保两个实体间的同种关系只能有一条
            UNIQUE(source_id, target_id, relation_type)
        )
    """)
    
    # 任务队列表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 兼容旧数据：尝试添加 error_message 字段
    try:
        cursor.execute("ALTER TABLE task_queue ADD COLUMN error_message TEXT")
    except:
        pass  # 字段已存在则忽略
    
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
        
        # 提取基类之外的弹性属性
        entity_dict = entity.model_dump()
        base_keys = {'id', 'entity_type', 'name', 'aliases', 'description', 'created_at'}
        attributes = {k: v for k, v in entity_dict.items() if k not in base_keys and v is not None and v != []}

        cursor.execute("""
            INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            entity.id,
            entity_type,
            entity.name,
            json.dumps(entity.aliases),
            entity.description,
            entity.created_at.isoformat() if isinstance(entity.created_at, datetime) else str(entity.created_at),
            json.dumps(attributes, ensure_ascii=False)
        ))
    
    # 保存事件
    for event in result.events:
        cursor.execute("""
            INSERT OR REPLACE INTO events (id, title, date, published_date, involved_entities_json, summary, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.id,
            event.title,
            event.date.isoformat() if isinstance(event.date, datetime) else str(event.date),
            event.published_date.isoformat() if isinstance(event.published_date, datetime) else str(event.published_date),
            json.dumps(event.involved_entity_ids),
            event.summary,
            event.source_url,
            event.created_at.isoformat() if isinstance(event.created_at, datetime) else str(event.created_at)
        ))
    
    # 保存关系 (使用 INSERT OR IGNORE，如果唯一约束冲突则忽略)
    for rel in result.relationships:
        cursor.execute("""
            INSERT OR IGNORE INTO relationships (source_id, target_id, relation_type, start_date, end_date)
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


def get_recent_events(days: int = 7) -> list:
    """
    获取最近 N 天的事件
    
    Args:
        days: 天数，默认 7 天
        
    Returns:
        事件列表
    """
    from datetime import timedelta
    conn = get_connection()
    cursor = conn.cursor()
    
    # 计算日期边界
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    # 查询 events 表中 published_date >= cutoff_date 的记录
    cursor.execute("""
        SELECT * FROM events
        WHERE published_date >= ?
        ORDER BY published_date DESC
    """, (cutoff_date,))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


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


# ============================================================================
# 任务队列函数
# ============================================================================

def push_task(url: str) -> bool:
    """
    将 URL 插入任务队列（状态为 pending）
    如果 URL 已存在且状态为 failed/completed，则重置为 pending 重新处理
    返回是否成功加入或重试
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 先查询 URL 是否存在
        cursor.execute("SELECT status FROM task_queue WHERE url = ?", (url,))
        row = cursor.fetchone()
        
        if row is None:
            # 不存在，插入新任务
            cursor.execute("""
                INSERT INTO task_queue (url, status, created_at)
                VALUES (?, 'pending', ?)
            """, (url, datetime.now().isoformat()))
            conn.commit()
            return True
        else:
            # 已存在，检查状态
            status = row[0]
            if status in ('failed', 'completed'):
                # 重新打回队列
                cursor.execute("""
                    UPDATE task_queue 
                    SET status = 'pending', error_message = NULL, created_at = ? 
                    WHERE url = ?
                """, (datetime.now().isoformat(), url))
                conn.commit()
                return True
            else:
                # 正在处理中，不做操作
                return False
    except Exception as e:
        print(f"❌ push_task 错误: {e}")
        return False
    finally:
        conn.close()


def get_pending_task() -> dict | None:
    """
    查找一条 status 为 'pending' 的任务
    将其状态更新为 'processing'，并返回该任务的 id 和 url
    注意使用事务防止并发冲突
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 使用事务确保原子性
        cursor.execute("BEGIN EXCLUSIVE")
        
        # 查找一条 pending 任务
        cursor.execute("""
            SELECT id, url FROM task_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            task_id, url = row
            # 更新状态为 processing
            cursor.execute("""
                UPDATE task_queue
                SET status = 'processing'
                WHERE id = ?
            """, (task_id,))
            conn.commit()
            conn.close()
            return {"id": task_id, "url": url}
        
        conn.commit()
        conn.close()
        return None
    except Exception as e:
        print(f"❌ get_pending_task 错误: {e}")
        conn.close()
        return None


def update_task_status(task_id: int, status: str, error_msg: str = None) -> None:
    """
    更新任务的最终状态（如 'completed' 或 'failed'）
    
    Args:
        task_id: 任务ID
        status: 新状态
        error_msg: 错误信息（可选）
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE task_queue
            SET status = ?, error_message = ?
            WHERE id = ?
        """, (status, error_msg, task_id))
        conn.commit()
    except Exception as e:
        print(f"❌ update_task_status 错误: {e}")
    finally:
        conn.close()


# ============================================================================
# RAG 查询函数
# ============================================================================

def get_events_for_entity(entity_id: str) -> list:
    """
    获取与指定实体相关的事件
    
    Args:
        entity_id: 实体ID
        
    Returns:
        事件列表
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events 
        WHERE involved_entities_json LIKE ? 
        ORDER BY date DESC
    """, (f'%"{entity_id}"%',))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_smart_rag_context(query: str) -> str:
    """
    智能 Graph-RAG 检索：
    1. 根据 query 提取提及的实体
    2. 精准查询这些实体的关联事件和关系
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1. 实体探针：找出 query 中提及的实体
    cursor.execute("SELECT id, name, aliases_json FROM entities")
    all_entities = cursor.fetchall()

    matched_entity_ids = set()
    for row in all_entities:
        eid, name, aliases_str = row[0], row[1], row[2]
        # 匹配名称
        if name.lower() in query.lower():
            matched_entity_ids.add(eid)
        # 匹配别名
        if aliases_str:
            try:
                aliases = json.loads(aliases_str)
                for alias in aliases:
                    if alias.lower() in query.lower():
                        matched_entity_ids.add(eid)
            except:
                pass

    # 2. 如果没有任何匹配，降级为全局最新摘要（Fallback）
    if not matched_entity_ids:
        cursor.execute("SELECT title, date, summary FROM events ORDER BY date DESC LIMIT 30")
        events = cursor.fetchall()
        conn.close()

        ctx = ["【系统提示】未在问题中检测到明确的具体实体，以下提供全局最新产业动态："]
        for e in events:
            ctx.append(f"- [{e[1][:10]}] {e[0]}: {e[2]}")
        return "\n".join(ctx)

    # 3. 如果有匹配，执行图谱精准下钻 (Drill-down)
    matched_ids_list = list(matched_entity_ids)
    context_parts = [f"【精准检索】系统在提问中识别到了 {len(matched_ids_list)} 个核心实体，以下是它们的专属档案：\n"]

    # 获取精准事件
    for eid in matched_ids_list:
        cursor.execute("SELECT title, date, summary FROM events WHERE involved_entities_json LIKE ? ORDER BY date DESC LIMIT 20", (f'%"{eid}"%',))
        events = cursor.fetchall()
        if events:
            context_parts.append(f"\n--- 关联事件 ---")
            for e in events:
                context_parts.append(f"- [{e[1][:10]}] {e[0]}: {e[2]}")

    # 获取精准连线关系
    placeholders = ','.join(['?'] * len(matched_ids_list))
    cursor.execute(f"""
        SELECT r.relation_type, e1.name, e2.name
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        WHERE r.source_id IN ({placeholders}) OR r.target_id IN ({placeholders})
        LIMIT 50
    """, matched_ids_list * 2)
    relationships = cursor.fetchall()

    if relationships:
        context_parts.append(f"\n--- 实体商业/技术关系网 ---")
        for r in relationships:
            context_parts.append(f"- {r[1]} --[{r[0]}]--> {r[2]}")

    conn.close()
    return "\n".join(context_parts)
