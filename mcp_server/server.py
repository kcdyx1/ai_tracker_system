# -*- coding: utf-8 -*-
"""
AI Tracker MCP Server v1.2
提供知识查询、系统状态、内容注入的标准化 MCP 接口
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from mcp.server import Server
from mcp.types import Tool, TextContent

from mcp_server.tools.system import get_tools as get_system_tools
from mcp_server.tools.nl_query import get_nl_query_tool
from mcp_server.tools.ingestion import get_ingestion_tools

# Server instance
app = Server("ai-tracker-mcp")

# Get all tools
SYSTEM_TOOLS = get_system_tools()
NL_QUERY_TOOL = get_nl_query_tool()
INGESTION_TOOLS = get_ingestion_tools()
ALL_TOOLS = SYSTEM_TOOLS + [NL_QUERY_TOOL] + INGESTION_TOOLS


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools"""
    return [tool.to_mcp_tool() for tool in ALL_TOOLS]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from MCP clients"""
    for tool in ALL_TOOLS:
        if tool.name == name:
            # Handle tools with different parameter requirements
            if name == "nl_query":
                result = await tool.execute(
                    question=arguments.get("question", ""),
                    limit=arguments.get("limit", 10)
                )
            else:
                result = await tool.execute(**arguments)
            return [TextContent(type="text", text=result)]
    raise ValueError(f"Unknown tool: {name}")


async def main():
    """Main entry point"""
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())