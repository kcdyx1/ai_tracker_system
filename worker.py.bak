#!/usr/bin/env python3
"""
AI Tracker System - 工业级分布式引擎 (Celery Worker)
承载高并发的大模型解析任务，包含网页拉取、Markdown切片与知识抽取。
"""

import os
from celery import Celery
from markitdown import MarkItDown

from database import update_task_status, save_extraction_result
from extractor import extract_with_validation
from ingestion import fetch_clean_markdown

celery_app = Celery(
    'ai_tracker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

celery_app.conf.update(
    worker_concurrency=4, 
    task_acks_late=True,
)

@celery_app.task(bind=True, max_retries=3)
def process_intel_task(self, task_id: int, url: str):
    """真正的异步解析大拿"""
    print(f"\n🚀 [V8 引擎] 开始处理高价值目标 #{task_id}: {url}")
    try:
        update_task_status(task_id, 'processing')
        
        # 1. 多模态内容提取 (网页 or 本地文档)
        content = ""
        if url.startswith("file://"):
            file_path = url[7:]
            md = MarkItDown()
            # Celery 是同步环境，直接调用即可
            parsed = md.convert(file_path)
            content = parsed.text_content
        else:
            content = fetch_clean_markdown(url)
            if not content: raise Exception("网页抓取为空或遭拦截")
            
        # 2. 黄金切片：8000字，重叠400字
        chunk_size, overlap = 8000, 400
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size - overlap)]
        
        total_ent, total_evt = 0, 0
        
        # 3. 呼叫大模型进行信息榨取
        for i, chunk in enumerate(chunks):
            result = extract_with_validation(chunk)
            if result.entities or result.events:
                save_extraction_result(result)
                total_ent += len(result.entities)
                total_evt += len(result.events)
        
        update_task_status(task_id, "completed")
        print(f"🎉 [V8 引擎] 任务 #{task_id} 完美解析! 共摄入 {total_ent} 实体, {total_evt} 事件")
        
    except Exception as e:
        print(f"❌ [V8 引擎] 任务 #{task_id} 发生异常: {e}")
        update_task_status(task_id, "failed", str(e))
        # 60秒后自动重新投胎
        raise self.retry(exc=e, countdown=60)