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
def _format_dt(dt):
    """Normalize datetime to ISO string with UTC timezone"""
    if dt is None:
        return None
    from datetime import timezone, datetime
    if isinstance(dt, str):
        s = dt.strip()
        try:
            if s.endswith('+00:00'):
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.fromisoformat(s.replace('+00:00', ''))
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return dt
    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()




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
            try:
                cursor.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise  # 非"列已存在"错误，继续抛出
        try:
            cursor.execute("ALTER TABLE entities ADD COLUMN attributes_json TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL, target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL, start_date TEXT, end_date TEXT,
                evidence TEXT,
                UNIQUE(source_id, target_id, relation_type)
            )
        """)
        try:
            cursor.execute("ALTER TABLE relationships ADD COLUMN evidence TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending', error_message TEXT, created_at TEXT NOT NULL
            )
        """)
        try:
            cursor.execute("ALTER TABLE task_queue ADD COLUMN error_message TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

        conn.commit()

        # 确保性能索引存在
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_events_entities ON events(involved_entities_json)",
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)",
            "CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status)",
            "CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_date)",
        ]:
            try:
                cursor.execute(sql)
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e).lower():
                    raise
        conn.commit()

        print(f"✅ 数据库底座就绪: {DB_PATH}")

        # 统一由 ensure_fts_tables() 处理 FTS5 初始化
        ensure_fts_tables()

    finally:
        conn.close()


# 预建跨语言别名映射（AI行业常见）
ALIAS_MAPPINGS = {
    # 公司别名
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "英伟达": "NVIDIA",
    "谷歌": "Google",
    "脸书": "Meta",
    "苹果": "Apple",
    "百度": "Baidu",
    "阿里巴巴": "Alibaba",
    "腾讯": "Tencent",
    "字节跳动": "ByteDance",
    "字节": "ByteDance",
    # 产品别名
    "gpt4": "GPT-4",
    "gpt-4": "GPT-4",
    "gpt4o": "GPT-4o",
    "chatgpt": "ChatGPT",
    "claude3": "Claude 3",
    "claude 3": "Claude 3",
    "claude2": "Claude 2",
    "claude 2": "Claude 2",
    "llama2": "LLaMA 2",
    "llama 2": "LLaMA 2",
    "llama3": "LLaMA 3",
    "llama 3": "LLaMA 3",
    # 技术别名
    "大模型": "LLM",
    "llm": "LLM",
    "大型语言模型": "LLM",
    "人工智能": "AI",
    "机器学习": "ML",
    "深度学习": "Deep Learning",
}

def normalize_for_match(text: str) -> str:
    """标准化文本用于匹配：转小写、移除空格和标点"""
    import re
    text = text.lower().strip()
    text = re.sub(r'[\s\-_–—.,，、。]', '', text)
    return text

def find_entity_by_alias(name: str, entity_type: str, name_type_to_id: dict, all_aliases: dict) -> str:
    """通过名称或别名查找已有实体的规范ID"""
    # 1. 直接检查 (name, type)
    if (name, entity_type) in name_type_to_id:
        return name_type_to_id[(name, entity_type)]

    # 2. 检查别名映射表
    normalized = normalize_for_match(name)
    for alias, canonical in ALIAS_MAPPINGS.items():
        if normalize_for_match(alias) == normalized:
            if (canonical, entity_type) in name_type_to_id:
                return name_type_to_id[(canonical, entity_type)]

    # 3. 检查 name_type_to_id 中所有实体的名称和别名列表
    # name_type_to_id: {(name, type): id}
    for (existing_name, existing_type), existing_id in name_type_to_id.items():
        if existing_type != entity_type:
            continue
        if normalize_for_match(existing_name) == normalized:
            return existing_id
        # 检查现有别名列表
        if existing_id in all_aliases:
            for alias in all_aliases[existing_id]:
                if normalize_for_match(alias) == normalized:
                    return existing_id

    return None

