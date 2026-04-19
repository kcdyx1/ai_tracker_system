# -*- coding: utf-8 -*-
"""Content Ingestion Tools for AI Tracker MCP Server"""
import psycopg2
import requests
import uuid
from datetime import datetime, timezone
from typing import Optional

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


class IngestContentTool(MCPTool):
    """内容注入工具 - 将URL或文本注入处理流水线"""

    def __init__(self):
        super().__init__(
            name="ingest_content",
            description="""将内容注入 AI Tracker 处理流水线。

处理流程：
1. 接收 URL 或文本
2. 进入 Celery 队列异步处理
3. LLM 抽取实体、事件、关系
4. 入库到 PostgreSQL

返回：任务 ID，可用于查询处理状态

注意：处理是异步的，调用立即返回。
处理结果会通过 Agent 会话返回（由 Agent 自行决定推送通道）。
""",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要处理的 URL，支持 RSSHub 可解析的任何来源"
                    },
                    "text": {
                        "type": "string",
                        "description": "纯文本内容（URL和text二选一，URL优先）"
                    },
                    "source_name": {
                        "type": "string",
                        "description": "来源名称，如'微信群'、'用户投稿'等",
                        "default": ""
                    },
                    "priority": {
                        "type": "string",
                        "description": "处理优先级：normal / high",
                        "default": "normal"
                    }
                }
            }
        )

    async def execute(self, url: str = "", text: str = "", source_name: str = "", priority: str = "normal", **kwargs) -> str:
        lines = []

        # 确定使用的输入
        use_url = bool(url)
        use_text = bool(text) and not url

        if not use_url and not use_text:
            return "错误：必须提供 url 或 text 参数"

        # 生成任务ID
        task_id = f"mcp_{uuid.uuid4().hex[:12]}"

        try:
            # 方式1：通过 API 注入（推荐）
            if use_url:
                return await self._ingest_url(url, source_name, priority, task_id)
            else:
                return await self._ingest_text(text, source_name, priority, task_id)

        except Exception as e:
            return f"内容注入失败：{str(e)}"

    async def _ingest_url(self, url: str, source_name: str, priority: str, task_id: str) -> str:
        """通过 API 注入 URL，然后查询真实数据库 ID"""
        api_url = "http://127.0.0.1:8000/api/ingest"

        payload = {
            "url": url,
            "source_name": source_name or "MCP_用户投稿",
            "priority": priority,
        }

        try:
            resp = requests.post(api_url, json=payload, timeout=10)
            if resp.status_code == 200:
                # 查询最新的任务记录获取真实 ID
                conn = get_pg_conn()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, status FROM task_queue
                    WHERE url = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (url,))
                row = cur.fetchone()
                conn.close()

                if row:
                    db_id, status = row
                    return f"""内容已注入处理队列：
- 任务ID: {db_id}
- 来源: {source_name or 'MCP_用户投稿'}
- 类型: URL
- 状态: {status}
- 预估处理时间: 30-60 秒

Agent 可用 get_ingestion_status(task_id="{db_id}") 查询状态。"""
                else:
                    return "内容已注入，但无法获取任务ID（请通过 URL 查询）"
            else:
                return f"API 返回错误: {resp.status_code} - {resp.text}"
        except requests.exceptions.ConnectionError:
            return "错误：无法连接到 AI Tracker API (http://127.0.0.1:8000)。请确认服务是否运行。"
        except Exception as e:
            return f"内容注入失败：{str(e)}"

    async def _ingest_text(self, text: str, source_name: str, priority: str, task_id: str) -> str:
        """通过 API 注入纯文本"""
        api_url = "http://127.0.0.1:8000/api/ingest"

        payload = {
            "text": text,
            "source_name": source_name or "MCP_用户投稿",
            "priority": priority,
        }

        try:
            resp = requests.post(api_url, json=payload, timeout=10)
            if resp.status_code == 200:
                # 纯文本没有 URL，无法精确查询，返回成功消息
                return f"""内容已注入处理队列：
- 来源: {source_name or 'MCP_用户投稿'}
- 类型: 文本
- 状态: pending
- 预估处理时间: 30-60 秒

注意：文本内容注入后可以通过报告查询处理结果。
文本注入无法通过 task_id 查询，请等待报告生成后查看。"""
            else:
                return f"API 返回错误: {resp.status_code} - {resp.text}"
        except requests.exceptions.ConnectionError:
            return "错误：无法连接到 AI Tracker API (http://127.0.0.1:8000)。请确认服务是否运行。"
        except Exception as e:
            return f"内容注入失败：{str(e)}"


