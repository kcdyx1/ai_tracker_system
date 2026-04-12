#!/usr/bin/env python3
"""
AI Tracker System - FastAPI 服务端 (React 前后端分离版 + PostgreSQL 重装版)
支持高并发入库、多模态解析与全量 REST API 供货
"""

import asyncio
import os
import shutil
import uuid
import json
import time
import logging
from pathlib import Path
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import (
    init_db, push_task, _format_dt, get_pending_task, update_task_status,
    save_extraction_result, get_connection, get_recent_events, query_all_entities,
    query_entity_by_id, get_events_for_entity
)
from worker import process_intel_task
from enricher import run_enrichment
from neo_client import neo_db
from rag import chat_with_graph

# ============================================================================
# 日志与限流配置
# ============================================================================
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

rate_limit_store = defaultdict(list)

def check_rate_limit(client_ip: str, max_requests: int = 500, window_seconds: int = 60) -> bool:
    """检查IP是否超过限流阈值 (放宽给前端大屏轮询用)"""
    now = datetime.now()
    rate_limit_store[client_ip] = [
        t for t in rate_limit_store[client_ip]
        if now - t < timedelta(seconds=window_seconds)
    ]
    if len(rate_limit_store[client_ip]) >= max_requests:
        return False
    rate_limit_store[client_ip].append(now)
    return True

# ============================================================================
# 生命周期与应用实例化
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("📦 初始化 PostgreSQL 数据库连接...")
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

app = FastAPI(title="AI Tracker System API (PG Edition)", lifespan=lifespan)

try:
    from sys_ops_endpoints import register_sys_ops_endpoints
    register_sys_ops_endpoints(app)