def save_extraction_result(result: ExtractionResult) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # ── 预防重复：建立 (name, type) → 已有ID 的映射 ─────────────────────
        # 新实体如果同名同类，直接复用已有ID，避免产生副本
        cursor.execute("SELECT name, type, id FROM entities")
        name_type_to_id = {(row[0], row[1]): row[2] for row in cursor.fetchall()}

        # 新 ID 映射：生成的 ID → 规范ID（可能是自己，也可能是已有ID）
        id_mapping = {}  # new_id → canonical_id

        for entity in result.entities:
            entity_type = entity.entity_type.value if hasattr(entity.entity_type, 'value') else str(entity.entity_type)
            entity_dict = entity.model_dump()
            base_keys = {'id', 'entity_type', 'name', 'aliases', 'description', 'created_at'}
            attributes = {k: v for k, v in entity_dict.items() if k not in base_keys and v is not None and v != []}

            # 关键：同名同类实体复用已有ID，从根源上防止重复
            # 增强版：也检查别名和跨语言映射
            all_aliases = {}  # 已有的别名映射 {id: [aliases]}
            for row in cursor.execute("SELECT id, aliases_json FROM entities WHERE type = ?", (entity_type,)):
                if row[1] and row[1] not in ('null', ''):
                    try:
                        all_aliases[row[0]] = json.loads(row[1])
                    except json.JSONDecodeError:
                        all_aliases[row[0]] = []

            canonical_id = find_entity_by_alias(entity.name, entity_type, name_type_to_id, all_aliases)
            use_id = canonical_id if canonical_id else entity.id

            if canonical_id:
                # 已有实体：补充缺失的属性字段（不覆盖已有非空字段）
                cursor.execute("SELECT attributes_json, description FROM entities WHERE id = ?", (canonical_id,))
                row = cursor.fetchone()
                if row:
                    try:
                        existing_attrs = json.loads(row[0]) if row[0] and row[0] not in ('null', '') else {}
                    except json.JSONDecodeError:
                        existing_attrs = {}
                    existing_desc = row[1] or ''
                    # 补充新属性
                    for k, v in attributes.items():
                        if k not in existing_attrs or not existing_attrs[k]:
                            existing_attrs[k] = v
                    # 描述取较长的
                    if len(str(entity.description or '')) > len(existing_desc):
                        existing_desc = entity.description
                    attributes = existing_attrs
                    entity_desc = existing_desc
                else:
                    entity_desc = entity.description
            else:
                entity_desc = entity.description
                # 记录新产生的 ID
                name_type_to_id[(entity.name, entity_type)] = use_id

            id_mapping[entity.id] = use_id

            cursor.execute("""
                INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (use_id, entity_type, entity.name, json.dumps(entity.aliases), entity_desc,
                  _format_dt(entity.created_at), json.dumps(attributes, ensure_ascii=False)))

        # ── 写入 events：把实体ID映射到规范ID ──────────────────────────────
        # 去重：同一标题+日期的事件跳过（防止同一URL重复处理产生重复事件）
        cursor.execute("SELECT title, date FROM events")
        existing_event_keys = set((row[0], row[1]) for row in cursor.fetchall())

        for event in result.events:
            event_key = (event.title, _format_dt(event.date))
            if event_key in existing_event_keys:
                continue
            canonical_ids = [id_mapping.get(eid, eid) for eid in event.involved_entity_ids]
            cursor.execute("""
                INSERT OR REPLACE INTO events (id, title, date, published_date, involved_entities_json, summary, source_url, created_at, risk_level, sentiment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event.id, event.title, _format_dt(event.date),
                  _format_dt(event.published_date),
                  json.dumps(canonical_ids), event.summary, event.source_url,
                  _format_dt(event.created_at),
                  getattr(event, 'risk_level', None), getattr(event, 'sentiment', None)))

        # ── 写入 relationships：把实体ID映射到规范ID ───────────────────────
        for rel in result.relationships:
            src = id_mapping.get(rel.source_id, rel.source_id)
            tgt = id_mapping.get(rel.target_id, rel.target_id)
            rtype = rel.relation_type.value if hasattr(rel.relation_type, 'value') else str(rel.relation_type)
            cursor.execute("""
                INSERT OR IGNORE INTO relationships (source_id, target_id, relation_type, start_date, end_date, evidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (src, tgt, rtype,
                  _format_dt(rel.start_date),
                  _format_dt(rel.end_date),
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
    finally:
        conn.close()

def query_entity_by_id(entity_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_recent_events(days: int = 7) -> list:
    from datetime import timedelta
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cutoff_date = _format_dt(datetime.now() - timedelta(days=days))
        cursor.execute("SELECT * FROM events WHERE published_date >= ? ORDER BY published_date DESC", (cutoff_date,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def push_task(url: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM task_queue WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO task_queue (url, status, created_at) VALUES (?, 'pending', ?)", (url, _format_dt(datetime.now())))
            conn.commit()
            return True
        else:
            if row[0] in ('failed', 'completed'):
                cursor.execute("UPDATE task_queue SET status = 'pending', error_message = NULL, created_at = ? WHERE url = ?", (_format_dt(datetime.now()), url))
                conn.commit()
                return True
            return False
    finally:
        conn.close()

def get_pending_task() -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # 两步原子操作：先查后改，兼容 SQLite 3.35 以前版本
        cursor.execute("""
            SELECT id, url FROM task_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None
        task_id, url = row['id'], row['url']
        cursor.execute(
            "UPDATE task_queue SET status = 'processing' WHERE id = ? AND status = 'pending'",
            (task_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            # 已被其他 worker 抢走，跳过
            return None
        return {"id": task_id, "url": url}
    except Exception as e:
        print(f"❌ get_pending_task 报错: {e}")
        return None
    finally:
        conn.close()

def update_task_status(task_id: int, status: str, error_msg: str = None) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE task_queue SET status = ?, error_message = ? WHERE id = ?", (status, error_msg, task_id))
        conn.commit()
    finally:
        conn.close()

def ensure_fts_tables() -> None:
    """
    初始化并维护 FTS5 虚拟表，用于全文检索（BM25 排序）。
    每次调用会增量同步新数据，不重复全量重建。
    统一由本函数处理 FTS5 相关操作，避免重复初始化。
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # ── 实体 FTS5 ─────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                entity_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
        conn.commit()

        # 同步：对比主表和 FTS 表，取差量更新
        cursor.execute("""
            INSERT INTO entities_fts(entity_id, content)
            SELECT id,
                   COALESCE(name, '') || ' ' ||
                   COALESCE(aliases_json, '') || ' ' ||
                   COALESCE(description, '') || ' ' ||
                   COALESCE(attributes_json, '')
            FROM entities e
            WHERE e.id NOT IN (SELECT entity_id FROM entities_fts)
        """)
        conn.commit()

        # ── 事件 FTS5 ─────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                event_id UNINDEXED,
                title,
                summary,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
        conn.commit()

        cursor.execute("""
            INSERT INTO events_fts(event_id, title, summary)
            SELECT id, COALESCE(title, ''), COALESCE(summary, '')
            FROM events e
            WHERE e.id NOT IN (SELECT event_id FROM events_fts)
        """)
        conn.commit()

        print("✅ FTS5 全文索引已同步")
    finally:
        conn.close()


def rebuild_fts_tables() -> None:
    """全量重建 FTS 表（数据不一致时调用）"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for sql in [
            "DROP TABLE IF EXISTS entities_fts",
            "DROP TABLE IF EXISTS events_fts",
        ]:
            cursor.execute(sql)
        conn.commit()
        ensure_fts_tables()
        print("✅ FTS5 全文索引全量重建完成")
    finally:
        conn.close()


def get_events_for_entity(entity_id: str) -> list:
    """查询某实体关联的所有事件（使用 json_each 而非 LIKE，全表扫描）"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.* FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ?
            ORDER BY e.date DESC
        """, (entity_id,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def _search_entities_fts(query: str, top_k: int = 10) -> list[tuple[str, float]]:
    """
    使用 FTS5 BM25 检索最相关的实体。
    返回 [(entity_id, bm25_score), ...]，分数越低越相关。
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        keywords = query.strip().split()
        if not keywords:
            return []
        fts_query = ' OR '.join(f'"{kw}"' for kw in keywords if kw)
        cursor.execute("""
            SELECT entity_id, bm25(entities_fts) AS score
            FROM entities_fts
            WHERE entities_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, (fts_query, top_k))
        return [(str(r['entity_id']), float(r['score'])) for r in cursor.fetchall()]
    except Exception as e:
        print(f"⚠️ FTS5 实体检索失败，退回全文扫描: {e}")
        return []
    finally:
        conn.close()


def _search_events_fts(query: str, top_k: int = 20) -> list[tuple[str, float]]:
    """
    使用 FTS5 BM25 检索最相关的最新事件。
    返回 [(event_id, bm25_score), ...]
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        keywords = query.strip().split()
        if not keywords:
            return []
        fts_query = ' OR '.join(f'"{kw}"' for kw in keywords if kw)
        cursor.execute("""
            SELECT event_id, bm25(events_fts) AS score
            FROM events_fts
            WHERE events_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, (fts_query, top_k))
        return [(str(r['event_id']), float(r['score'])) for r in cursor.fetchall()]
    except Exception as e:
        print(f"⚠️ FTS5 事件检索失败: {e}")
        return []
    finally:
        conn.close()


def get_smart_rag_context(query: str) -> str:
    """
    升级版 RAG 检索：
    1. FTS5 BM25 精准匹配实体（替代暴力子串匹配）
    2. json_each 精准关联事件（替代 LIKE 全表扫描）
    3. Neo4j 多跳拓扑扩展（1-hop → 2-hop）
    4. 双重兜底：FTS 事件检索 + 最新事件
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # ── Step 1：FTS5 BM25 实体检索（替代 name in query 暴力匹配）────────
        fts_entities = _search_entities_fts(query, top_k=12)
        if fts_entities:
            matched_ids = [eid for eid, _ in fts_entities]
        else:
            # 兜底：FTS 查不到则用宽松 LIKE
            cursor.execute("""
                SELECT id FROM entities
                WHERE LOWER(name) LIKE ? OR LOWER(description) LIKE ?
                LIMIT 12
            """, (f'%{query}%', f'%{query}%'))
            matched_ids = [str(r[0]) for r in cursor.fetchall()]

        # ── Step 2：关联事件（json_each 精准匹配，不再 LIKE 全表扫描）─────────
        context_parts = []
        if matched_ids:
            placeholders = ','.join('?' * len(matched_ids))
            # 找同时涉及多个匹配实体的「高相关事件」，优先展示
            cursor.execute(f"""
                SELECT e.id, e.title, e.date, e.summary, e.risk_level, e.sentiment,
                       COUNT(DISTINCT j.value) AS match_count
                FROM events e
                JOIN json_each(e.involved_entities_json) j
                WHERE j.value IN ({placeholders})
                GROUP BY e.id
                ORDER BY match_count DESC, e.date DESC
                LIMIT 30
            """, matched_ids)
            rows = cursor.fetchall()
            if rows:
                context_parts.append("【精准档案】关联事件：\n")
                for r in rows:
                    risk_tag = f" [{dict(r).get('risk_level') or '?'}] " if dict(r).get('risk_level') else "  "
                    context_parts.append(
                        f"  {dict(r)['date'][:10]}{risk_tag}{dict(r)['title']}: {dict(r)['summary']}"
                    )
            else:
                context_parts.append("【精准档案】该主题暂无事件记录。\n")

        # ── Step 3：FTS5 事件检索兜底（查询词匹配最新相关动态）──────────────
        fts_events = _search_events_fts(query, top_k=15)
        if fts_events:
            fts_event_ids = [eid for eid, _ in fts_events]
            placeholders = ','.join('?' * len(fts_event_ids))
            cursor.execute(f"""
                SELECT title, date, summary FROM events
                WHERE id IN ({placeholders})
                ORDER BY date DESC
                LIMIT 15
            """, fts_event_ids)
            fts_rows = cursor.fetchall()
            if fts_rows:
                context_parts.append("\n【语义相关】最新动态：\n")
                for r in fts_rows:
                    context_parts.append(f"  {r['date'][:10]} {dict(r)['title']}: {dict(r)['summary']}")

        # ── Step 4：Neo4j 多跳拓扑扩展（1-hop → 2-hop）──────────────────────
        if matched_ids:
            context_parts.append("\n【🕸️ 图谱拓扑】关系网络：\n")
            try:
                from neo_client import neo_db
                if neo_db.driver:
                    # 1-hop：直接邻居
                    cypher_1hop = """
                    MATCH (s:Entity)-[r]-(t:Entity)
                    WHERE s.id IN $anchor_ids
                    RETURN s.name AS source, type(r) AS rel, t.name AS target,
                           r.evidence AS evidence, 1 AS depth
                    LIMIT 40
                    """
                    records_1hop = neo_db.execute_query(cypher_1hop, {"anchor_ids": matched_ids})

                    # 2-hop：通过中间节点扩展（跨领域关系发现）
                    cypher_2hop = """
                    MATCH (s:Entity)-[r1]-(mid:Entity)-[r2]-(t:Entity)
                    WHERE s.id IN $anchor_ids AND t.id <> s.id
                    RETURN s.name AS source, type(r1) AS rel1, mid.name AS via,
                           type(r2) AS rel2, t.name AS target,
                           r1.evidence AS evidence, 2 AS depth
                    LIMIT 30
                    """
                    records_2hop = neo_db.execute_query(cypher_2hop, {"anchor_ids": matched_ids[:6]})

                    seen_1hop = set()
                    for rec in records_1hop:
                        key = (rec['source'], rec['rel'], rec['target'])
                        if key not in seen_1hop:
                            seen_1hop.add(key)
                            evid = f" (证据: {rec['evidence'][:60]})" if rec.get('evidence') else ""
                            context_parts.append(
                                f"  • {rec['source']} --[{rec['rel']}]--> {rec['target']}{evid}"
                            )

                    if records_2hop:
                        context_parts.append("  ── 2-hop 扩展 ──")
                        seen_2hop = set()
                        for rec in records_2hop:
                            key = (rec['source'], rec['rel1'], rec['via'], rec['rel2'], rec['target'])
                            if key not in seen_2hop:
                                seen_2hop.add(key)
                                evid = f" (证据: {rec['evidence'][:50]})" if rec.get('evidence') else ""
                                context_parts.append(
                                    f"  • {rec['source']} --[{rec['rel1']}]--> {rec['via']}"
                                    f" --[{rec['rel2']}]--> {rec['target']}{evid}"
                                )
                else:
                    context_parts.append("  (Neo4j 未连接)")
            except Exception as e:
                context_parts.append(f"  (图谱查询失败: {e})")

        if not context_parts:
            # 完全兜底：返回最近事件
            cursor.execute("SELECT title, date, summary FROM events ORDER BY date DESC LIMIT 20")
            fallback = cursor.fetchall()
            context_parts = ["【全局动态】\n"]
            for r in fallback:
                context_parts.append(f"  {r['date'][:10]} {dict(r)['title']}: {dict(r)['summary']}")

        return "\n".join(context_parts)
    finally:
        conn.close()
