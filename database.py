#!/usr/bin/env python3
"""
AI Tracker System - 数据存储层 (PostgreSQL 版)
迁移自 SQLite，替换为 psycopg2，支持多 worker 并发
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, Json

# PostgreSQL 连接配置
PG_HOST = os.environ.get("AI_TRACKER_PG_HOST", "172.20.0.4")
PG_PORT = int(os.environ.get("AI_TRACKER_PG_PORT", "5432"))
PG_USER = os.environ.get("AI_TRACKER_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("AI_TRACKER_PG_PASSWORD", "difyai123456")
PG_DATABASE = os.environ.get("AI_TRACKER_PG_DATABASE", "ai_tracker")

# SQLite 兼容层路径（用于迁移）


def _get_pg_conn():
    """获取 PostgreSQL 连接"""
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DATABASE,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
    )
    conn.autocommit = False
    return conn


def _format_dt(dt):
    """Normalize datetime to ISO string with UTC timezone"""
    if dt is None:
        return None
    if isinstance(dt, str):
        s = dt.strip()
        try:
            # fromisoformat handles any offset (+00:00, +08:00, -05:00, Z) correctly
            dt = datetime.fromisoformat(s)
            # Convert to UTC using astimezone (NOT replace, which just swaps tz without converting time)
            dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except ValueError:
            return dt
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        # Naive datetime: treat as local time, convert to UTC
        dt = dt.replace(tzinfo=timezone.utc)
    elif hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def get_connection():
    """兼容 SQLite 版 get_connection() 的接口"""
    return _get_pg_conn()


def init_db() -> None:
    """初始化 PostgreSQL 表结构"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()

        # entities 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                aliases_json TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                attributes_json TEXT
            )
        """)

        # events 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                published_date TEXT NOT NULL,
                involved_entities_json TEXT,
                summary TEXT,
                source_url TEXT,
                created_at TEXT NOT NULL,
                risk_level TEXT,
                sentiment TEXT,
                attributes_json TEXT
            )
        """)

        # relationships 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id SERIAL PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                evidence TEXT,
                UNIQUE(source_id, target_id, relation_type)
            )
        """)

        # task_queue 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id SERIAL PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL,
                fail_count INTEGER DEFAULT 0,
                next_retry_at TIMESTAMP WITH TIME ZONE
            )
        """)

        # 索引
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_events_entities ON events(involved_entities_json)",
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)",
            "CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status)",
            "CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_date)",
                "CREATE INDEX IF NOT EXISTS idx_task_retry ON task_queue(next_retry_at) WHERE status = 'failed' AND fail_count > 0",
        ]
        for idx_sql in indexes:
            cursor.execute(idx_sql)

        conn.commit()
        print(f"✅ PostgreSQL 数据库初始化完成: {PG_DATABASE}@{PG_HOST}")

        ensure_fts_tables()

    finally:
        conn.close()


def ensure_fts_tables() -> None:
    """初始化 PostgreSQL 全文检索（FTS）"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()

        # 实体 FTS
        cursor.execute("""
            CREATE EXTENSION IF NOT EXISTS pg_trgm
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entities_name_trgm ON entities USING gin (name gin_trgm_ops)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entities_desc_trgm ON entities USING gin (description gin_trgm_ops)
        """)

        # 事件 FTS
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_title_trgm ON events USING gin (title gin_trgm_ops)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_summary_trgm ON events USING gin (summary gin_trgm_ops)
        """)

        conn.commit()
        print("✅ PostgreSQL FTS 索引已同步")
    finally:
        conn.close()


def _fill_arxiv_url(event_title: str, current_url: str) -> str:
    """
    后处理纠正：如果 event.source_url 为空但标题含 arXiv 信息，
    则构造一个合理的 arXiv URL。
    支持从标题中提取 arXiv ID（如 "arXiv:2604.14223" 或 "arXiv abs/2604.14223"）。
    """
    if current_url:
        return current_url
    # 从标题中提取 arXiv ID
    match = re.search(r'arXiv[:\s]*(?:abs/)?(\d{4}\.\d{4,5})', event_title, re.IGNORECASE)
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"
    if 'arxiv' in event_title.lower():
        return "https://arxiv.org/"
    return current_url


