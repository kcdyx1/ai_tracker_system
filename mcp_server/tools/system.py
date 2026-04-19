# -*- coding: utf-8 -*-
"""System status query tools for AI Tracker MCP Server"""
import psycopg2
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import PG_CONFIG


class MCPTool:
    """Base class for MCP tools"""
    def __init__(self, name: str, description: str, input_schema: dict):
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def to_mcp_tool(self):
        from mcp.types import Tool
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema
        )

    async def execute(self, **kwargs) -> str:
        raise NotImplementedError


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


class GetSystemHealthTool(MCPTool):
    def __init__(self):
        super().__init__(
            name="get_system_health",
            description="获取 AI Tracker 系统各组件的健康状态。包括 PostgreSQL、Redis、Neo4j、Celery Workers、RSSHub 等组件的状态。",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )

    async def execute(self, **kwargs) -> str:
        lines = ["=== AI Tracker 系统状态 ===", ""]

        # PostgreSQL check
        try:
            conn = get_pg_conn()
            cur = conn.cursor()
            cur.execute("SELECT pg_database_size('ai_tracker') / 1024 / 1024 as size_mb")
            size = cur.fetchone()[0]
            cur.execute("SELECT NOW()")
            now = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM events")
            event_count = cur.fetchone()[0]
            conn.close()
            lines.append(f"【PostgreSQL】healthy ({size:.1f}MB, {event_count} events)")
        except Exception as e:
            lines.append(f"【PostgreSQL】unhealthy: {e}")

        # Redis check
        try:
            import redis
            r = redis.from_url("redis://localhost:6379/0")
            r.ping()
            info = r.info()
            lines.append(f"【Redis】healthy (uptime: {info.get('uptime_in_days', '?')}d)")
        except Exception as e:
            lines.append(f"【Redis】unhealthy: {e}")

        # Celery queue check
        try:
            conn = get_pg_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT status, COUNT(*)
                FROM task_queue
                WHERE created_at > CURRENT_DATE
                GROUP BY status
            """)
            rows = cur.fetchall()
            pending = sum(c for s, c in rows if s == 'pending')
            completed = sum(c for s, c in rows if s == 'completed')
            failed = sum(c for s, c in rows if s == 'failed')
            lines.append(f"【Celery队列】pending={pending}, completed={completed}, failed={failed}")
            conn.close()
        except Exception as e:
            lines.append(f"【Celery队列】check failed: {e}")

        lines.append("")
        lines.append(f"查询时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        return "\n".join(lines)


class GetDatabaseStatsTool(MCPTool):
    def __init__(self):
        super().__init__(
            name="get_database_stats",
            description="获取 AI Tracker 数据库的实时统计信息。包括 events、entities、relationships 的总数和近7天新增数量。",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )

    async def execute(self, **kwargs) -> str:
        lines = ["=== AI Tracker 数据库统计 ===", ""]

        try:
            conn = get_pg_conn()
            cur = conn.cursor()

            # Events stats
            cur.execute("SELECT COUNT(*) FROM events")
            total_events = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM events WHERE created_at > CURRENT_DATE - INTERVAL '7 days'")
            recent_events = cur.fetchone()[0]

            # Entities stats
            cur.execute("SELECT COUNT(*) FROM entities")
            total_entities = cur.fetchone()[0]
            cur.execute("SELECT type, COUNT(*) FROM entities GROUP BY type ORDER BY COUNT(*) DESC LIMIT 5")
            entity_types = cur.fetchall()

            # Relationships
            cur.execute("SELECT COUNT(*) FROM relationships")
            total_rels = cur.fetchone()[0]

            # Events by risk level
            cur.execute("""
                SELECT risk_level, COUNT(*)
                FROM events
                WHERE published_date > CURRENT_DATE - INTERVAL '30 days'
                  AND risk_level IS NOT NULL
                GROUP BY risk_level
                ORDER BY COUNT(*) DESC
            """)
            risk_stats = cur.fetchall()

            # Recent date distribution
            cur.execute("""
                SELECT published_date::date, COUNT(*)
                FROM events
                WHERE published_date > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY published_date::date
                ORDER BY published_date::date DESC
            """)
            recent_dates = cur.fetchall()

            conn.close()

            lines.append(f"【Events】总计: {total_events:,} 条，近7天: +{recent_events:,} 条")
            lines.append(f"【Entities】总计: {total_entities:,} 条")
            for etype, cnt in entity_types:
                lines.append(f"  - {etype}: {cnt:,}")
            lines.append(f"【Relationships】总计: {total_rels:,} 条")
            lines.append("")
            lines.append("【近7天事件趋势】")
            for date, cnt in recent_dates:
                lines.append(f"  {date}: {cnt} 条")
            lines.append("")
            lines.append("【近30天风险分布】")
            for risk, cnt in risk_stats:
                lines.append(f"  {risk or '(无标签)'}: {cnt} 条")

        except Exception as e:
            lines.append(f"查询失败: {e}")

        return "\n".join(lines)


class GetTaskQueueStatusTool(MCPTool):
    def __init__(self):
        super().__init__(
            name="get_task_queue_status",
            description="获取 Celery 任务队列的实时状态。包括 pending、processing、completed、failed 任务数量。",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )

    async def execute(self, **kwargs) -> str:
        lines = ["=== Celery 任务队列状态 ===", ""]

        try:
            conn = get_pg_conn()
            cur = conn.cursor()

            # Overall stats
            cur.execute("""
                SELECT status, COUNT(*), MAX(created_at)
                FROM task_queue
                WHERE created_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY status
                ORDER BY COUNT(*) DESC
            """)
            rows = cur.fetchall()

            total = sum(cnt for _, cnt, _ in rows)
            lines.append(f"近7天任务总数: {total}")
            lines.append("")
            for status, cnt, last_at in rows:
                status_icon = {"pending": "[P]", "processing": "[R]", "completed": "[OK]", "failed": "[X]"}.get(status, status)
                lines.append(f"{status_icon} {status}: {cnt} 条 (最后: {last_at})")

            # Check for stuck tasks
            cur.execute("""
                SELECT COUNT(*)
                FROM task_queue
                WHERE status = 'pending'
                  AND created_at < CURRENT_TIMESTAMP - INTERVAL '2 hours'
            """)
            stuck = cur.fetchone()[0]
            if stuck > 0:
                lines.append("")
                lines.append(f"WARNING: {stuck} 个任务等待超过2小时，可能卡住")

            # Failed tasks detail
            cur.execute("""
                SELECT url, fail_count, created_at
                FROM task_queue
                WHERE status = 'failed'
                ORDER BY created_at DESC
                LIMIT 5
            """)
            failed_rows = cur.fetchall()
            if failed_rows:
                lines.append("")
                lines.append("【最近失败任务】")
                for url, fail_count, created_at in failed_rows:
                    lines.append(f"  - {str(url)[:50]} (失败{fail_count}次)")

            conn.close()

        except Exception as e:
            lines.append(f"查询失败: {e}")

        return "\n".join(lines)


# Export tool instances
def get_tools():
    return [
        GetSystemHealthTool(),
        GetDatabaseStatsTool(),
        GetTaskQueueStatusTool(),
    ]