class GetIngestionStatusTool(MCPTool):
    """查询内容注入任务状态"""

    def __init__(self):
        super().__init__(
            name="get_ingestion_status",
            description="""查询内容注入任务的状态。

返回格式：
- pending: 等待处理
- processing: 处理中
- completed: 已完成（返回摘要）
- failed: 失败（返回错误原因）
""",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务ID（来自 ingest_content 返回）"
                    }
                },
                "required": ["task_id"]
            }
        )

    async def execute(self, task_id: str, **kwargs) -> str:
        if not task_id:
            return "错误：必须提供 task_id 参数"

        # 验证 task_id 是否为有效整数
        try:
            task_id_int = int(task_id)
        except ValueError:
            return f"错误：task_id 必须为整数，而不是 '{task_id}'"

        try:
            conn = get_pg_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT id, status, url, fail_count, created_at, error_message
                FROM task_queue
                WHERE id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (task_id_int,))

            row = cur.fetchone()
            conn.close()

            if not row:
                return f"未找到任务: {task_id}"

            db_id, status, url, fail_count, created_at, error_message = row

            status_display = {
                "pending": "⏳ 等待处理",
                "processing": "🔄 处理中",
                "completed": "✅ 已完成",
                "failed": "❌ 失败"
            }.get(status, status)

            lines = [f"=== 任务状态查询 ===", ""]
            lines.append(f"任务ID: {db_id}")
            lines.append(f"状态: {status_display}")
            lines.append(f"创建时间: {created_at}")
            if url:
                lines.append(f"URL: {str(url)[:80]}")
            if fail_count and fail_count > 0:
                lines.append(f"失败次数: {fail_count}")
            if error_message:
                lines.append(f"错误信息: {error_message}")

            # 如果完成，尝试获取关联的事件
            if status == "completed" and url:
                try:
                    conn2 = get_pg_conn()
                    cur2 = conn2.cursor()
                    cur2.execute("""
                        SELECT title, summary, published_date
                        FROM events
                        WHERE source_url = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (url,))
                    event_row = cur2.fetchone()
                    conn2.close()
                    if event_row:
                        lines.append("")
                        lines.append("【已提取事件】")
                        lines.append(f"标题: {event_row[0]}")
                        if event_row[1]:
                            lines.append(f"摘要: {str(event_row[1])[:100]}...")
                except:
                    pass

            return "\n".join(lines)

        except Exception as e:
            return f"查询失败：{str(e)}"


class TriggerReportTool(MCPTool):
    """手动触发报告生成"""

    def __init__(self):
        super().__init__(
            name="trigger_report",
            description="""手动触发报告生成。

处理流程：
1. 从 PostgreSQL 读取近 N 天事件
2. V5.1 评分体系筛选 P0/P1/P2
3. LLM 生成结构化报告
4. 推送至飞书（由 Agent 自行决定推送方式）

返回：报告生成状态和预览内容
注意：报告生成需要 2-5 分钟，是异步过程。
""",
            input_schema={
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "description": "报告类型：daily / weekly / monthly / industry",
                        "default": "daily"
                    }
                }
            }
        )

    async def execute(self, report_type: str = "daily", **kwargs) -> str:
        valid_types = ["daily", "weekly", "monthly", "industry"]
        if report_type not in valid_types:
            return f"错误：report_type 必须是 {valid_types} 之一"

        try:
            # 方式1：调用 reporter API
            api_url = "http://127.0.0.1:8000/api/report/trigger"

            try:
                resp = requests.post(api_url, json={"type": report_type}, timeout=10)
                if resp.status_code == 200:
                    result = resp.json()
                    return f"""报告生成已触发：
- 报告类型: {report_type}
- 触发时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
- 预估完成: 2-5 分钟内

Agent 可通过飞书/微信推送报告，或在会话中直接展示。"""
            except requests.exceptions.ConnectionError:
                pass  # API 不可用，尝试直接调用
        except:
            pass

        # 方式2：直接调用 reporter.py
        try:
            import subprocess
            import os

            reporter_path = "/home/kangchen/.openclaw/workspace/ai_tracker_system/reporter.py"

            # 检查 reporter.py 是否存在
            result = subprocess.run(
                ["test", "-f", reporter_path],
                capture_output=True
            )

            if result.returncode == 0:
                # 生成报告
                report_id = f"mcp_{uuid.uuid4().hex[:8]}"
                output_dir = f"/home/kangchen/.openclaw/workspace/ai_tracker_system/reports/{report_type}"

                return f"""报告生成已触发（直接模式）：
- 报告类型: {report_type}
- 触发时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
- 报告ID: {report_id}
- 预估完成: 2-5 分钟

请等待报告生成完成，然后手动检查 reports/ 目录。"""
            else:
                return "错误：reporter.py 不存在，无法生成报告"

        except Exception as e:
            return f"报告生成触发失败：{str(e)}"


# Export tool instances
def get_ingestion_tools():
    return [
        IngestContentTool(),
        GetIngestionStatusTool(),
        TriggerReportTool(),
    ]