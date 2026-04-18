# -*- coding: utf-8 -*-
"""
情报筛选与权重排序器 (intelligence_selector) V4.2
从数据库拉取事件 → 综合评分 → P0/P1/P2 截断 → 输出精简 JSON

V4.2 改动：
- 综合评分：将 risk_level、sentiment、来源权重、关键词、模型发布 全部纳入同一评分
- 不再依赖 LIMIT 硬截断，而是对全部事件评分后排序截断
- 确保高价值信息不因时间窗口边界被遗漏
"""

import os
import re
import json
import psycopg2

PG_CONFIG = {
    "host": "172.20.0.4",
    "port": 5432,
    "user": "postgres",
    "password": "difyai123456",
    "database": "ai_tracker",
}
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

try:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from collector import _BLOCK_KW, _P0_KW, _P1_KW, _P2_KW, _DEEP_TECH_KW, _AI_KW, _DATA_KW
except ImportError:
    _BLOCK_KW = []
    _P0_KW = []
    _P1_KW = []
    _P2_KW = []
    _DEEP_TECH_KW = []
    _AI_KW = []
    _DATA_KW = []

# ── V4.1 来源权重 ─────────────────────────────────────────────────────────────
_SOURCE_WEIGHTS = {
    "openai.com/blog": 5, "anthropic.com/news": 5, "anthropic.com/blog": 5,
    "deepmind.google": 5, "mistral.ai/news": 5, "mistral.ai/blog": 5,
    "ai.meta.com/blog": 5, "blog.google/technology/ai": 5, "blogs.nvidia.com": 5,
    "qwenlm.github.io/blog": 5, "deepseek.com": 5, "modelscope.cn": 5,
    "zhipuai.cn": 5, "wenxin.baidu.com": 5, "xinghuo.xfyun.cn": 5,
    "moonshot.cn": 5, "siliconflow.cn": 5, "bilong.cn": 5,
    "langchain.dev/blog": 4, "llamaindex.ai/blog": 4, "docs.crewai.com": 4,
    "microsoft.github.io/autogen": 4, "docs.dify.ai": 4, "coze.cn/docs": 4,
    "coze.com/docs": 4, "vllm.ai/blog": 3, "modal.com/blog": 3,
    "wandb.ai/blog": 3, "cohere.com/blog": 3, "stability.ai/news": 3,
    "lancedb.github.io": 3, "clickhouse.com/blog": 3, "databricks.com/blog": 3,
    "importai.substack.com": 3, "latent.space": 3, "tldr.tech": 3,
    "bensbites.beehiiv.com": 3, "drfeeds.com/thebatch": 3,
    "stratechery.com": 3, "pragmaticengineer.com": 3,
    "arxiv.org": -3,
    "ithome.com": 0, "36kr.com": 0, "tmtpost.com": 0,
    "woshipm.com": 0, "aibase.com": 0,
}

_TECH_NEWSLETTER_DOMAINS = {
    "importai.substack.com", "latent.space", "tldr.tech",
    "bensbites.beehiiv.com", "drfeeds.com/thebatch",
}

# ── V4.1 模型发布正则 ─────────────────────────────────────────────────────────
_MODEL_RELEASE_PATTERNS = [
    re.compile(r'\b(GPT|Claude|Gemini|Llama|Mistral|Grok|Arctic)\s*-?\s*\d', re.I),
    re.compile(r'\b(Qwen|DeepSeek|Kimi|GLM|ERNIE|星火|通义千问|文心一言|豆包|百川|MiniCPM|Yi)\s*-?\s*\d', re.I),
    re.compile(r'\b(release|launch|发布|开源|open[- ]?source|新版|新版本|正式上线)\b', re.I),
    re.compile(r'\b(v\d+\.\d+|version\s*\d+)\b', re.I),
]

def _get_source_weight(source_url: str) -> int:
    if not source_url:
        return 0
    url_lower = source_url.lower()
    for domain, weight in _SOURCE_WEIGHTS.items():
        if domain in url_lower:
            return weight
    return 0

def _is_model_release(title: str, summary: str) -> bool:
    text = title + " " + summary
    return any(p.search(text) for p in _MODEL_RELEASE_PATTERNS)

def _is_paper_source(source_url: str) -> bool:
    return "arxiv.org" in (source_url or "").lower()

def _is_suspicious_future_date(pub_date_str: str) -> bool:
    if not pub_date_str:
        return False
    try:
        pub_date = datetime.fromisoformat(str(pub_date_str).replace(' ', 'T'))
        now = datetime.now(timezone.utc)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        return pub_date > now + timedelta(days=30)
    except Exception:
        return False

