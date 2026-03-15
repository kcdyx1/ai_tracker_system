#!/usr/bin/env python3
"""
AI Tracker System - FastAPI 服务端

提供 REST API 接口和后台任务 Worker
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
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


# 任务队列
task_queue = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，启动时初始化数据库和后台 Worker"""
    # 启动时初始化数据库
    print("📦 初始化数据库...")
    init_db()
    
    # 启动后台 Worker
    print("🚀 启动后台 Worker...")
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
                    # Step 1: 抓取网页内容
                    print(f"  🔄 正在抓取网页...")
                    content = fetch_clean_markdown(url)
                    
                    if not content:
                        raise Exception("网页抓取失败，返回内容为空")
                    
                    print(f"  ✅ 抓取成功，内容长度: {len(content)} 字符")
                    
                    # Step 2: AI 知识提取
                    print(f"  🔄 正在进行 AI 知识提取...")
                    result = extract_with_validation(content)
                    print(f"  ✅ 提取成功: {len(result.entities)} 实体, {len(result.events)} 事件")
                    
                    # Step 3: 保存到数据库
                    print(f"  🔄 正在保存到数据库...")
                    save_extraction_result(result)
                    print(f"  ✅ 保存成功")
                    
                    # 更新任务状态为完成
                    update_task_status(task_id, "completed")
                    print(f"  🎉 任务 #{task_id} 完成!")
                    
                except Exception as e:
                    # 标记任务失败
                    update_task_status(task_id, "failed")
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
# 主程序入口
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
