# -*- coding: utf-8 -*-
"""MCP Server 配置"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# PostgreSQL 配置
PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "172.20.0.4"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "user": os.environ.get("PG_USER", "postgres"),
    "password": os.environ.get("PG_PASSWORD", "difyai123456"),
    "database": os.environ.get("PG_DATABASE", "ai_tracker"),
}

# MiniMax API 配置
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cp-W86nFgVDO6HwjK4jGw-_WrtN_b84EFi-u7OC1fUoBEeZ-0o_4sJ9r6sCR9lRI4AbolC4QurzaniyLjdI6s9I_hYzBrbpVw2dDeiJ0tQNoTSCQGa5yO6OkX4")
MINIMAX_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
MINIMAX_MODEL = "MiniMax-M2.7-highspeed"

# Redis 配置
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")