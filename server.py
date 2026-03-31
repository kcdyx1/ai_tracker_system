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
from fastapi import FastAPI, Request, HTTPException
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
            # 💡 核心升级：全局大盘，拉取最核心的拓扑结构
            query = """
            MATCH (s:Entity)-[r]->(t:Entity)
            RETURN s.id AS source_id, s.name AS source_name, s.type AS source_type,
                   type(r) AS rel_type,
                   t.id AS target_id, t.name AS target_name, t.type AS target_type
            LIMIT 300
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

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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