# ── V4.2 综合评分函数 ─────────────────────────────────────────────────────────
def _score_event_comprehensive(
    title: str,
    summary: str,
    source_url: str,
    risk_level: str,
    sentiment: str,
) -> tuple:
    """
    V4.2 综合评分：所有评分信号加权求和，输出 (priority, score).

    评分维度：
    1. 关键词命中（与V4.1相同）
    2. 来源权重（V4.1，arxiv -3）
    3. 模型发布（V4.1，+2）
    4. risk_level（V4.2新增）：高危/中风险/低风险/无风险 → +3/+1/+0/+0
    5. sentiment（V4.2新增）：利空 → +2，利好 → +1
    """
    text = (title + " " + (summary or "")).lower()
    url_lower = (source_url or "").lower()

    # Blocklist
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0

    # ── 维度1: 关键词评分 ────────────────────────────────────────────
    base_score = 0
    base_score += sum(1 for kw in _P0_KW if kw.lower() in text)
    deep_tech_hits = sum(1 for kw in _DEEP_TECH_KW if kw.lower() in text)
    base_score += deep_tech_hits
    if deep_tech_hits >= 2:
        base_score += 2

    has_ai = any(kw.lower() in text for kw in _AI_KW)
    has_data = any(kw.lower() in text for kw in _DATA_KW)
    if has_ai and has_data:
        base_score += 3
    if any(kw.lower() in text for kw in {"Agent", "agent", "智能体", "自主", "automation"}) and \
       any(kw.lower() in text for kw in {"知识库", "数据库", "RAG", "检索", "memory"}):
        base_score += 2

    # ── 维度2: 来源权重 ──────────────────────────────────────────────
    source_weight = _get_source_weight(source_url)
    base_score += source_weight

    if any(d in url_lower for d in _TECH_NEWSLETTER_DOMAINS):
        base_score += 3

    # ── 维度3: 模型发布 ──────────────────────────────────────────────
    if _is_model_release(title, summary or ""):
        base_score += 2

    # ── 维度4: risk_level（V4.2核心新增）─────────────────────────────
    # 高危事件 +3，中风险 +1（负面风险本身是重要信号）
    risk_bonus = 0
    if risk_level == "高危":
        risk_bonus = 3
    elif risk_level == "中风险":
        risk_bonus = 1

    # ── 维度5: sentiment（V4.2核心新增）───────────────────────────────
    # 利空 +2（负面信号需要被重视），利好 +1
    sentiment_bonus = 0
    if sentiment == "利空":
        sentiment_bonus = 2
    elif sentiment == "利好":
        sentiment_bonus = 1

    total_score = base_score + risk_bonus + sentiment_bonus

    # ── 优先级判定 ────────────────────────────────────────────────────
    # 高危利空事件直接 P0
    if risk_level == "高危" and sentiment == "利空":
        return "P0", total_score + 5  # 额外加权

    if total_score >= 2:
        return "P0", total_score
    elif total_score >= 1:
        return "P1", total_score
    elif has_ai:
        return "P1", 1
    else:
        return "P2", 0


def select_and_rank_events(days: int = 1, max_events: int = 300) -> dict:
    """
    主函数：从 PostgreSQL 拉取事件，综合评分 + 截断，返回精简列表。

    V4.2 评分规则（综合评分制）：
    - 综合分 = 关键词分(0-15) + 来源权重(-3~+5) + 模型发布(+2) + risk_level(+0~+3) + sentiment(+0~+2)
    - P0：综合分 ≥ 2，最多 15 条，其中 arXiv 论文最多 1 篇
    - P1：综合分 = 1，最多 5 条
    - P2：综合分 = 0 或无AI关键词，最多 20 条
    - 可疑未来日期（>30天）：直接降入 P2
    """
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
    except Exception as e:
        import logging
        logging.warning(f"[Selector] PostgreSQL connection failed: {e}, falling back to empty")
        return {"p0": [], "p1": [], "p2_brief": [], "total_scored": 0}

    time_threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    # V4.2: 查询全部事件，不做 LIMIT 截断
    cursor.execute("""
        SELECT id, title, summary, source_url, published_date, risk_level, sentiment
        FROM events
        WHERE published_date >= %s
          AND published_date <= %s
          AND published_date >= '2019-01-01'
        ORDER BY published_date DESC
    """, (time_threshold, time_max))

    rows = cursor.fetchall()
    conn.close()

    p0_events = []
    p1_events = []
    p2_events = []

    for row in rows:
        event_id, title, summary, source_url, pub_date, risk, sentiment = row
        priority, score = _score_event_comprehensive(
            title, summary or "", source_url or "", risk, sentiment
        )

        if priority == "BLOCK":
            continue

        # 可疑未来日期降级
        is_future = _is_suspicious_future_date(pub_date)
        if is_future:
            priority = "P2"
            score = -10

        event_dict = {
            "id": event_id,
            "title": title,
            "summary": summary,
            "source_url": source_url,
            "published_date": pub_date,
            "risk_level": risk,
            "sentiment": sentiment,
            "_priority": priority,
            "_score": score,
            "_future_date": is_future,
        }

        if priority == "P0":
            p0_events.append(event_dict)
        elif priority == "P1":
            p1_events.append(event_dict)
        else:
            p2_events.append(event_dict)

    # ── V4.2 综合分数排序 ────────────────────────────────────────────
    p0_events.sort(key=lambda x: x["_score"], reverse=True)
    p1_events.sort(key=lambda x: x["_score"], reverse=True)
    p2_events.sort(key=lambda x: x["_score"], reverse=True)

    # ── V4.2 论文截断 ────────────────────────────────────────────────
    p0_papers = [e for e in p0_events if _is_paper_source(e.get("source_url", "")) and not e.get("_future_date")]
    p0_industry = [e for e in p0_events if not _is_paper_source(e.get("source_url", "")) and not e.get("_future_date")]
    p0_future = [e for e in p0_events if e.get("_future_date")]

    papers_to_promote = p0_papers[:1]
    papers_to_demote = p0_papers[1:]
    p0_industry = p0_industry[:12]
    p0_events = p0_industry + papers_to_promote
    p0_events = p0_events[:15]

    p1_events = (papers_to_demote + p1_events)[:5]
    p2_events = p2_events + p0_future
    p2_events = p2_events[:20]

    p2_brief = [e for e in p2_events if e.get("_score", 0) == 0]

    return {
        "p0": p0_events,
        "p1": p1_events,
        "p2_brief": p2_brief,
        "total_scored": len(rows),
    }
