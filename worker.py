#!/usr/bin/env python3
"""
AI Tracker System - 工业级分布式引擎 (Celery Worker)
承载高并发的大模型解析任务，包含网页拉取、Markdown切片与知识抽取。
"""

import os
from celery import Celery
from celery.schedules import crontab
from markitdown import MarkItDown
import json
from datetime import datetime, timezone, timedelta

from database import update_task_status, save_extraction_result, get_connection
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
    # Celery Beat 定时任务配置
    beat_schedule={
        'reset-stuck-tasks': {
            'task': 'worker.reset_stuck_tasks',
            'schedule': crontab(minute='*/30'),  # 每30分钟执行
        },
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
def process_intel_task(self, task_id: int, url: str, rss_summary: str = ""):
    """真正的异步解析大拿"""
    print(f"\n🚀 [V8 引擎] 开始处理高价值目标 #{task_id}: {url}")
    # guard: skip if already processing/completed
    from database import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM task_queue WHERE id = %s", (task_id,))
        row = cur.fetchone()
        if row and row['status'] == "completed":
            print(f"  skip: task #{task_id} already completed")
            return
    finally:
        conn.close()

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
            result = extract_with_validation(chunk, source_url=url)
            if result.entities or result.events:
                save_extraction_result(result)
                total_ent += len(result.entities)
                total_evt += len(result.events)

        update_task_status(task_id, "completed")
        print(f"🎉 [V8 引擎] 任务 #{task_id} 完美解析! 共摄入 {total_ent} 实体, {total_evt} 事件")

    except Exception as e:
        error_str = str(e)
        print("ERROR [V8] Task #" + str(task_id) + " error: " + error_str)

        # 判断是否是永久失败错误（网站封禁、内容为空等）
        permanent_errors = [
            "网页抓取为空或遭拦截",
            "连接超时",
            "无法访问",
            "页面加载失败",
        ]
        is_permanent = any(err in error_str for err in permanent_errors)

        # 获取当前 fail_count
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT fail_count FROM task_queue WHERE id = %s", (task_id,))
        row = cur.fetchone()
        prev_count = row["fail_count"] if row else 0
        conn.close()

        new_count = prev_count + 1

        # 超过阈值，检查是否有 RSS summary 作为降级 fallback
        if rss_summary:
            print("WARNING [V8] Task #" + str(task_id) + " failed " + str(new_count) + " times, using RSS summary fallback")
            content = "# " + url + "\n\n" + rss_summary
            chunk_size, overlap = 8000, 400
            chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size - overlap)]
            total_ent, total_evt = 0, 0
            for i, chunk in enumerate(chunks):
                result = extract_with_validation(chunk, source_url=url)
                if result.entities or result.events:
                    save_extraction_result(result)
                    total_ent += len(result.entities)
                    total_evt += len(result.events)
            update_task_status(task_id, "completed")
            print("🎉 [V8] 任务 #" + str(task_id) + " RSS降级解析完成! 共摄入 " + str(total_ent) + " 实体, " + str(total_evt) + " 事件")
            return
        elif is_permanent:
            # 指数退避：1h -> 6h -> 24h -> 72h
            delays = [3600, 21600, 86400, 259200]
            delay = delays[min(new_count - 1, len(delays) - 1)]
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
            update_task_status(task_id, "failed", error_str, fail_count=new_count,
                             next_retry_at=next_retry.isoformat())
            print("WARNING [V8] Task #" + str(task_id) + " failed " + str(new_count) + " times, retry in " + str(delay//3600) + "h")
            schedule_retry.apply_async(args=[task_id], countdown=delay)
            return  # 不使用 self.retry
        else:
            # 临时错误，保持原有逻辑
            update_task_status(task_id, "failed", error_str)
            raise self.retry(exc=e, countdown=60)


def _build_in_clause(ids: list) -> tuple[str, list]:
    """构建安全的 SQL IN 子句，返回 (placeholders, params)"""
    if not ids:
        return "('__invalid__')", []
    placeholders = ','.join('%s' * len(ids))
    return f'({placeholders})', list(ids)


@celery_app.task
def schedule_retry(task_id: int):
    """延迟重试任务：将 failed 改回 pending 并触发处理"""
    from database import push_task
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT url FROM task_queue WHERE id = %s", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    url = row["url"]
    cur.execute(
        "UPDATE task_queue SET status = 'pending' WHERE id = %s AND status = 'failed'",
        (task_id,)
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if changed:
        print("[retry] Task #" + str(task_id) + " (" + url + ") requeued")
        process_intel_task.apply_async(args=[task_id, url])

def reset_stuck_tasks():
    """重置卡死的任务：processing 超时 和 到期的指数退避任务"""
    print("[Stuck-Release] Starting stuck task scan...")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 重置卡死的 processing 任务
        cursor.execute(
            "UPDATE task_queue SET status = 'pending', error_message = 'auto-reset: stuck in processing > 30min' WHERE status = 'processing' AND created_at < NOW() - INTERVAL '30 minutes'"
        )
        conn.commit()
        count1 = cursor.rowcount

        # 重置到期的指数退避任务
        cursor.execute(
            "UPDATE task_queue SET status = 'pending' WHERE status = 'failed' AND next_retry_at IS NOT NULL AND next_retry_at <= NOW() AND fail_count > 0 AND fail_count < 5"
        )
        conn.commit()
        count2 = cursor.rowcount

        total = count1 + count2
        if total > 0:
            print("[Stuck-Release] Reset " + str(total) + " tasks (" + str(count1) + " processing, " + str(count2) + " retry)")
        else:
            print("[Stuck-Release] No stuck tasks found")
    finally:
        conn.close()

@celery_app.task
def deduplicate_entities():
    """每天定时执行实体去重合并"""
    print(f"\n🧹 [去重任务] 开始执行实体去重...")
    conn = get_connection()
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
                WHERE name = %s AND type = %s
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
                SET source_id = %s
                WHERE source_id IN {in_clause}
            """, [primary_id] + in_params)

            in_clause, in_params = _build_in_clause(duplicate_ids)
            cursor.execute(f"""
                UPDATE relationships
                SET target_id = %s
                WHERE target_id IN {in_clause}
            """, [primary_id] + in_params)

            # 将事件关联中的重复实体ID替换为主实体ID
            # events 使用 involved_entities_json (JSON数组)，需要逐条处理
            cursor.execute("SELECT id, involved_entities_json FROM events")
            for event_row in cursor.fetchall():
                event_id, involved_json = event_row
                if not involved_json or involved_json in ('null', ''):
                    continue
                try:
                    entity_ids = json.loads(involved_json)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
                updated = False
                new_ids = []
                for eid in entity_ids:
                    if eid in duplicate_ids:
                        new_ids.append(primary_id)
                        updated = True
                    else:
                        new_ids.append(eid)
                if updated:
                    cursor.execute(
                        "UPDATE events SET involved_entities_json = %s WHERE id = %s",
                        (json.dumps(new_ids, ensure_ascii=False), event_id)
                    )

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
    """每天定时备份 PostgreSQL 数据库（pg_dump）"""
    import subprocess
    from pathlib import Path
    import os

    backup_dir = Path.home() / ".openclaw" / "workspace" / "ai_tracker_system" / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = backup_dir / f"ai_tracker_{timestamp}.sql"

    try:
        env = dict(os.environ)
        env['PGPASSWORD'] = 'difyai123456'
        result = subprocess.run([
            'pg_dump', '-h', '172.20.0.6', '-U', 'postgres',
            '-d', 'ai_tracker', '-f', str(backup_file)
        ], env=env, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print(f"💾 [备份任务] 数据库已备份到: {backup_file}")
            backups = sorted(backup_dir.glob("ai_tracker_*.sql"), key=lambda p: p.stat().st_mtime)
            for old_b in backups[:-7]:
                old_b.unlink()
                print(f"🗑️ [备份任务] 删除过期备份: {old_b}")
            print(f"💾 [备份任务] 当前共 {len(backups)} 个备份")
        else:
            print(f"❌ [备份任务] pg_dump 失败: {result.stderr}")
    except Exception as e:
        print(f"❌ [备份任务] 备份失败: {e}")