# -*- coding: utf-8 -*-
"""
情报筛选与权重排序器 (intelligence_selector) V5.0
严格按照产业优先级评分，确保大模型/Agent/平台/投资/收购等核心内容不遗漏

V5.0 评分维度（按优先级排序）：
  TIER 1（最重要）: 新大模型发布 +5, 新Agent框架 +4, 新技术产品 +4, 新数据平台 +3
  TIER 2（重要）  : 投资/收购 +5, 高管变动 +3, 新产品发布 +4
  TIER 3（加分）  : 官方博客 +3, 技术媒体 +2, arXiv -3, 高危风险 +3
  截断规则        : P0上限20条（保证核心信息不遗漏），P1上限10条，P2上限30条
"""

import os
import re
import json
import psycopg2

PG_CONFIG = {
    "host": os.environ.get("AI_TRACKER_PG_HOST", "172.20.0.9"),
    "port": 5432,
    "user": "postgres",
    "password": "difyai123456",
    "database": "ai_tracker",
}
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

try:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from collector import _BLOCK_KW
except ImportError:
    _BLOCK_KW = []

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: 新大模型发布（最高优先级）
# ─────────────────────────────────────────────────────────────────────────────
_MODEL_MAJOR_PATTERNS = [
    # 国外大模型
    re.compile(r'\b(GPT[-\s]?\d[\.\d]*|Claude[-\s]?\d[\.\d]*|Gemini[-\s]?\d[\.\d]*)\b', re.I),
    re.compile(r'\b(Llama\s*\d[\.\d]*|Mistral\s*\d[\.\d]*|Grok\s*\d[\.\d]*|Arctic\s*\w+)\b', re.I),
    re.compile(r'\b(Phi[-\s]?\d[\.\d]*|DaLL[\s-]?E|Stable\s*Diffusion|Flux\s*\w+)\b', re.I),
    re.compile(r'\b(Sora[-\s]?\d?|Runway\s*\w+|Veo\s*\d?|Luma\s*\w+|Kling\s*\w+)\b', re.I),
    # 国内大模型
    re.compile(r'\b(Qwen[\s/-]?\d[\.\d]*|DeepSeek[\s/-]?\w+|Kimi[\s/-]?\w+)\b', re.I),
    re.compile(r'\b(GLM[\s/-]?\d[\.\d]*|ERNIE[\s/-]?\d[\.\d]*|Yi[\s/-]?\w+)\b', re.I),
    re.compile(r'\b(通义千问|文心一言|豆包|百川|星火|混元)\s*\w*', re.I),
    re.compile(r'\b(MiniCPM|MiniMax|Abab|Seqke|01\s*AI|零一|万物)\b', re.I),
    # 新模型发布关键词
    re.compile(r'\b(发布|开源|launch|release|正式上线|v\d+[\.\d]+)\s*(模型|model|llm|assistant)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: 新Agent框架/平台
# ─────────────────────────────────────────────────────────────────────────────
_AGENT_FRAMEWORK_PATTERNS = [
    re.compile(r'\b(LangChain|LlamaIndex|CrewAI|AutoGen|Dify|Coze|Mastra|Besen)\b', re.I),
    re.compile(r'\b(OpenAI\s*Assistants|OpenAI\s*Agents|GPT[\s-]?Agent|Claude\s*Agent)\b', re.I),
    re.compile(r'\b(Agent\s*Framework|Agent\s*SDK|Multi[\s-]?Agent|Agentic\s*RAG)\b', re.I),
    re.compile(r'\b(MCP[\s-]?Server|MCP[\s-]?Protocol|Model\s*Context\s*Protocol)\b', re.I),
    re.compile(r'\b( CrewAI|Autogen|Goverse|Cognify|ShellAgent)\b', re.I),
    # 国内Agent平台
    re.compile(r'\b(Dify|Coze|扣子|钉钉\s*AI|飞书\s*AI|百度\s*Agent|通义百宝)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: 新技术产品/数据平台/Infra
# ─────────────────────────────────────────────────────────────────────────────
_NEW_PRODUCT_PATTERNS = [
    re.compile(r'\b(Vector\s*DB|Vector\s*Database|向量数据库)\b', re.I),
    re.compile(r'\b(Chroma|Pinecone|Weaviate|Qdrant|Milvus|MongoDB\s*Vector)\b', re.I),
    re.compile(r'\b(LLM\s*Ops|MLOps|RAG\s*Framework|RAG\s*System)\b', re.I),
    re.compile(r'\b(vLLM|Ollama|TGI|Text[\s-]?Generation[\s-]?Inference)\b', re.I),
    re.compile(r'\b(Hugging\s*Face\s*Endpoints|Replicate|groq|mistral\.(ai/chat))\b', re.I),
    re.compile(r'\b(Data\s*Platform|数据平台|分析平台|BI\s*Platform)\b', re.I),
    re.compile(r'\b(AI\s*Search|Search\s*Engine|Search\s*Platform|搜索平台)\b', re.I),
    re.compile(r'\b(Benchmark\s*发布|Benchmark|评测基准|评估基准)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: 投资/收购/高管变动
# ─────────────────────────────────────────────────────────────────────────────
_INVESTMENT_ACQ_PATTERNS = [
    re.compile(r'\b(融资|投资|inves?t?|funding|raise[d]?|series\s+[A-Z]|A轮|B轮|C轮)\b', re.I),
    re.compile(r'\b(收购|acqui[r]?|merger|并购|买|战略投资)\b', re.I),
    re.compile(r'\b(估值|valuation|亿美元|\$[\d\.]+[MB])\b', re.I),
]

_MGMT_CHANGE_PATTERNS = [
    re.compile(r'\b(任命|聘用|hire|appoint|CEO|CTO|CFO|COO|总裁|总经理|副总裁)\b', re.I),
    re.compile(r'\b(离职|leave|exit|resign|quit|joined?\s+(Google|Microsoft|OpenAI|Anthropic|Meta))\b', re.I),
    re.compile(r'\b(创始人|founder|co[\s-]?founder|CEO\s+离职|核心团队变动)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: 新产品发布（非模型）
# ─────────────────────────────────────────────────────────────────────────────
_NEW_LAUNCH_PATTERNS = [
    re.compile(r'\b(发布|launch|release|推出|上线|新版|new\s+product)\b', re.I),
    re.compile(r'\b(正式开放|public[\s-]?beta|open[\s-]?beta|GA|general\s*availability)\b', re.I),
    re.compile(r'\b(API\s*发布|API\s*launch|SDK\s*发布|platform\s*launch)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# 来源权重
# ─────────────────────────────────────────────────────────────────────────────
_SOURCE_WEIGHTS = {
    # 官方博客 - 最高权重
    "openai.com/blog": 5, "openai.com/research": 5,
    "anthropic.com/news": 5, "anthropic.com/blog": 5,
    "deepmind.google": 5, "ai.meta.com/blog": 5,
    "blog.google/technology/ai": 5, "blogs.nvidia.com": 5,
    "mistral.ai/news": 5, "mistral.ai/blog": 5,
    # 国内模型官方
    "qwenlm.github.io/blog": 5, "deepseek.com": 5,
    "modelscope.cn": 5, "zhipuai.cn": 5,
    "wenxin.baidu.com": 5, "xinghuo.xfyun.cn": 5,
    "moonshot.cn": 5, "siliconflow.cn": 5, "bilong.cn": 5,
    # Agent框架官方
    "langchain.dev/blog": 4, "llamaindex.ai/blog": 4,
    "docs.crewai.com": 4, "microsoft.github.io/autogen": 4,
    "docs.dify.ai": 4, "coze.cn/docs": 4, "coze.com/docs": 4,
    # Infra/数据平台
    "vllm.ai/blog": 3, "modal.com/blog": 3,
    "wandb.ai/blog": 3, "cohere.com/blog": 3,
    "stability.ai/news": 3, "lancedb.github.io": 3,
    "clickhouse.com/blog": 3, "databricks.com/blog": 3,
    "pinecone.io/blog": 3, "qdrant.io/blog": 3,
    # 优质newsletter
    "importai.substack.com": 3, "latent.space": 3,
    "tldr.tech": 3, "bensbites.beehiiv.com": 3,
    "drfeeds.com/thebatch": 3, "stratechery.com": 3,
    # arXiv - 降权
    "arxiv.org": -3,
}

def _get_source_weight(url: str) -> int:
    if not url:
        return 0
    url_lower = url.lower()
    for domain, weight in _SOURCE_WEIGHTS.items():
        if domain in url_lower:
            return weight
    return 0

def _is_paper_source(url: str) -> bool:
    return "arxiv.org" in (url or "").lower()

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

# ─────────────────────────────────────────────────────────────────────────────
# V5.0 综合评分
# ─────────────────────────────────────────────────────────────────────────────
def _score_event_v5(
    title: str,
    summary: str,
    source_url: str,
    risk_level: str,
    sentiment: str,
) -> tuple[str, int]:
    """
    V5.0 综合评分，严格按产业优先级：
    TIER 1（最重要）: 新大模型发布 +5, 新Agent框架 +4, 新技术产品 +3
    TIER 2（重要）  : 投资/收购 +5, 高管变动 +3, 大厂新品 +4
    TIER 3（来源）  : 官方博客 +3, 有URL +2, arXiv -3
    TIER 4（风险）  : 高危 +3, 中风险 +1; 利空 +2, 利好 +1

    P0: 综合分 >= 3
    P1: 综合分 1-2
    P2: 其他
    """
    text = (title + " " + (summary or "")).lower()
    url_lower = (source_url or "").lower()
    is_paper = _is_paper_source(source_url)

    # Blocklist
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0

    score = 0

    # ── TIER 1: 新大模型发布（最重要）────────────────────────────────
    for p in _MODEL_MAJOR_PATTERNS:
        if p.search(title) or p.search(summary[:200] if summary else ""):
            score += 5
            break

    # ── TIER 1: 新Agent框架 ─────────────────────────────────────────
    if score == 0:  # only if not already scored as model
        for p in _AGENT_FRAMEWORK_PATTERNS:
            if p.search(title) or p.search(summary[:200] if summary else ""):
                score += 4
                break

    # ── TIER 1: 新技术产品/数据平台 ────────────────────────────────
    if score == 0:
        for p in _NEW_PRODUCT_PATTERNS:
            if p.search(title) or p.search(summary[:200] if summary else ""):
                score += 3
                break

    # ── TIER 2: 投资/收购（显式金额）───────────────────────────────
    invest_text = title.lower()
    if any(kw in invest_text for kw in ["亿美元", "亿美元", "$", "亿美元", "万亿美元", "百万美元"]):
        if any(kw in invest_text for kw in ["融资", "投资", "收购", "合作", "inves", "funding", "acqui", "acquire"]):
            score += 5
        elif any(kw in invest_text for kw in ["亿美元", "亿美元", "万亿美元"]):
            score += 3  # explicit dollar amount

    # ── TIER 2: 高管变动 ─────────────────────────────────────────
    for p in _MGMT_CHANGE_PATTERNS:
        if p.search(title):
            score += 3
            break

    # ── TIER 2: 大厂新品发布 ─────────────────────────────────────
    if score == 0:
        major_cos = ["苹果", "华为", "Google", "Microsoft", "Meta", "OpenAI", "Anthropic", "英伟达", "NVIDIA", "Apple", "Samsung", "阿里", "腾讯", "字节", "ByteDance", "小米", "vivo", "OPPO"]
        for co in major_cos:
            if co.lower() in title.lower() and any(kw in title for kw in ["发布", "推出", "上线", "launch", "release"]):
                score += 4
                break

    # ── TIER 3: 来源权重 ─────────────────────────────────────────
    source_weight = _get_source_weight(source_url)
    score += source_weight

    # 有URL来源加分（弥补URL缺失问题）
    if source_url and source_url.strip() and not is_paper:
        score += 2

    # ── TIER 4: 风险信号 ─────────────────────────────────────────
    if risk_level == "高危":
        score += 3
    elif risk_level == "中风险":
        score += 1

    if sentiment == "利空":
        score += 2
    elif sentiment == "利好":
        score += 1

    # ── 优先级判定 ─────────────────────────────────────────────────
    if score >= 3:
        return "P0", score
    elif score >= 1:
        return "P1", score
    else:
        return "P2", score

def select_and_rank_events(days: int = 1, max_events: int = 50) -> Dict[str, Any]:
    """
    V5.0 主函数：查询所有事件 → 综合评分 → 排序截断 → 返回结果

    截断规则：
    - P0: 最多 20 条（保证核心不遗漏）
    - P1: 最多 10 条
    - P2: 最多 30 条（仅保留有参考价值的事件）
    - future date (>30天): 降入 P2
    """
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
    except Exception as e:
        import logging
        logging.warning(f"[Selector] PG connection failed: {e}")
        return {"p0": [], "p1": [], "p2_brief": [], "total": 0}

    now_utc = datetime.now(timezone.utc)
    threshold = (now_utc - timedelta(days=days)).isoformat()
    max_date = (now_utc + timedelta(days=7)).isoformat()

    cursor.execute("""
        SELECT id, title, summary, source_url, published_date, risk_level, sentiment
        FROM events
        WHERE published_date >= %s
          AND published_date <= %s
          AND published_date >= '2019-01-01'
        ORDER BY published_date DESC
    """, (threshold, max_date))

    rows = cursor.fetchall()
    conn.close()

    p0_events, p1_events, p2_events = [], [], []

    for row in rows:
        event_id, title, summary, source_url, pub_date, risk, sentiment = row
        priority, score = _score_event_v5(title, summary or "", source_url or "", risk, sentiment)

        if priority == "BLOCK":
            continue

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

    # ── 排序（综合分降序）──────────────────────────────────────────
    p0_events.sort(key=lambda x: x["_score"], reverse=True)
    p1_events.sort(key=lambda x: x["_score"], reverse=True)
    p2_events.sort(key=lambda x: x["_score"], reverse=True)

    # ── 截断 ─────────────────────────────────────────────────────
    # P0: 最多20条，允许最多2篇论文
    p0_papers = [e for e in p0_events if _is_paper_source(e.get("source_url", ""))]
    p0_industry = [e for e in p0_events if not _is_paper_source(e.get("source_url", ""))]
    papers_to_p0 = p0_papers[:2]  # 最多2篇论文
    papers_to_p1 = p0_papers[2:]  # 其余论文降入P1

    p0_industry = p0_industry[:18]  # 18条产业 + 2篇论文 = 20
    final_p0 = (p0_industry + papers_to_p0)[:20]

    # P1: 最多10条
    final_p1 = (papers_to_p1 + p1_events)[:10]

    # P2 brief: 最多30条
    final_p2 = p2_events[:30]
    p2_brief = [e for e in final_p2]

    return {
        "p0": final_p0,
        "p1": final_p1,
        "p2_brief": p2_brief,
        "total": len(rows),
    }
