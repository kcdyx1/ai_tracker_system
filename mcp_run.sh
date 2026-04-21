#!/bin/bash
# Wrapper to launch ai-tracker MCP server with -m module syntax
cd /home/kangchen/.openclaw/workspace/ai_tracker_system
exec /home/kangchen/.openclaw/workspace/ai_tracker_system/mcp_venv/bin/python -m mcp_server.server "$@"