def save_extraction_result(result) -> None:
    """保存抽取结果到 PostgreSQL"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()

        # 预防重复：建立 (name, type) → 已有ID 的映射
        cursor.execute("SELECT name, type, id FROM entities")
        name_type_to_id = {(row['name'], row['type']): row['id'] for row in cursor.fetchall()}

        id_mapping = {}

        for entity in result.entities:
            entity_type = entity.entity_type.value if hasattr(entity.entity_type, "value") else str(entity.entity_type)
            entity_dict = entity.model_dump()
            base_keys = {"id", "entity_type", "name", "aliases", "description", "created_at"}
            attributes = {k: v for k, v in entity_dict.items() if k not in base_keys and v is not None and v != []}

            all_aliases = {}
            cursor.execute("SELECT id, aliases_json FROM entities WHERE type = %s", (entity_type,))
            for row in cursor.fetchall():
                if row['aliases_json'] and row['aliases_json'] not in ("null", ""):
                    try:
                        all_aliases[row['id']] = json.loads(row['aliases_json'])
                    except json.JSONDecodeError:
                        all_aliases[row['id']] = []

            canonical_id = find_entity_by_alias(entity.name, entity_type, name_type_to_id, all_aliases)
            use_id = canonical_id if canonical_id else entity.id

            if canonical_id:
                cursor.execute("SELECT attributes_json, description FROM entities WHERE id = %s", (canonical_id,))
                row = cursor.fetchone()
                if row:
                    try:
                        existing_attrs = json.loads(row['attributes_json']) if row['attributes_json'] and row['attributes_json'] not in ("null", "") else {}
                    except json.JSONDecodeError:
                        existing_attrs = {}
                    existing_desc = row['description'] or ""
                    for k, v in attributes.items():
                        if k not in existing_attrs or not existing_attrs[k]:
                            existing_attrs[k] = v
                    if len(str(entity.description or "")) > len(existing_desc):
                        existing_desc = entity.description
                    attributes = existing_attrs
                    entity_desc = existing_desc
                else:
                    entity_desc = entity.description
            else:
                entity_desc = entity.description
                name_type_to_id[(entity.name, entity_type)] = use_id

            id_mapping[entity.id] = use_id

            cursor.execute("""
                INSERT INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    aliases_json = EXCLUDED.aliases_json,
                    description = EXCLUDED.description,
                    attributes_json = EXCLUDED.attributes_json
            """, (
                use_id, entity_type, entity.name,
                json.dumps(entity.aliases),
                entity_desc,
                _format_dt(entity.created_at),
                json.dumps(attributes, ensure_ascii=False)
            ))

        # events 去重
        cursor.execute("SELECT title, date FROM events")
        existing_event_keys = set((row['title'], row['date']) for row in cursor.fetchall())

        for event in result.events:
            event_key = (event.title, _format_dt(event.date))
            if event_key in existing_event_keys:
                continue
            canonical_ids = [id_mapping.get(eid, eid) for eid in event.involved_entity_ids]
            # ── 后处理纠正：arXiv URL 补全 ────────────────────────────
            filled_url = _fill_arxiv_url(event.title, event.source_url or "")
            cursor.execute("""
                INSERT INTO events (id, title, date, published_date, involved_entities_json,
                                    summary, source_url, created_at, risk_level, sentiment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                event.id, event.title, _format_dt(event.date),
                _format_dt(event.published_date),
                json.dumps(canonical_ids), event.summary, filled_url,
                _format_dt(event.created_at),
                getattr(event, "risk_level", None),
                getattr(event, "sentiment", None)
            ))

        # relationships
        for rel in result.relationships:
            src = id_mapping.get(rel.source_id, rel.source_id)
            tgt = id_mapping.get(rel.target_id, rel.target_id)
            rtype = rel.relation_type.value if hasattr(rel.relation_type, "value") else str(rel.relation_type)
            cursor.execute("""
                INSERT INTO relationships (source_id, target_id, relation_type, start_date, end_date, evidence)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, target_id, relation_type) DO NOTHING
            """, (
                src, tgt, rtype,
                _format_dt(rel.start_date),
                _format_dt(rel.end_date),
                getattr(rel, "evidence", None)
            ))

        conn.commit()
    finally:
        conn.close()


