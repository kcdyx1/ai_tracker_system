#!/usr/bin/env python3
"""
AI Tracker System - FastAPI 服务端

提供 REST API 接口和后台任务 Worker
"""

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
import shutil
import uuid
from pathlib import Path
from pydantic import BaseModel

from database import (
    init_db,
    push_task,
    get_pending_task,
    update_task_status,
    save_extraction_result
)
from extractor import extract_with_validation
from ingestion import fetch_clean_markdown


# API Key 从环境变量获取
API_KEY = os.environ.get("MINIMAX_API_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，启动时初始化数据库和后台 Worker"""
    # 启动时初始化数据库
    print("📦 初始化数据库...")
    init_db()
    
    # --- 自愈机制：重置僵尸任务 ---
    from database import get_connection
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE task_queue SET status = 'pending' WHERE status = 'processing'")
        reset_count = cursor.rowcount
        conn.commit()
        conn.close()
        if reset_count > 0:
            print(f"🧹 自愈机制触发：已将 {reset_count} 个意外中断的僵尸任务重置为排队状态")
    except Exception as e:
        print(f"⚠️ 僵尸任务重置失败: {e}")
    # ------------------------------
    
    # 启动后台 Worker (3 线程并发)
    print("🚀 启动 3 个并发后台 Worker...")
    for _ in range(3):
        asyncio.create_task(background_worker())
    
    yield
    
    # 关闭时清理资源
    print("👋 应用关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="AI Tracker System API",
    description="AI 产业知识提取服务",
    version="1.0.0",
    lifespan=lifespan
)


# 请求模型
class IngestRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    status: str
    url: str


# 后台 Worker 异步函数
async def background_worker():
    """后台任务 Worker，持续从队列获取任务并处理"""
    print("✅ 后台 Worker 已启动")
    
    while True:
        try:
            # 获取待处理任务
            task = get_pending_task()
            
            if task:
                task_id = task["id"]
                url = task["url"]
                print(f"\n[Worker] 开始处理: {url}")
                
                try:
                    content = ""
                    if url.startswith("file://"):
                        file_path = url[7:]
                        print(f"  🔄 正在解析本地文档: {file_path}")
                        try:
                            from markitdown import MarkItDown
                            md = MarkItDown()
                            parsed = await asyncio.to_thread(md.convert, file_path)
                            content = parsed.text_content
                            print(f"  ✅ 文档解析成功，内容长度: {len(content)} 字符")
                        except ImportError:
                            raise Exception("请先安装依赖: pip install markitdown")
                        except Exception as e:
                            raise Exception(f"文档解析失败: {e}")
                    else:
                        print(f"  🔄 正在抓取网页...")
                        content = await asyncio.to_thread(fetch_clean_markdown, url)
                        if not content:
                            raise Exception("网页抓取失败，返回内容为空")
                        print(f"  ✅ 抓取成功，内容长度: {len(content)} 字符")
                        
                    # 长文本切片逻辑 (黄金比例：兼顾速度与召回率)
                    chunk_size = 8000
                    overlap = 400
                    chunks = []
                    start = 0
                    while start < len(content):
                        end = min(start + chunk_size, len(content))
                        chunks.append(content[start:end])
                        start += chunk_size - overlap
                        
                    print(f"  🔪 文本已切分为 {len(chunks)} 个分析块，开始流式图谱构建...")
                    
                    total_entities = 0
                    total_events = 0
                    
                    for i, chunk in enumerate(chunks):
                        print(f"  🔄 [块 {i+1}/{len(chunks)}] AI 知识提取与图谱融合中...")
                        # Step 2: AI 知识提取
                        result = await asyncio.to_thread(extract_with_validation, chunk)
                        
                        # Step 3: 边提取边存库，让数据库充当"全局跨段落记忆体"
                        if result.entities or result.events:
                            await asyncio.to_thread(save_extraction_result, result)
                            total_entities += len(result.entities)
                            total_events += len(result.events)
                            print(f"  ✅ [块 {i+1}/{len(chunks)}] 成功并入图谱: {len(result.entities)}实体, {len(result.events)}事件")
                        else:
                            print(f"  ⏭️ [块 {i+1}/{len(chunks)}] 未发现高价值情报，跳过")
                            
                    # 更新任务状态为完成
                    update_task_status(task_id, "completed")
                    print(f"  🎉 任务 #{task_id} 完成! 累计摄入 {total_entities} 实体, {total_events} 事件")
                    
                except Exception as e:
                    # 标记任务失败
                    update_task_status(task_id, "failed", str(e))
                    print(f"  ❌ 任务 #{task_id} 失败: {e}")
            else:
                # 没有待处理任务，短暂休眠
                await asyncio.sleep(5)
                
        except Exception as e:
            print(f"❌ Worker 异常: {e}")
            await asyncio.sleep(5)


# ============================================================================
# API 路由
# ============================================================================

@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "AI Tracker System API",
        "version": "1.0.0"
    }


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_url(request: IngestRequest):
    """
    接收 URL 并加入任务队列
    
    Args:
        request: 包含 url 的请求体
        
    Returns:
        确认消息
    """
    url = request.url
    
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    
    # 验证 URL 格式
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须是 http 或 https 开头")
    
    # 加入任务队列
    success = push_task(url)
    
    if success:
        return IngestResponse(
            status="queued",
            url=url
        )
    else:
        # URL 已存在（重复提交）
        return IngestResponse(
            status="already_exists",
            url=url
        )



# ============================================================================
# 文件上传路由 (Multi-modal Ingestion)
# ============================================================================
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """接收上传文件并伪装成 file:// 协议加入队列"""
    try:
        # 1. 生成带短哈希的安全文件名，防止中文名或同名冲突
        file_ext = Path(file.filename).suffix
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        save_path = UPLOAD_DIR / safe_name
        
        # 2. 物理保存文件到硬盘
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 3. 架构魔法：伪装成 file:// 协议塞入现有数据库队列
        file_url = f"file://{save_path.absolute()}"
        success = push_task(file_url)
        
        if success:
            return {"status": "queued", "filename": file.filename, "url": file_url}
        else:
            return {"status": "already_exists"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 实体侦察兵路由 (Enricher API)
# ============================================================================
from enricher import run_enrichment

@app.post("/api/enrich/{entity_id}")
async def force_enrich_entity(entity_id: str):
    """手动触发侦察兵，全网扫描补全该实体的缺失参数"""
    try:
        # 侦察过程较长，放入线程池异步执行，但这里为了前端直接拿到结果，使用 await
        result = await asyncio.to_thread(run_enrichment, entity_id)
        if result["status"] == "success":
            return result
        else:
            raise HTTPException(status_code=400, detail=result["message"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
