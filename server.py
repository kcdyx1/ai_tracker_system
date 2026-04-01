#!/usr/bin/env python3
"""
AI Tracker System - FastAPI 服务端 (React 前后端分离版)
支持高并发入库、多模态解析与全量 REST API 供货
"""

import asyncio
import os
import shutil
import uuid
import json
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import os
from datetime import datetime
from fastapi import Request, HTTPException
# ... 其他 import
from database import (
    init_db, push_task, get_pending_task, update_task_status,
    save_extraction_result, get_connection, get_recent_events, query_all_entities,
    query_entity_by_id, get_events_for_entity
)
from worker import process_intel_task
from extractor import extract_with_validation
from ingestion import fetch_clean_markdown
from enricher import run_enrichment
from neo_client import neo_db
from rag import chat_with_graph

# ============================================================================
# 生命周期与 Worker 引擎
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("📦 初始化数据库...")
    init_db()
    
    # 自愈：重置僵尸任务
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE task_queue SET status = 'pending' WHERE status = 'processing'")
            reset_count = cursor.rowcount
            conn.commit()
            if reset_count > 0:
                print(f"🧹 自愈触发：已重置 {reset_count} 个僵尸任务")
        finally:
            conn.close()
    except Exception as e:
        print(f"⚠️ 僵尸任务重置失败: {e}")

    yield
    print("👋 应用关闭")

# ============================================================================
# App 实例化与 CORS 配置
# ============================================================================
app = FastAPI(title="AI Tracker System API", lifespan=lifespan)

# 允许 React 跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# 添加请求日志中间件
@app.middleware("http")
async def log_requests(request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    start_time = time.time()

    # 记录请求
    logger.info(f"请求: {request.method} {request.url.path} from {client_ip}")

    # 检查限流
    if not check_rate_limit(client_ip):
        logger.warning(f"限流触发: {client_ip}")
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})

    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"响应: {response.status_code} ({process_time:.3f}s)")
    return response

class IngestRequest(BaseModel):
    url: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: str
    history: list[ChatMessage] = []

# ============================================================================
# API 路由 (为 React 前端供货)
# ============================================================================
@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    from datetime import datetime
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AI Tracker System"
    }

@app.get("/api/stats")
async def get_dashboard_stats():
    """获取大盘统计数据"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM entities")
        stats["entity_count"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM events")
        stats["event_count"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM relationships")
        stats["relationship_count"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'company'")
        stats["company_count"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'product'")
        stats["product_count"] = cursor.fetchone()[0]
        return stats
    finally:
        conn.close()

@app.get("/api/tool/radar")
async def tool_radar_endpoint(query: str):
    """供 OpenClaw 直接调用的 REST API 接口"""
    # 引入底层的 RAG 检索函数
    from database import get_smart_rag_context
    try:
        # 执行图谱与二维表的混合检索
        context = get_smart_rag_context(query)
        return {
            "status": "success", 
            "data": f"【产业雷达底层检索返回的情报事实】\n\n{context}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/graph")
async def get_graph_data(entity_id: str = None):
    """从 Neo4j 获取图谱的节点(nodes)和连线(links)数据"""
    try:
        if entity_id:
            # 💡 核心升级：查指定节点的 1 跳甚至 2 跳关系网
            query = """
            MATCH (s:Entity)-[r]->(t:Entity)
            WHERE s.id = $entity_id OR t.id = $entity_id
            RETURN s.id AS source_id, s.name AS source_name, s.type AS source_type,
                   type(r) AS rel_type,
                   t.id AS target_id, t.name AS target_name, t.type AS target_type
            LIMIT 500
            """
            params = {"entity_id": entity_id}
        else:
            # 💡 核心升级 V2：真正的“内阁精英网” (Elite Core Network)
            # 战术逻辑：
            # 1. 先扫描全量数据库，找出“关系线最多、影响力最大”的前 100 名大佬。
            # 2. 将这 100 人圈进一个叫 elite_nodes 的高级 VIP 房间。
            # 3. 核心大招：【只画出这 100 人互相之间的连线】。把房间外无关紧要的杂鱼全部过滤掉！
            query = """
            MATCH (n:Entity)
            WITH n, COUNT { (n)--() } AS degree
            ORDER BY degree DESC
            LIMIT 100
            WITH collect(n) AS elite_nodes
            UNWIND elite_nodes AS s
            MATCH (s)-[r]-(t:Entity)
            WHERE t IN elite_nodes AND s.id < t.id
            RETURN s.id AS source_id, s.name AS source_name, s.type AS source_type,
                   type(r) AS rel_type,
                   t.id AS target_id, t.name AS target_name, t.type AS target_type
            """
            params = {}

        # 执行原生 Cypher 查询
        records = neo_db.execute_query(query, params)

        nodes_dict = {}
        links = []

        for row in records:
            s_id, t_id = row['source_id'], row['target_id']
            
            # 去重记录节点
            if s_id not in nodes_dict:
                nodes_dict[s_id] = {"id": s_id, "name": row['source_name'], "type": row['source_type']}
            if t_id not in nodes_dict:
                nodes_dict[t_id] = {"id": t_id, "name": row['target_name'], "type": row['target_type']}
                
            # 记录连线
            links.append({
                "source": s_id,
                "target": t_id,
                "label": row['rel_type']
            })

        return {"nodes": list(nodes_dict.values()), "links": links}

    except Exception as e:
        print(f"❌ Neo4j 图谱 API 崩溃: {e}")
        return {"nodes": [], "links": []}

@app.get("/api/events")
async def get_events(limit: int = 30):
    """获取最新事件流"""
    return get_recent_events(days=30)[:limit]

@app.get("/api/entities")
async def get_entities():
    """获取所有实体档案"""
    return query_all_entities()

@app.get("/api/tasks")
async def get_tasks():
    """获取引擎监控任务队列"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, status, error_message, created_at FROM task_queue ORDER BY id DESC LIMIT 20")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

