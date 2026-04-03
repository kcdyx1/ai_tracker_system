#!/usr/bin/env python3
"""
AI Tracker System - 工业级分布式引擎 (Celery Worker)
承载高并发的大模型解析任务，包含网页拉取、Markdown切片与知识抽取。
"""

import os
from celery import Celery
from celery.schedules import crontab
from markitdown import MarkItDown
import sqlite3
import json
from datetime import datetime

from database import update_task_status, save_extraction_result
from extractor import extract_with_validation
from ingestion import fetch_clean_markdown

DB_PATH = "/home/kangchen/.openclaw/workspace/ai_tracker_system/ai_tracker.db"

celery_app = Celery(
    'ai_tracker',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

celery_app.conf.update(
    worker_concurrency=4,
    task_acks_late=True,
    # Celery Beat 定时任务配置
    beat_schedule={
        'daily-deduplicate': {
            'task': 'worker.deduplicate_entities',
            'schedule': crontab(hour=3, minute=0),  # 每天凌晨3点执行
        },
        'daily-backup': {
            'task': 'worker.backup_database',
            'schedule': crontab(hour=3, minute=30),  # 每天凌晨3:30执行
        },
    },
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


def _build_in_clause(ids: list) -> tuple[str, list]:
    """构建安全的 SQL IN 子句，返回 (placeholders, params)"""
    if not ids:
        return "('__invalid__')", []
    placeholders = ','.join('?' * len(ids))
    return f'({placeholders})', ids


@celery_app.task
def deduplicate_entities():
    """每天定时执行实体去重合并"""
    print(f"\n🧹 [去重任务] 开始执行实体去重...")
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()

    try:
        # 找出所有有重复的 (name, type) 组
        cursor.execute("""
            SELECT name, type, COUNT(*) as cnt
            FROM entities
            WHERE name IS NOT NULL AND name != ''
            GROUP BY name, type
            HAVING cnt > 1
        """)
        groups = cursor.fetchall()

        if not groups:
            print("🧹 [去重任务] 没有发现重复实体")
            return

        total_merged = 0
        for name, etype, cnt in groups:
            # 找出该组所有实体ID及其完整度
            cursor.execute("""
                SELECT id, description, attributes_json
                FROM entities
                WHERE name = ? AND type = ?
            """, (name, etype))
            rows = cursor.fetchall()

            def completeness(row):
                eid, desc, attrs_str = row
                score = 0
                if desc and desc != 'null' and len(str(desc)) > 5:
                    score += 2
                if attrs_str and attrs_str != 'null':
                    try:
                        attrs = json.loads(attrs_str)
                        score += len([v for v in attrs.values() if v and str(v) not in ('[]', '{}', 'null', 'None', '')])
                    except (json.JSONDecodeError, ValueError):
                        pass
                return score

            # 按完整度排序，保留最完整的
            rows.sort(key=completeness, reverse=True)
            primary_id = rows[0][0]
            duplicate_ids = [r[0] for r in rows[1:]]

            if not duplicate_ids:
                continue

            # 将重复实体的关系转移到主实体 (使用参数化查询)
            in_clause, in_params = _build_in_clause(duplicate_ids)
            cursor.execute(f"""
                UPDATE relationships
                SET source_id = ?
                WHERE source_id IN {in_clause}
            """, [primary_id] + in_params)

            in_clause, in_params = _build_in_clause(duplicate_ids)
            cursor.execute(f"""
                UPDATE relationships
                SET target_id = ?
                WHERE target_id IN {in_clause}
            """, [primary_id] + in_params)

            # 将事件关联到主实体
            in_clause, in_params = _build_in_clause(duplicate_ids)
            cursor.execute(f"""
                UPDATE events
                SET entity_id = ?
                WHERE entity_id IN {in_clause}
            """, [primary_id] + in_params)

            # 删除重复实体
            in_clause, in_params = _build_in_clause(duplicate_ids)
            cursor.execute(f"""
                DELETE FROM entities
                WHERE id IN {in_clause}
            """, in_params)

            total_merged += len(duplicate_ids)

        conn.commit()
        print(f"🧹 [去重任务] 完成！合并了 {len(groups)} 组，共删除 {total_merged} 个重复实体")

    except Exception as e:
        print(f"❌ [去重任务] 失败: {e}")
        conn.rollback()
    finally:
        conn.close()


@celery_app.task
def backup_database():
    """每天定时备份数据库"""
    import shutil
    from pathlib import Path

    backup_dir = Path(DB_PATH).parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = backup_dir / f"ai_tracker_{timestamp}.db"

    try:
        shutil.copy2(DB_PATH, backup_file)
        print(f"💾 [备份任务] 数据库已备份到: {backup_file}")

        # 保留最近7天备份，删除更旧的
        backups = sorted(backup_dir.glob("ai_tracker_*.db"), key=lambda p: p.stat().st_mtime)
        for old_backup in backups[:-7]:
            old_backup.unlink()
            print(f"🗑️ [备份任务] 删除过期备份: {old_backup}")

        print(f"💾 [备份任务] 备份完成，当前共 {len(backups)} 个备份")

    except Exception as e:
        print(f"❌ [备份任务] 备份失败: {e}")