def query_all_entities(text: str = "") -> list:
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        if text:
            words = set(w.lower() for w in text.split() if len(w) >= 3)
            cursor.execute("SELECT * FROM entities")
            all_entities = cursor.fetchall()
            text_lower = text.lower()
            filtered = [dict(r) for r in all_entities if r["name"] and r["name"].lower() in text_lower]
            return filtered
        else:
            cursor.execute("SELECT * FROM entities")
            return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def query_entity_by_id(entity_id: str) -> Optional[dict]:
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE id = %s", (entity_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_recent_events(days: int = 7) -> list:
    from datetime import timedelta
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cutoff_date = _format_dt(datetime.now() - timedelta(days=days))
        cursor.execute(
            "SELECT * FROM events WHERE published_date >= %s ORDER BY published_date DESC",
            (cutoff_date,)
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def push_task(url: str):
    """Push URL to task queue, returns (task_id, is_new) or (None, False)"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM task_queue WHERE url = %s", (url,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO task_queue (url, status, created_at) VALUES (%s, 'pending', %s) RETURNING id",
                (url, _format_dt(datetime.now()))
            )
            conn.commit()
            task_id = cursor.fetchone()["id"]
            return task_id, True
        else:
            task_id = row["id"]
            if row["status"] in ("failed", "completed"):
                cursor.execute(
                    "UPDATE task_queue SET status = 'pending', error_message = NULL, created_at = %s WHERE url = %s",
                    (_format_dt(datetime.now()), url)
                )
                conn.commit()
                return task_id, True
            return task_id, False
    finally:
        conn.close()


def get_pending_task() -> dict | None:
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, url FROM task_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = cursor.fetchone()
        if not row:
            return None
        task_id = row["id"]
        url = row["url"]
        cursor.execute(
            "UPDATE task_queue SET status = 'processing' WHERE id = %s AND status = 'pending'",
            (task_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return {"id": task_id, "url": url}
    except Exception as e:
        print(f"get_pending_task error: {e}")
        return None
    finally:
        conn.close()


def update_task_status(task_id: int, status: str, error_msg: str = None, fail_count: int = None, next_retry_at: str = None) -> None:
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        if fail_count is not None:
            cursor.execute(
                "UPDATE task_queue SET status = %s, error_message = %s, fail_count = %s, next_retry_at = %s WHERE id = %s",
                (status, error_msg, fail_count, next_retry_at, task_id)
            )
        else:
            cursor.execute(
                "UPDATE task_queue SET status = %s, error_message = %s WHERE id = %s",
                (status, error_msg, task_id)
            )
        conn.commit()
    finally:
        conn.close()


def get_events_for_entity(entity_id: str) -> list:
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.* FROM events e
            WHERE e.involved_entities_json::text LIKE %s
            ORDER BY e.date DESC
        """, (f'%{entity_id}%',))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def rebuild_fts_tables() -> None:
    """全量重建 FTS 表"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DROP INDEX IF EXISTS idx_entities_name_trgm")
        cursor.execute("DROP INDEX IF EXISTS idx_entities_desc_trgm")
        cursor.execute("DROP INDEX IF EXISTS idx_events_title_trgm")
        cursor.execute("DROP INDEX IF EXISTS idx_events_summary_trgm")
        conn.commit()
        ensure_fts_tables()
        print("✅ PostgreSQL FTS 索引全量重建完成")
    finally:
        conn.close()


def get_smart_rag_context(query: str) -> str:
    """升级版 RAG 检索（PostgreSQL FTS）"""
    conn = _get_pg_conn()
    try:
        cursor = conn.cursor()

        # 实体模糊检索（pg_trgm）
        cursor.execute("""
            SELECT id, name, description FROM entities
            WHERE similarity(name, %s) > 0.1
               OR name ILIKE %s
               OR description ILIKE %s
            ORDER BY similarity(name, %s) DESC
            LIMIT 12
        """, (query, f"%{query}%", f"%{query}%", query))
        matched_entities = cursor.fetchall()
        matched_ids = [str(r["id"]) for r in matched_entities]

        context_parts = []
        if matched_entities:
            context_parts.append("【精准档案】关联实体：\n")
            for r in matched_entities:
                context_parts.append(f"  • {r['name']}: {r['description'] or ''}")

        # 关联事件
        if matched_ids:
            # Use a simpler approach: ILIKE with escaped % for each entity
            conditions = " OR ".join(["involved_entities_json::text ILIKE '%%' || %s || '%%'" for _ in matched_ids])
            cursor.execute(f"""
                SELECT e.id, e.title, e.date, e.summary, e.risk_level, e.sentiment
                FROM events e
                WHERE {conditions}
                ORDER BY e.date DESC
                LIMIT 30
            """, matched_ids)
            event_rows = cursor.fetchall()
            if event_rows:
                context_parts.append("\n【精准档案】关联事件：\n")
                for r in event_rows:
                    risk_tag = f" [{r.get('risk_level') or '?'}] " if r.get('risk_level') else "  "
                    context_parts.append(
                        f"  {str(r['date'])[:10]}{risk_tag}{r['title']}: {r['summary'] or ''}"
                    )

        # 兜底：FTS 事件检索
        cursor.execute("""
            SELECT title, date, summary FROM events
            WHERE title ILIKE %s OR summary ILIKE %s
            ORDER BY date DESC
            LIMIT 15
        """, (f"%{query}%", f"%{query}%"))
        fts_rows = cursor.fetchall()
        if fts_rows:
            context_parts.append("\n【语义相关】最新动态：\n")
            for r in fts_rows:
                context_parts.append(f"  {str(r['date'])[:10]} {r['title']}: {r['summary'] or ''}")

        if not context_parts:
            cursor.execute("SELECT title, date, summary FROM events ORDER BY date DESC LIMIT 20")
            fallback = cursor.fetchall()
            context_parts = ["【全局动态】\n"]
            for r in fallback:
                context_parts.append(f"  {str(r['date'])[:10]} {r['title']}: {r['summary'] or ''}")

        return "\n".join(context_parts)
    finally:
        conn.close()


# ── 兼容性别名 ───────────────────────────────────────────────────────────
ALIAS_MAPPINGS = {
    "openai": "OpenAI", "anthropic": "Anthropic", "google": "Google",
    "meta": "Meta", "microsoft": "Microsoft", "nvidia": "NVIDIA",
    "英伟达": "NVIDIA", "谷歌": "Google", "脸书": "Meta",
    "苹果": "Apple", "百度": "Baidu", "阿里巴巴": "Alibaba",
    "腾讯": "Tencent", "字节跳动": "ByteDance", "字节": "ByteDance",
    "gpt4": "GPT-4", "gpt-4": "GPT-4", "gpt4o": "GPT-4o",
    "chatgpt": "ChatGPT", "claude3": "Claude 3", "claude 3": "Claude 3",
    "llama2": "LLaMA 2", "llama 2": "LLaMA 2", "llama3": "LLaMA 3",
    "大模型": "LLM", "llm": "LLM", "大型语言模型": "LLM",
    "人工智能": "AI", "机器学习": "ML", "深度学习": "Deep Learning",
}


def normalize_for_match(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[\s\-_–—.,，、。]', '', text)
    return text


def find_entity_by_alias(name: str, entity_type: str, name_type_to_id: dict, all_aliases: dict) -> str:
    if (name, entity_type) in name_type_to_id:
        return name_type_to_id[(name, entity_type)]

    normalized = normalize_for_match(name)
    for alias, canonical in ALIAS_MAPPINGS.items():
        if normalize_for_match(alias) == normalized:
            if (canonical, entity_type) in name_type_to_id:
                return name_type_to_id[(canonical, entity_type)]

    for (existing_name, existing_type), existing_id in name_type_to_id.items():
        if existing_type != entity_type:
            continue
        if normalize_for_match(existing_name) == normalized:
            return existing_id
        if existing_id in all_aliases:
            for alias in all_aliases[existing_id]:
                if normalize_for_match(alias) == normalized:
                    return existing_id

    return None