@app.get("/api/entity/{entity_id}")
async def get_entity_details(entity_id: str):
    """精准调取单体档案及关联情报"""
    try:
        entity = query_entity_by_id(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体档案不存在")

        # 捞取与该实体相关的最新 10 条事件
        events = get_events_for_entity(entity_id)
        return {"entity": entity, "events": events[:10]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/entity/{entity_id}/competitors")
async def get_entity_competitors(entity_id: str):
    """获取实体的竞品列表（通过COMPETES_WITH关系）"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 查询竞争对手
        cursor.execute("""
            SELECT e.id, e.name, e.type, e.description
            FROM relationships r
            JOIN entities e ON (
                (r.source_id = ? AND r.target_id = e.id) OR
                (r.target_id = ? AND r.source_id = e.id)
            )
            WHERE r.relation_type = 'COMPETES_WITH'
        """, (entity_id, entity_id))
        competitors = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return {"entity_id": entity_id, "competitors": competitors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/entity/{entity_id}/timeline")
async def get_entity_timeline(entity_id: str, limit: int = 20):
    """获取实体的时序事件流"""
    try:
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        # 获取实体信息
        entity = query_entity_by_id(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")

        # 获取该实体相关的事件，按时间排序
        cursor.execute("""
            SELECT e.id, e.title, e.date, e.summary, e.risk_level, e.sentiment
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ?
            ORDER BY e.date DESC
            LIMIT ?
        """, (entity_id, limit))
        events = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return {"entity": entity, "timeline": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trending")
async def get_trending_entities(limit: int = 10):
    """
    获取本周热点分析报告

    返回：
    - entities: 热点实体排行
    - products: 新兴产品（近30天首次出现的产品）
    - tech_trends: 技术热点
    - companies: 公司活跃度排行
    - risk_alerts: 高风险事件摘要
    """
    try:
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()

        result = {"period_days": 7}

        # 1. 热点实体排行
        cursor.execute("""
            SELECT e.id, e.name, e.type,
                   COUNT(*) as event_count
            FROM events evt
            JOIN json_each(evt.involved_entities_json) j
            JOIN entities e ON j.value = e.id
            WHERE evt.date >= ?
            GROUP BY e.id
            ORDER BY event_count DESC
            LIMIT ?
        """, (week_ago, limit))

        result["entities"] = [
            {"id": row[0], "name": row[1], "type": row[2], "event_count": row[3]}
            for row in cursor.fetchall()
        ]

        # 2. 新兴产品（近30天首次出现的产品）
        cursor.execute("""
            SELECT e.id, e.name, e.description
            FROM entities e
            WHERE e.type = 'product'
              AND e.created_at >= ?
            ORDER BY e.created_at DESC
            LIMIT ?
        """, (month_ago, limit))

        result["products"] = [
            {"id": row[0], "name": row[1], "description": row[2] or ""}
            for row in cursor.fetchall()
        ]

        # 3. 技术热点（最常见的tech_concept类型实体）
        cursor.execute("""
            SELECT e.id, e.name,
                   COUNT(*) as mention_count
            FROM events evt
            JOIN json_each(evt.involved_entities_json) j
            JOIN entities e ON j.value = e.id
            WHERE evt.date >= ? AND e.type = 'tech_concept'
            GROUP BY e.id
            ORDER BY mention_count DESC
            LIMIT ?
        """, (week_ago, limit))

        result["tech_trends"] = [
            {"id": row[0], "name": row[1], "mention_count": row[2]}
            for row in cursor.fetchall()
        ]

        # 4. 公司活跃度（事件最多的公司）
        cursor.execute("""
            SELECT e.id, e.name,
                   COUNT(*) as event_count
            FROM events evt
            JOIN json_each(evt.involved_entities_json) j
            JOIN entities e ON j.value = e.id
            WHERE evt.date >= ? AND e.type = 'company'
            GROUP BY e.id
            ORDER BY event_count DESC
            LIMIT ?
        """, (week_ago, limit))

        result["companies"] = [
            {"id": row[0], "name": row[1], "event_count": row[2]}
            for row in cursor.fetchall()
        ]

        # 5. 高风险事件（risk_level = 高危/中风险）
        cursor.execute("""
            SELECT e.id, e.name,
                   evt.title, evt.date, evt.risk_level
            FROM events evt
            JOIN json_each(evt.involved_entities_json) j
            JOIN entities e ON j.value = e.id
            WHERE evt.date >= ?
              AND evt.risk_level IN ('高危', '中风险')
            ORDER BY evt.date DESC
            LIMIT ?
        """, (week_ago, 5))

        result["risk_alerts"] = [
            {
                "entity": {"id": row[0], "name": row[1]},
                "event_title": row[2],
                "date": row[3],
                "risk_level": row[4]
            }
            for row in cursor.fetchall()
        ]

        conn.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/entity/{entity_id}/conflicts")
async def detect_entity_conflicts(entity_id: str):
    """
    检测实体的知识冲突

    检查同一实体在不同事件中是否存在矛盾信息：
    - 同一关系的矛盾描述（如"投资"vs"不投资"）
    - 日期/数字的矛盾
    - 情感极性冲突（利好vs利空）
    """
    try:
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        # 获取实体信息
        entity = query_entity_by_id(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")

        # 获取该实体相关的所有关系
        cursor.execute("""
            SELECT r.id, r.relation_type, r.source_id, r.target_id,
                   r.evidence, r.start_date, r.end_date,
                   e1.name as source_name, e2.name as target_name
            FROM relationships r
            JOIN entities e1 ON r.source_id = e1.id
            JOIN entities e2 ON r.target_id = e1.id
            WHERE r.source_id = ? OR r.target_id = ?
        """, (entity_id, entity_id))

        relationships = []
        for row in cursor.fetchall():
            relationships.append({
                "id": row[0],
                "relation_type": row[1],
                "source_id": row[2],
                "target_id": row[3],
                "evidence": row[4],
                "start_date": row[5],
                "end_date": row[6],
                "source_name": row[7],
                "target_name": row[8]
            })

        # 获取该实体相关的事件及其情感极性
        cursor.execute("""
            SELECT e.id, e.title, e.date, e.sentiment, e.risk_level,
                   e.involved_entities_json
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ?
            ORDER BY e.date DESC
            LIMIT 50
        """, (entity_id,))

        events = []
        sentiments = []
        for row in cursor.fetchall():
            sentiments.append(row[4])  # sentiment
            events.append({
                "id": row[0],
                "title": row[1],
                "date": row[2],
                "sentiment": row[3],
                "risk_level": row[4]
            })

        # 检测情感冲突
        sentiment_conflicts = []
        if sentiments:
            positive = sentiments.count("利好")
            negative = sentiments.count("利空")
            if positive > 0 and negative > 0:
                sentiment_conflicts.append({
                    "type": "sentiment_conflict",
                    "positive_count": positive,
                    "negative_count": negative,
                    "description": f"该实体同时存在 {positive} 条利好和 {negative} 条利空事件"
                })

        # 检测关系冲突（同一实体对有多个矛盾关系）
        relation_map = {}
        for rel in relationships:
            key = (rel["source_id"], rel["target_id"])
            if key not in relation_map:
                relation_map[key] = []
            relation_map[key].append(rel)

        relation_conflicts = []
        for key, rels in relation_map.items():
            rel_types = set(r["relation_type"] for r in rels)
            # 检测矛盾关系对
            contradictory_pairs = [
                ("INVESTED", "COMPETES_WITH"),
                ("PARTNERS", "COMPETES_WITH"),
                ("ACQUIRED", "FOUNDED"),
            ]
            for pair in contradictory_pairs:
                if pair[0] in rel_types and pair[1] in rel_types:
                    relation_conflicts.append({
                        "type": "relation_conflict",
                        "entities": key,
                        "conflicting_types": list(rel_types),
                        "description": f"同一实体对同时存在 {pair[0]} 和 {pair[1]} 关系"
                    })

        conn.close()

        return {
            "entity": entity,
            "sentiment_conflicts": sentiment_conflicts,
            "relation_conflicts": relation_conflicts,
            "total_events": len(events),
            "total_relationships": len(relationships)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/entity/{entity_id}/insights")
async def get_entity_insights(entity_id: str):
    """
    获取实体的深度洞察摘要

    综合分析实体的：
    - 整体情感倾向
    - 关系网络密度
    - 活跃度趋势
    - 关键事件时间线
    """
    try:
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        entity = query_entity_by_id(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")

        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()

        # 近7天事件数
        cursor.execute("""
            SELECT COUNT(*)
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ? AND e.date >= ?
        """, (entity_id, week_ago))
        recent_events = cursor.fetchone()[0]

        # 近30天事件数
        cursor.execute("""
            SELECT COUNT(*)
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ? AND e.date >= ?
        """, (entity_id, month_ago))
        monthly_events = cursor.fetchone()[0]

        # 关系总数
        cursor.execute("""
            SELECT COUNT(*)
            FROM relationships
            WHERE source_id = ? OR target_id = ?
        """, (entity_id, entity_id))
        total_relations = cursor.fetchone()[0]

        # 情感统计
        cursor.execute("""
            SELECT sentiment, COUNT(*)
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ? AND e.sentiment IS NOT NULL
            GROUP BY sentiment
        """, (entity_id,))
        sentiment_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # 高风险事件
        cursor.execute("""
            SELECT e.title, e.date, e.risk_level
            FROM events e
            JOIN json_each(e.involved_entities_json) j
            WHERE j.value = ? AND e.risk_level = '高危'
            ORDER BY e.date DESC
            LIMIT 3
        """, (entity_id,))
        high_risk_events = [{"title": row[0], "date": row[1]} for row in cursor.fetchall()]

        conn.close()

        # 计算活跃度趋势
        activity_trend = "stable"
        if recent_events > monthly_events / 4:
            activity_trend = "rising"
        elif recent_events < monthly_events / 10:
            activity_trend = "declining"

        # 计算整体情感
        overall_sentiment = "neutral"
        positive = sentiment_stats.get("利好", 0)
        negative = sentiment_stats.get("利空", 0)
        if positive > negative * 2:
            overall_sentiment = "positive"
        elif negative > positive * 2:
            overall_sentiment = "negative"

        return {
            "entity": entity,
            "activity": {
                "recent_events_7d": recent_events,
                "monthly_events_30d": monthly_events,
                "trend": activity_trend
            },
            "relationships": {
                "total": total_relations
            },
            "sentiment": {
                "overall": overall_sentiment,
                "positive": positive,
                "negative": negative,
                "neutral": sentiment_stats.get("中性", 0)
            },
            "high_risk_events": high_risk_events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/task_stats")
async def get_task_stats():
    """获取任务队列的全局统计"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for status in status_counts.keys():
            cursor.execute("SELECT COUNT(*) FROM task_queue WHERE status = ?", (status,))
            status_counts[status] = cursor.fetchone()[0]
        return status_counts
    finally:
        conn.close()

from datetime import datetime

@app.post("/api/ingest")
async def ingest_url(request: Request):
    data = await request.json()
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    # 使用 push_task 函数智能处理重复URL（参考 database.py 的逻辑）
    success = push_task(url)
    if not success:
        # URL 已存在且任务正在处理中，返回成功避免阻塞
        return {"status": "skipped", "message": "任务已在队列中，跳过重复提交"}

    # 获取刚插入的任务ID
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM task_queue WHERE url = ?", (url,))
        row = cursor.fetchone()
        task_id = row['id'] if row else None
    finally:
        conn.close()

    if not task_id:
        raise HTTPException(status_code=500, detail="无法获取任务ID")

    # 2. ⚡️ 核心质变：将任务打入 Redis 队列，让 Celery 异步接管！
    # .delay() 是 Celery 的魔法方法，它会瞬间把参数打包发给 Redis，然后立刻返回
    process_intel_task.delay(task_id, url)
    
    # 3. FastAPI 秒回前端，前端再也不会转圈卡顿了
    return {"status": "success", "message": "目标已成功发射至 Redis 高并发队列"}

UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        # 1. 保存实体文件
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        save_path = UPLOAD_DIR / safe_name
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_url = f"file://{save_path.absolute()}"
        
        # 2. 极速写入 SQLite 占位获取 ID
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_queue (url, status, created_at) 
            VALUES (?, 'pending', ?)
        """, (file_url, datetime.now().isoformat()))
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # 3. ⚡️ 将文件解析任务打入 Redis 队列
        process_intel_task.delay(task_id, file_url)
        
        return {"status": "queued", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/enrich/{entity_id}")
async def force_enrich_entity(entity_id: str):
    try:
        result = await asyncio.to_thread(run_enrichment, entity_id)
        if result["status"] == "success": return result
        raise HTTPException(status_code=400, detail=result["message"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel

# 定义前端传过来的修改数据格式
# 1. 在接收模型里加上 type 字段
class EntityOverride(BaseModel):
    type: str = None  # 👈 新增这一行
    description: str = None
    attributes: dict = None

@app.put("/api/entity/{entity_id}")
async def override_entity(entity_id: str, data: EntityOverride):
    """L5 级最高指令：人工强行修正档案"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 提取原档案，这次把 type 也查出来
        cursor.execute("SELECT type, description, attributes_json FROM entities WHERE id = ?", (entity_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="档案不存在")
            
        # 接收新数据或保留旧数据（同时检查 None 和空字符串）
        new_type = data.type if (data.type is not None and data.type != '') else row['type']
        new_desc = data.description if data.description is not None else row['description']
        
        current_attrs = json.loads(row['attributes_json']) if row['attributes_json'] and row['attributes_json'] != 'null' else {}
        if data.attributes is not None:
            current_attrs.update(data.attributes)
        new_attrs_json = json.dumps(current_attrs, ensure_ascii=False)
        
        # 更新 SQLite，加入 type 字段
        cursor.execute("UPDATE entities SET type = ?, description = ?, attributes_json = ? WHERE id = ?", 
                       (new_type, new_desc, new_attrs_json, entity_id))
        conn.commit()
        conn.close()

        # 更新 Neo4j 图谱 (更新 type 属性)
        from neo_client import neo_db
        neo_query = """
        MATCH (e:Entity {id: $eid})
        SET e.type = $type, e.description = $desc, e.attributes_json = $attrs
        RETURN e
        """
        neo_db.execute_query(neo_query, {"eid": entity_id, "type": new_type, "desc": new_desc, "attrs": new_attrs_json})

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """L3 战略参谋部对话接口"""
    try:
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in request.history]
        response_text = await asyncio.to_thread(chat_with_graph, request.query, history_dicts)
        return {"response": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.responses import StreamingResponse
import csv
import io

@app.get("/api/export")
async def export_data(format: str = "json", entity_type: str = None, days: int = 30):
    """
    导出数据为 JSON 或 CSV 格式

    参数:
    - format: json 或 csv
    - entity_type: 过滤实体类型 (company, product, person, tech_concept)
    - days: 只导出近N天的事件 (默认30天)
    """
    try:
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        time_threshold = (datetime.now() - timedelta(days=days)).isoformat()

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow(["id", "type", "name", "description", "created_at"])

            if entity_type:
                cursor.execute("SELECT id, type, name, description, created_at FROM entities WHERE type = ?", (entity_type,))
            else:
                cursor.execute("SELECT id, type, name, description, created_at FROM entities")

            for row in cursor.fetchall():
                writer.writerow([row[0], row[1], row[2], row[3] or "", row[4]])

            writer.writerow([])
            writer.writerow(["source_id", "target_id", "relation_type", "evidence"])
            cursor.execute("SELECT source_id, target_id, relation_type, evidence FROM relationships")
            for row in cursor.fetchall():
                writer.writerow([row[0], row[1], row[2], row[3] or ""])

            conn.close()
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=ai_tracker_export_{datetime.now().strftime('%Y%m%d')}.csv"}
            )
        else:
            result = {"export_time": datetime.now().isoformat(), "entities": [], "relationships": [], "events": []}

            if entity_type:
                cursor.execute("SELECT id, type, name, description, created_at, aliases_json, attributes_json FROM entities WHERE type = ?", (entity_type,))
            else:
                cursor.execute("SELECT id, type, name, description, created_at, aliases_json, attributes_json FROM entities")

            for row in cursor.fetchall():
                result["entities"].append({
                    "id": row[0], "type": row[1], "name": row[2], "description": row[3],
                    "created_at": row[4],
                    "aliases": json.loads(row[5]) if row[5] and row[5] not in ('null', '') else [],
                    "attributes": json.loads(row[6]) if row[6] and row[6] not in ('null', '') else {}
                })

            cursor.execute("SELECT source_id, target_id, relation_type, evidence FROM relationships")
            for row in cursor.fetchall():
                result["relationships"].append({"source_id": row[0], "target_id": row[1], "relation_type": row[2], "evidence": row[3]})

            cursor.execute("SELECT id, title, date, published_date, summary, source_url, risk_level, sentiment FROM events WHERE date >= ?", (time_threshold,))
            for row in cursor.fetchall():
                result["events"].append({"id": row[0], "title": row[1], "date": row[2], "published_date": row[3], "summary": row[4], "source_url": row[5], "risk_level": row[6], "sentiment": row[7]})

            conn.close()
            return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import time

# 配置日志持久化
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"server_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 简易API限流（每个IP每分钟最多100次请求）
rate_limit_store = defaultdict(list)

def check_rate_limit(client_ip: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
    """检查IP是否超过限流阈值"""
    now = datetime.now()
    # 清理过期记录
    rate_limit_store[client_ip] = [
        t for t in rate_limit_store[client_ip]
        if now - t < timedelta(seconds=window_seconds)
    ]
    # 检查是否超限
    if len(rate_limit_store[client_ip]) >= max_requests:
        return False
    # 记录本次请求
    rate_limit_store[client_ip].append(now)
    return True



# ============================================================================
# 部署挂载：让 FastAPI 接管 React 编译后的前端页面
# ============================================================================
frontend_dist_path = Path(__file__).parent / "frontend" / "dist"

if frontend_dist_path.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist_path / "assets"), name="assets")
    
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        if catchall.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        index_path = frontend_dist_path / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"error": "Frontend build not found."}
else:
    print("⚠️ 警告: 未找到前端 dist 目录，请确在 frontend 目录下执行了 npm run build")



if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)