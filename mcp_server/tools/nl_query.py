# -*- coding: utf-8 -*-
"""NL Query Tool — 自然语言知识查询"""
import psycopg2
from ..nl_engine import get_nl_engine, NLEngine
from ..config import PG_CONFIG


class NLQueryTool:
    """自然语言查询工具"""

    def __init__(self):
        self.name = "nl_query"
        self.description = """自然语言查询 AI Tracker 知识库。

用户用自然语言提问，例如：
- "最近一周有哪些大模型发布？"
- "哪些公司在做 AI Agent 投资？"
- "DeepSeek 最近有什么动态？"
- "最近有哪些高危风险事件？"

返回格式：结构化文本，便于 Agent 直接阅读或转发。
如果找不到相关信息，返回"未找到相关记录"。
"""
        self.input_schema = {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "自然语言问题，例如：'最近有哪些大模型发布？'"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制，默认10",
                    "default": 10
                }
            },
            "required": ["question"]
        }

    def to_mcp_tool(self):
        from mcp.types import Tool
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema
        )

    async def execute(self, question: str, limit: int = 10) -> str:
        """
        执行自然语言查询

        Args:
            question: 自然语言问题
            limit: 返回数量限制

        Returns:
            格式化的查询结果文本
        """
        # 调用 NL Engine 解析问题
        engine = get_nl_engine()
        parse_result = engine.parse_question(question, limit)

        sql = parse_result["sql"]
        explanation = parse_result["explanation"]
        degraded = parse_result.get("degraded", False)

        # 执行 SQL 查询
        try:
            conn = psycopg2.connect(**PG_CONFIG)
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            conn.close()

            # 格式化结果
            if not rows:
                return f"根据查询'{question}'，找到 0 条结果。\n\n说明：{explanation}"

            result_lines = [f"根据查询'{question}'，找到 {len(rows)} 条结果：" ]
            result_lines.append(f"说明：{explanation}")
            if degraded:
                result_lines.append("[注意：MiniMax API 不可用，采用规则匹配降级模式]")
            result_lines.append("")

            for i, row in enumerate(rows, 1):
                title, summary, published_date, source_url, risk_level, sentiment = row
                result_lines.append(f"{i}. {title}")
                if published_date:
                    date_str = str(published_date)[:16] if published_date else "未知"
                    result_lines.append(f"   时间：{date_str}")
                if source_url:
                    result_lines.append(f"   来源：{source_url[:60]}...")
                if risk_level:
                    result_lines.append(f"   风险：{risk_level}")
                if sentiment:
                    result_lines.append(f"   情绪：{sentiment}")
                if summary:
                    summary_text = str(summary)[:100] + "..." if len(str(summary)) > 100 else str(summary)
                    result_lines.append(f"   摘要：{summary_text}")
                result_lines.append("")

            return "\n".join(result_lines)

        except Exception as e:
            return f"查询执行失败：{str(e)}\n\nSQL: {sql}"


# Export tool instance
def get_nl_query_tool():
    return NLQueryTool()


# Backwards compatibility
def get_tool():
    return NLQueryTool()