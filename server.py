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

from database import (
    init_db, push_task, get_pending_task, update_task_status,
    save_extraction_result, get_connection, get_recent_events, query_all_entities
)
from extractor import extract_with_validation
from ingestion import fetch_clean_markdown
from enricher import run_enrichment

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
        cursor = conn.cursor()
        cursor.execute("UPDATE task_queue SET status = 'pending' WHERE status = 'processing'")
        reset_count = cursor.rowcount
        conn.commit()
        conn.close()
        if reset_count > 0:
            print(f"🧹 自愈触发：已重置 {reset_count} 个僵尸任务")
    except Exception as e:
        print(f"⚠️ 僵尸任务重置失败: {e}")
        
    print("🚀 启动 3 个并发后台 Worker...")
    for _ in range(3):
        asyncio.create_task(background_worker())
    
    yield
    print("👋 应用关闭")

async def background_worker():
    print("✅ 后台 Worker 已启动")
    while True:
        try:
            task = get_pending_task()
            if task:
                task_id, url = task["id"], task["url"]
                print(f"\n[Worker] 开始处理: {url}")
                try:
                    content = ""
                    if url.startswith("file://"):
                        file_path = url[7:]
                        try:
                            from markitdown import MarkItDown
                            md = MarkItDown()
                            parsed = await asyncio.to_thread(md.convert, file_path)
                            content = parsed.text_content
                        except Exception as e:
                            raise Exception(f"文档解析失败: {e}")
                    else:
                        content = await asyncio.to_thread(fetch_clean_markdown, url)
                        if not content: raise Exception("网页抓取为空")
                        
                    # 黄金切片：8000字，重叠400字
                    chunk_size, overlap = 8000, 400
                    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size - overlap)]
                    
                    total_ent, total_evt = 0, 0
                    for i, chunk in enumerate(chunks):
                        result = await asyncio.to_thread(extract_with_validation, chunk)
                        if result.entities or result.events:
                            await asyncio.to_thread(save_extraction_result, result)
                            total_ent += len(result.entities)
                            total_evt += len(result.events)
                    
                    update_task_status(task_id, "completed")
                    print(f"🎉 任务 #{task_id} 完成! 摄入 {total_ent}实体, {total_evt}事件")
                except Exception as e:
                    update_task_status(task_id, "failed", str(e))
                    print(f"❌ 任务 #{task_id} 失败: {e}")
            else:
                await asyncio.sleep(5)
        except Exception as e:
            await asyncio.sleep(5)

# ============================================================================
# App 实例化与 CORS 配置
# ============================================================================
app = FastAPI(title="AI Tracker System API", lifespan=lifespan)

# 允许 React 跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 开发环境允许所有来源
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
    cursor = conn.cursor()
    stats = {}
    
    cursor.execute("SELECT COUNT(*) FROM entities")
    stats["entity_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM events")
    stats["event_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM relationships")
    stats["relationship_count"] = cursor.fetchone()[0]
    
    # 👇 这两行是之前遗漏的，补上后 React 就能亮起来了！
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'company'")
    stats["company_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'product'")
    stats["product_count"] = cursor.fetchone()[0]
    
    conn.close()
    return stats


@app.get("/api/graph")
async def get_graph_data(entity_id: str = None):
    """获取图谱的节点(nodes)和连线(links)数据（带幽灵节点过滤引擎）"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        nodes, links, entity_ids = [], [], set()

        # 1. 查询连线 (拉取最新的 300 条动态关系)
        if entity_id:
            cursor.execute("SELECT source_id, target_id, relation_type FROM relationships WHERE source_id = ? OR target_id = ? LIMIT 300", (entity_id, entity_id))
        else:
            cursor.execute("SELECT source_id, target_id, relation_type FROM relationships ORDER BY id DESC LIMIT 300")

        for row in cursor.fetchall():
            links.append({"source": row[0], "target": row[1], "label": row[2]})
            entity_ids.update([row[0], row[1]])

        # 2. 查询真实存在的节点实体
        valid_node_ids = set()
        if entity_ids:
            placeholders = ','.join(['?'] * len(entity_ids))
            cursor.execute(f"SELECT id, name, type FROM entities WHERE id IN ({placeholders})", list(entity_ids))
            for row in cursor.fetchall():
                nodes.append({"id": row[0], "name": row[1], "type": row[2]})
                valid_node_ids.add(row[0])  # 记录存活的节点

        # 3. 🛡️ 极其重要的装甲：剔除掉不存在的“幽灵连线”
        valid_links = [
            link for link in links 
            if link["source"] in valid_node_ids and link["target"] in valid_node_ids
        ]

        conn.close()
        return {"nodes": nodes, "links": valid_links}
        
    except Exception as e:
        print(f"❌ 图谱 API 崩溃拦截: {e}")
        return {"nodes": [], "links": []}
    

@app.get("/api/events")
async def get_events(limit: int = 30):
    """获取最新事件流 (包含 L2 红绿灯标签)"""
    return get_recent_events(days=30)[:limit]

@app.get("/api/entities")
async def get_entities():
    """获取所有实体档案"""
    return query_all_entities()

@app.get("/api/tasks")
async def get_tasks():
    """获取引擎监控任务队列"""
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, url, status, error_message, created_at FROM task_queue ORDER BY id DESC LIMIT 20")
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks

from database import get_connection

@app.get("/api/task_stats")
async def get_task_stats():
    """获取任务队列的全局统计"""
    conn = get_connection()
    cursor = conn.cursor()
    status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
    for status in status_counts.keys():
        cursor.execute("SELECT COUNT(*) FROM task_queue WHERE status = ?", (status,))
        status_counts[status] = cursor.fetchone()[0]
    conn.close()
    return status_counts

@app.post("/api/ingest")
async def ingest_url(request: IngestRequest):
    if push_task(request.url): return {"status": "queued"}
    return {"status": "already_exists"}

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
        if push_task(file_url): return {"status": "queued", "filename": file.filename}
        return {"status": "already_exists"}
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
    

from rag import chat_with_graph

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """L3 战略参谋部对话接口"""
    try:
        # 将前端传来的 Pydantic 模型转换为字典列表，适配 rag.py
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in request.history]
        
        # 因为调用大模型是阻塞的，所以放进线程池运行
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
    # 1. 挂载静态资源目录 (JS/CSS/图片)
    app.mount("/assets", StaticFiles(directory=frontend_dist_path / "assets"), name="assets")
    
    # 2. 兜底路由 (Catch-All)：支持 React Router 的前端路由
    # 注意：这个路由必须放在所有 /api 路由的最下面！
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        # 排除 api 请求，防止误杀
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