except ImportError:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    # 静态资源不限流，API限流
    if not request.url.path.startswith("/assets") and not check_rate_limit(client_ip):
        logger.warning(f"限流触发: {client_ip}")
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    if request.url.path.startswith("/api/"):
        logger.info(f"响应: {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
    return response

# ============================================================================
# Pydantic 数据模型
# ============================================================================
class IngestRequest(BaseModel):
    url: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: str
    history: list[ChatMessage] = []

class EntityOverride(BaseModel):
    type: str = None
    description: str = None
    attributes: dict = None

# ============================================================================
# 核心 API 路由 (已完美适配 PostgreSQL 的 %s 语法)
# ============================================================================

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": _format_dt(datetime.now(timezone.utc)), "service": "AI Tracker"}

@app.get("/api/stats")
async def get_dashboard_stats():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM entities")
        row = cursor.fetchone()
        stats["entity_count"] = row[0] if isinstance(row, tuple) else row.get("count", 0)
        
        cursor.execute("SELECT COUNT(*) FROM events")
        row = cursor.fetchone()
        stats["event_count"] = row[0] if isinstance(row, tuple) else row.get("count", 0)
        
        cursor.execute("SELECT COUNT(*) FROM relationships")
        row = cursor.fetchone()
        stats["relationship_count"] = row[0] if isinstance(row, tuple) else row.get("count", 0)
        
        cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'company'")
        row = cursor.fetchone()
        stats["company_count"] = row[0] if isinstance(row, tuple) else row.get("count", 0)
        
        cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'product'")
        row = cursor.fetchone()
        stats["product_count"] = row[0] if isinstance(row, tuple) else row.get("count", 0)
        return stats
    finally:
        conn.close()

@app.get("/api/task_stats")
async def get_task_stats():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for status in status_counts.keys():
            cursor.execute("SELECT COUNT(*) AS count FROM task_queue WHERE status = %s", (status,))
            row = cursor.fetchone()
            # 兼容 tuple 和 dict 返回结果
            status_counts[status] = row["count"] if isinstance(row, dict) else row[0]
        return status_counts
    finally:
        conn.close()

@app.get("/api/graph")
async def get_graph_data(
    entity_id: str = None,
    depth: int = Query(1, ge=1, le=2),
    rel_type: str = Query(None)
):
    """Graph API: entity_id=root, depth=1=direct/2=2nd-degree, rel_type=filter"""
    from database import get_connection

    def get_pg_weight(source_id, target_id, rel):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT weight FROM relationships WHERE source_id=%s AND target_id=%s AND relation_type=%s LIMIT 1", (source_id, target_id, rel))
            row = cur.fetchone()
            conn.close()
            return row["weight"] if row else 1.0
        except Exception:
            return 1.0

    try:
        params = {}
        if entity_id:
            if depth >= 2:
                if rel_type:
                    query = "MATCH (s:Entity)-[r1]->(m:Entity)-[r2]->(t:Entity) WHERE s.id=$entity_id AND type(r1)=$rel_type AND type(r2)=$rel_type RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(r1) AS rel, m.id AS tid, m.name AS tname, m.type AS ttype, t.id AS t2id, t.name AS t2name, t.type AS t2type LIMIT 800"
                    params = {"entity_id": entity_id, "rel_type": rel_type}
                else:
                    query = "MATCH (s:Entity)-[r1]->(m:Entity)-[r2]->(t:Entity) WHERE s.id=$entity_id RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(r1) AS rel, m.id AS tid, m.name AS tname, m.type AS ttype, t.id AS t2id, t.name AS t2name, t.type AS t2type LIMIT 800"
                    params = {"entity_id": entity_id}
            else:
                if rel_type:
                    query = "MATCH (s:Entity)-[r]->(t:Entity) WHERE (s.id=$entity_id OR t.id=$entity_id) AND type(r)=$rel_type RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(r) AS rel, t.id AS tid, t.name AS tname, t.type AS ttype LIMIT 500"
                    params = {"entity_id": entity_id, "rel_type": rel_type}
                else:
                    query = "MATCH (s:Entity)-[r]->(t:Entity) WHERE s.id=$entity_id OR t.id=$entity_id RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(r) AS rel, t.id AS tid, t.name AS tname, t.type AS ttype LIMIT 500"
                    params = {"entity_id": entity_id}
        else:
            if rel_type:
                query = "MATCH (s:Entity)-[r]->() WHERE type(r)=$rel_type WITH s,count(r) AS degree ORDER BY degree DESC LIMIT 30 MATCH (s)-[r]->(t:Entity) RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(r) AS rel, t.id AS tid, t.name AS tname, t.type AS ttype LIMIT 400"
                params = {"rel_type": rel_type}
            else:
                query = "MATCH (s:Entity)-[r]->() WITH s,count(r) AS degree ORDER BY degree DESC LIMIT 40 MATCH (s)-[r]->(t:Entity) WITH s,collect({r:r,t:t})[0..8] AS rels UNWIND rels AS rel RETURN s.id AS sid, s.name AS sname, s.type AS stype, type(rel.r) AS rel, rel.t.id AS tid, rel.t.name AS tname, rel.t.type AS ttype"
                params = {}

        records = neo_db.execute_query(query, params)
        nodes, links = {}, []

        for row in records:
            sid, tid = row["sid"], row["tid"]
            if sid not in nodes:
                nodes[sid] = {"id": sid, "name": row["sname"], "type": row["stype"]}
            if tid not in nodes:
                nodes[tid] = {"id": tid, "name": row["tname"], "type": row["ttype"]}
            rel = row["rel"]
            w = get_pg_weight(sid, tid, rel)
            links.append({"source": sid, "target": tid, "label": rel, "weight": w})
            if depth >= 2 and "t2id" in row and row["t2id"]:
                t2id = row["t2id"]
                if t2id not in nodes:
                    nodes[t2id] = {"id": t2id, "name": row["t2name"], "type": row["t2type"]}
                w2 = get_pg_weight(tid, t2id, rel)
                links.append({"source": tid, "target": t2id, "label": rel, "weight": w2})

        return {"nodes": list(nodes.values()), "links": links}
    except Exception as e:
        logger.error("Neo4j graph API error: " + str(e))
        return {"nodes": [], "links": []}


@app.get("/api/events")
async def get_events(limit: int = 30):
    return get_recent_events(days=30)[:limit]

@app.get("/api/entities")
async def get_entities():
    return query_all_entities()

@app.get("/api/tasks")
async def get_tasks():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, status, error_message, created_at FROM task_queue ORDER BY id DESC LIMIT 20")
        return [dict(row) if isinstance(row, dict) else row for row in cursor.fetchall()]
    finally:
        conn.close()

@app.get("/api/entity/{entity_id}")
async def get_entity_details(entity_id: str):
    try:
        entity = query_entity_by_id(entity_id)
        if not entity:
            try:
                rows = neo_db.execute_query(
                    "MATCH (e:Entity {id: $entity_id}) RETURN e.id AS id, e.name AS name, labels(e)[0] AS type, e.description AS description",
                    {"entity_id": entity_id}
                )
                if rows and rows[0]:
                    r = rows[0]
                    entity = {"id": r["id"], "name": r["name"], "type": r.get("type", "unknown"), "description": r.get("description") or "", "aliases_json": "[]", "created_at": "", "attributes_json": None, "enriched_at": None}
            except Exception as neo_err:
                logger.warning(f"Neo4j 兜底查询失败: {neo_err}")

        if not entity:
            raise HTTPException(status_code=404, detail="实体档案不存在")

        from datetime import datetime, timezone, timedelta
        needs_enrich = False
        enriched_at = entity.get("enriched_at")
        if not enriched_at or enriched_at == "null" or enriched_at is None:
            asyncio.create_task(asyncio.to_thread(run_enrichment, entity_id))
            needs_enrich = True
        else:
            try:
                last_enrich = datetime.fromisoformat(enriched_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_enrich) > timedelta(days=7):
                    asyncio.create_task(asyncio.to_thread(run_enrichment, entity_id))
                    needs_enrich = True
            except (ValueError, TypeError):
                asyncio.create_task(asyncio.to_thread(run_enrichment, entity_id))
                needs_enrich = True

        # Related papers: search by entity name in papers table
        related_papers = []
        try:
            entity_name = entity.get("name", "")
            if entity_name:
                conn = get_connection()
                cur = conn.cursor()
                # Simple full-text search using ILIKE on title/abstract
                pattern = r"%{}%".format(entity_name.replace("%", "%%"))
                cur.execute("""
                    SELECT id, title, abstract, authors, published_date, citation_count, source_url
                    FROM papers
                    WHERE title ILIKE %s OR abstract ILIKE %s
                    ORDER BY published_date DESC
                    LIMIT 5
                """, (pattern, pattern))
                for row in cur.fetchall():
                    related_papers.append({
                        "id": row["id"],
                        "title": row["title"],
                        "abstract": (row["abstract"] or "")[:200],
                        "authors": row["authors"],
                        "published_date": str(row["published_date"]) if row["published_date"] else None,
                        "citation_count": row["citation_count"],
                        "source_url": row["source_url"],
                    })
                conn.close()
        except Exception as e:
            logger.warning("Failed to fetch related papers: " + str(e))

        events = get_events_for_entity(entity_id)
        return {"entity": entity, "events": events[:10], "needs_enrich": needs_enrich, "related_papers": related_papers}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ingest")
async def ingest_url(request: Request):
    data = await request.json()
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    task_id, is_new = push_task(url)
    if not is_new:
        return {"status": "skipped", "message": "任务已在队列中，跳过重复提交"}

    process_intel_task.delay(task_id, url)
    return {"status": "success", "message": "目标已成功发射至 Redis 高并发队列"}

UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        save_path = UPLOAD_DIR / safe_name
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_url = f"file://{save_path.absolute()}"
        
        conn = get_connection()
        cursor = conn.cursor()
        # 💡 Postgres 关键修复：插入并返回自增 ID
        cursor.execute("""
            INSERT INTO task_queue (url, status, created_at) 
            VALUES (%s, 'pending', %s) RETURNING id
        """, (file_url, _format_dt(datetime.now(timezone.utc))))
        
        row = cursor.fetchone()
        task_id = row['id'] if isinstance(row, dict) else row[0]
        
        conn.commit()
        conn.close()

        process_intel_task.delay(task_id, file_url)
        return {"status": "queued", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/entity/{entity_id}")
async def override_entity(entity_id: str, data: EntityOverride):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT type, description, attributes_json FROM entities WHERE id = %s", (entity_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="档案不存在")
        
        old_type = row["type"] if isinstance(row, dict) else row[0]
        old_desc = row["description"] if isinstance(row, dict) else row[1]
        old_attrs = row["attributes_json"] if isinstance(row, dict) else row[2]
            
        new_type = data.type if (data.type is not None and data.type != '') else old_type
        new_desc = data.description if data.description is not None else old_desc
        
        current_attrs = json.loads(old_attrs) if old_attrs and old_attrs != 'null' else {}
        if data.attributes is not None:
            current_attrs.update(data.attributes)
        new_attrs_json = json.dumps(current_attrs, ensure_ascii=False)
        
        cursor.execute("UPDATE entities SET type = %s, description = %s, attributes_json = %s WHERE id = %s", 
                       (new_type, new_desc, new_attrs_json, entity_id))
        conn.commit()
        conn.close()

        neo_query = """MATCH (e:Entity {id: $eid}) SET e.type = $type, e.description = $desc, e.attributes_json = $attrs RETURN e"""
        neo_db.execute_query(neo_query, {"eid": entity_id, "type": new_type, "desc": new_desc, "attrs": new_attrs_json})

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export")
async def export_data(format: str = "json", entity_type: str = None, days: int = 30):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        time_threshold = _format_dt(datetime.now(timezone.utc) - timedelta(days=days))

        if format == "csv":
            import io, csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "type", "name", "description", "created_at"])

            if entity_type:
                cursor.execute("SELECT id, type, name, description, created_at FROM entities WHERE type = %s", (entity_type,))
            else:
                cursor.execute("SELECT id, type, name, description, created_at FROM entities")

            for row in cursor.fetchall():
                r_id = row["id"] if isinstance(row, dict) else row[0]
                r_type = row["type"] if isinstance(row, dict) else row[1]
                r_name = row["name"] if isinstance(row, dict) else row[2]
                r_desc = row["description"] if isinstance(row, dict) else row[3]
                r_created = row["created_at"] if isinstance(row, dict) else row[4]
                writer.writerow([r_id, r_type, r_name, r_desc or "", r_created])

            writer.writerow([])
            writer.writerow(["source_id", "target_id", "relation_type", "evidence"])
            cursor.execute("SELECT source_id, target_id, relation_type, evidence FROM relationships")
            for row in cursor.fetchall():
                s_id = row["source_id"] if isinstance(row, dict) else row[0]
                t_id = row["target_id"] if isinstance(row, dict) else row[1]
                r_type = row["relation_type"] if isinstance(row, dict) else row[2]
                ev = row["evidence"] if isinstance(row, dict) else row[3]
                writer.writerow([s_id, t_id, r_type, ev or ""])

            conn.close()
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]), media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=ai_tracker_export_{datetime.now().strftime('%Y%m%d')}.csv"}
            )
        else:
            result = {"export_time": _format_dt(datetime.now(timezone.utc)), "entities": [], "relationships": [], "events": []}
            if entity_type:
                cursor.execute("SELECT id, type, name, description, created_at, aliases_json, attributes_json FROM entities WHERE type = %s", (entity_type,))
            else:
                cursor.execute("SELECT id, type, name, description, created_at, aliases_json, attributes_json FROM entities")

            for row in cursor.fetchall():
                # 兼容 dict / tuple
                data_dict = dict(row) if isinstance(row, dict) else {
                    "id": row[0], "type": row[1], "name": row[2], "description": row[3],
                    "created_at": row[4], "aliases_json": row[5], "attributes_json": row[6]
                }
                
                al_json = data_dict["aliases_json"]
                at_json = data_dict["attributes_json"]
                
                result["entities"].append({
                    "id": data_dict["id"], "type": data_dict["type"], "name": data_dict["name"], "description": data_dict["description"],
                    "created_at": data_dict["created_at"],
                    "aliases": json.loads(al_json) if al_json and al_json not in ('null', '') else [],
                    "attributes": json.loads(at_json) if at_json and at_json not in ('null', '') else {}
                })

            cursor.execute("SELECT source_id, target_id, relation_type, evidence FROM relationships")
            for row in cursor.fetchall():
                data_dict = dict(row) if isinstance(row, dict) else {"source_id": row[0], "target_id": row[1], "relation_type": row[2], "evidence": row[3]}
                result["relationships"].append(data_dict)

            cursor.execute("SELECT id, title, date, published_date, summary, source_url, risk_level, sentiment FROM events WHERE date >= %s", (time_threshold,))
            for row in cursor.fetchall():
                data_dict = dict(row) if isinstance(row, dict) else {"id": row[0], "title": row[1], "date": row[2], "published_date": row[3], "summary": row[4], "source_url": row[5], "risk_level": row[6], "sentiment": row[7]}
                result["events"].append(data_dict)

            conn.close()
            return result
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

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in request.history]
        response_text = await asyncio.to_thread(chat_with_graph, request.query, history_dicts)
        return {"response": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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