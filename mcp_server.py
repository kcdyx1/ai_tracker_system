from dotenv import load_dotenv
load_dotenv()
#!/usr/bin/env python3
"""
AI Tracker System - MCP 桥接服务
用于将底层 RAG 检索能力直接暴露给 OpenClaw 等 Agent 框架
"""

import asyncio
from mcp.server import Server
import mcp.types as types
from mcp.server.stdio import stdio_server

# 引入你刚才在 rag.py 中准备好的纯检索函数
from rag import get_intelligence_context

# 创建一个名为 industry-radar 的 MCP 服务器
app = Server("industry-radar-mcp")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """告诉 OpenClaw 我们有哪些工具可用"""
    return [
        types.Tool(
            name="query_industry_radar",
            description="查询产业雷达数据库，获取关于公司动态、技术趋势、实体档案及 Neo4j 图谱拓扑关系的深度情报上下文。当你需要了解特定公司、AI产品或行业风向的最新客观事实时，必须调用此工具。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要查询的精确关键词或问题，例如 '英伟达最近的投资动向' 或 'OpenAI 核心参数'"
                    }
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """当 OpenClaw 决定调用工具时，执行这里的逻辑"""
    if name == "query_industry_radar":
        query = arguments.get("query")
        if not query:
            raise ValueError("查询参数 query 不能为空")
        
        try:
            # 调用底层图谱与二维表混合检索
            context = get_intelligence_context(query)
            
            return [
                types.TextContent(
                    type="text",
                    text=f"【产业雷达底层检索返回的情报事实】\n\n{context}\n\n(请基于以上真实数据，结合你的知识进行推演回答)"
                )
            ]
        except Exception as e:
            return [
                types.TextContent(
                    type="text",
                    text=f"⚠️ 雷达系统检索失败: {str(e)}"
                )
            ]
            
    raise ValueError(f"未找到工具: {name}")

async def main():
    """通过标准输入输出 (stdio) 启动服务，这是 Agent 调用的标准模式"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())