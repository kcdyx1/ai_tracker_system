#!/usr/bin/env python3
"""
AI Tracker System - 数据库迁移脚本
扩展支持 papers (学术论文) 和 repositories (开源项目) 表
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


# ============================================================
# 数据库迁移
# ============================================================

DB_PATH = Path(__file__).parent / "ai_tracker.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_papers_table():
    """创建 papers 表"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                abstract TEXT,
                authors TEXT,
                published_date TEXT,
                updated_date TEXT,
                arxiv_id TEXT,
                arxiv_url TEXT,
                pdf_url TEXT,
                categories TEXT,
                comment TEXT,
                doi TEXT,
                citation_count INTEGER DEFAULT 0,
                reference_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'arxiv',
                source_url TEXT,
                raw_metadata TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(arxiv_id, source)
            )
        """)

        # 索引
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id)",
            "CREATE INDEX IF NOT EXISTS idx_papers_citation_count ON papers(citation_count)",
            "CREATE INDEX IF NOT EXISTS idx_papers_published_date ON papers(published_date)",
            "CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source)",
        ]:
            try:
                cursor.execute(idx_sql)
            except sqlite3.OperationalError:
                pass

        conn.commit()
        print("✅ papers 表创建/检查完成")

    except Exception as e:
        print(f"❌ papers 表迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()


def migrate_repositories_table():
    """创建 repositories 表"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL UNIQUE,
                description TEXT,
                stars INTEGER DEFAULT 0,
                forks INTEGER DEFAULT 0,
                watchers INTEGER DEFAULT 0,
                open_issues INTEGER DEFAULT 0,
                language TEXT,
                license TEXT,
                topics TEXT,
                owner TEXT NOT NULL,
                owner_url TEXT,
                created_at TEXT,
                updated_at TEXT,
                pushed_at TEXT,
                html_url TEXT,
                github_url TEXT,
                issues_url TEXT,
                primary_language TEXT,
                languages TEXT,
                source TEXT DEFAULT 'github_trending',
                trending_date TEXT,
                raw_metadata TEXT,
                created_at_ts TEXT NOT NULL,
                UNIQUE(full_name, source)
            )
        """)

        # 索引
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repositories(full_name)",
            "CREATE INDEX IF NOT EXISTS idx_repos_stars ON repositories(stars)",
            "CREATE INDEX IF NOT EXISTS idx_repos_language ON repositories(language)",
            "CREATE INDEX IF NOT EXISTS idx_repos_trending_date ON repositories(trending_date)",
        ]:
            try:
                cursor.execute(idx_sql)
            except sqlite3.OperationalError:
                pass

        conn.commit()
        print("✅ repositories 表创建/检查完成")

    except Exception as e:
        print(f"❌ repositories 表迁移失败: {e}")
        conn.rollback()
    finally:
        conn.close()


def run_migrations():
    """运行所有迁移"""
    print("=" * 60)
    print("🚀 开始数据库迁移...")
    print("=" * 60)

    migrate_papers_table()
    migrate_repositories_table()

    print("=" * 60)
    print("✅ 数据库迁移完成!")
    print("=" * 60)


if __name__ == "__main__":
    run_migrations()
