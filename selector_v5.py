# -*- coding: utf-8 -*-
"""
情报筛选与权重排序器 (intelligence_selector) V5.0 → V8
严格按照产业优先级评分，确保大模型/Agent/平台/投资/收购等核心内容不遗漏

V5.0 评分维度（按优先级排序）：
  TIER 1（最重要）: 新大模型发布 +5, 新Agent框架 +4, 新技术产品 +4, 新数据平台 +3
  TIER 2（重要）  : 投资/收购 +5, 高管变动 +3, 新产品发布 +4
  TIER 3（加分）  : 官方博客 +3, 技术媒体 +2, arXiv -3, 高危风险 +3
  截断规则        : P0上限20条（保证核心信息不遗漏），P1上限10条，P2上限30条

V8 新增（实体位阶加权 + 论文防火墙）：
  - TIER_0_ENTITIES: 产业定义者，乘数 2.0x
  - TIER_1_ENTITIES: 重要参与者，乘数 1.2x
  - 论文防火墙: 非范式转移论文强制进入academic_papers池
  - 噪音惩罚: noise_level * 2.0
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
from typing import List, Dict, Any, Tuple

try:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from collector import _BLOCK_KW
except ImportError:
    _BLOCK_KW = []

# ─────────────────────────────────────────────────────────────────────────────
# V8 新增：实体位阶表
# ─────────────────────────────────────────────────────────────────────────────
# TIER_0_ENTITIES: 产业定义者，乘数 2.0x
TIER_0_ENTITIES = {
    "OpenAI", "Anthropic", "Google DeepMind", "DeepMind",
    "NVIDIA", "Meta AI", "Microsoft Research",
    "智谱AI", "智谱", "zhipuai",
    "字节跳动", "字节", "ByteDance",
    "华为", "Huawei", "阿里", "Alibaba", "百度", "Baidu", "腾讯", "Tencent",
    "DeepSeek", "深度求索", "月之暗面", "Moonshot",
    "MiniMax", "MiniMax-Team",
    "Physical Intelligence", "Figure AI", "Tesla",
}

# TIER_1_ENTITIES: 重要参与者，乘数 1.2x
TIER_1_ENTITIES = {
    "Stability AI", "Cohere", "Mistral AI", "HuggingFace", "Hugging Face",
    "LangChain", "LlamaIndex", "Dify", "Coze",
    "Runway", "Midjourney", "Scale AI",
    "智源", "硅基流动", "面壁智能", "IDEA",
    "MiniMax-", "MiniMax ",
}

def _extract_main_entity(title: str, summary: str = "") -> str:
    """从标题/摘要中提取主实体名称"""
    text = (title + " " + (summary or "")).lower()

    # 优先检查TIER_0实体
    for entity in TIER_0_ENTITIES:
        if entity.lower() in text:
            return entity

    # 然后检查TIER_1实体
    for entity in TIER_1_ENTITIES:
        if entity.lower() in text:
            return entity

    return ""

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: 新大模型发布（最高优先级）- 扩展覆盖
# ─────────────────────────────────────────────────────────────────────────────
_MODEL_MAJOR_PATTERNS = [
    # 国外大模型
    re.compile(r'\b(GPT[-\s]?\d[\.\d]*|Claude[-\s]?\d[\.\d]*|Gemini[-\s]?\d[\.\d]*)\b', re.I),
    re.compile(r'\b(Llama\s*\d[\.\d]*|Mistral\s*\d[\.\d]*|Grok\s*\d[\.\d]*|Arctic\s*\w+)\b', re.I),
    re.compile(r'\b(Phi[-\s]?\d[\.\d]*|DaLL[\s-]?E|Stable\s*Diffusion|Flux\s*\w+)\b', re.I),
    re.compile(r'\b(Sora[-\s]?\d?|Runway\s*\w+|Veo\s*\d?|Luma\s*\w+|Kling\s*\w+)\b', re.I),
    # 文生图/视频模型扩展
    re.compile(r'\b(GPT\s*Image\s*\d|Image\s*\d)\b', re.I),
    re.compile(r'\b(DALL-E\s*\d|Stable\s*Diffusion\s*\d|Flux\s*\w+|Midjourney)\b', re.I),
    re.compile(r'\b(Veo\s*\d+|Luma\s*Dream|Gen-3|Kling\s*\w+)\b', re.I),
    # 国内大模型
    re.compile(r'\b(Qwen[\s/-]?\d[\.\d]*|DeepSeek[\s/-]?\w+|Kimi[\s/-]?\w+)\b', re.I),
    re.compile(r'\b(GLM[\s/-]?\d[\.\d]*|ERNIE[\s/-]?\d[\.\d]*|Yi[\s/-]?\w+)\b', re.I),
    re.compile(r'\b(通义千问|文心一言|豆包|百川|星火|混元)\s*\w*', re.I),
    re.compile(r'\b(MiniCPM|MiniMax|Abab|Seqke|01\s*AI|零一|万物)\b', re.I),
    # 新模型发布关键词
    re.compile(r'\b(发布|开源|launch|release|正式上线|v\d+[\.\d]+)\s*(模型|model|llm|assistant)\b', re.I),
    # Claude产品线（非数字系列）
    re.compile(r'\bClaude\s*(Design|Code|Artifacts|AI)\b', re.I),
    # 国内新模型/产品
    re.compile(r'\b(AutoClaw|GLM-[CX]\d|ChatGLM\s*\d|Abab\s*\d)\b', re.I),
    # 具身智能/机器人模型
    re.compile(r'\b(π0\.7|pi0\.7|pi-zero|pi-zero\.7|ABot|VLA|具身智能)\b', re.I),
    re.compile(r'\b(Physical\s*Intelligence|Figure\s*\d|Unitree|Boston\s*Dynamics)\b', re.I),
    # 科学/垂直模型
    re.compile(r'\b(GPT-Rosalind|AlphaFold\s*\d|ESMFold|MedPaLM)\b', re.I),
    # IPO/重大资本事件
    re.compile(r'\b(群核科技|零一万物|月之暗面|智谱AI|深度求索)\s*(IPO|上市|融资)\b', re.I),
    re.compile(r'\b(人形机器人|半程马拉松)\b', re.I),
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
# TIER 1: 新技术产品/数据平台/Infra - 扩展覆盖
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
    # 具身智能/世界模型/空间智能
    re.compile(r'\b(世界模型|空间智能|导航模型|操作模型|具身)\b', re.I),
    re.compile(r'\b(ABot-World|ABot-M|ABot-N|RoboMind|π0)\b', re.I),
    # AI办公套件
    re.compile(r'\b(Skill\s*商店|GLM\s*Office|PPT\s*生成|DOCX\s*生成)\b', re.I),
    # 自进化机制
    re.compile(r'\b(自进化|记忆写入|能力进化|经验积累)\b', re.I),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: 投资/收购/高管变动
# ─────────────────────────────────────────────────────────────────────────────
_INVESTMENT_ACQ_PATTERNS = [
    re.compile(r'\b(融资|投资|inves?t?|funding|raise[d]?|series\s+[A-Z]|A轮|B轮|C轮)\b', re.I),
    re.compile(r'\b(收购|acqui[r]?|merger|并购|买|战略投资)\b', re.I),
    re.compile(r'\b(估值|valuation|亿美元|\$[\d\.]+[MB])\b', re.I),
    re.compile(r'\b(IPO|上市|登陆港股|登陆科创板|纳斯达克|NYSE)\b', re.I),
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
    "physicalintelligence.com": 5,
    "amap.com": 4,
    "autonavi.com": 4,
    "qunhe.com": 4,
    "36kr.com": 3,
    "jiqizhixin.com": 4,
    "qbitai.com": 4,
    "ithome.com": 3,
    "figure.ai": 5,
    "unitree.com": 4,
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
    TIER 2（重要）  : 投资/收购 +5, 高管变动 +3, 新产品发布 +3
    TIER 3（来源）  : 官方博客 +3, 技术媒体 +1, arXiv -3
    TIER 4（风险）  : 高危 +3, 中风险 +1; 利空 +2, 利好 +1

    P0: 综合分 >= 3
    P1: 综合分 1-2
    P2: 其他
    """
    text = (title + " " + (summary or "")).lower()
    url_lower = (source_url or "").lower()

    # Blocklist
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0

    score = 0
    bonus_tags = []

    # ── TIER 1: 新大模型发布（最重要）────────────────────────────────
    for p in _MODEL_MAJOR_PATTERNS:
        if p.search(title) or p.search(summary[:200] if summary else ""):
            score += 5
            bonus_tags.append("大模型发布")
            break

    # ── TIER 1: 新Agent框架 ───────────────────────────────────────
    for p in _AGENT_FRAMEWORK_PATTERNS:
        if p.search(title) or p.search(summary[:200] if summary else ""):
            score += 4
            bonus_tags.append("Agent框架")
            break

    # ── TIER 1: 新技术产品/数据平台 ───────────────────────────────
    for p in _NEW_PRODUCT_PATTERNS:
        if p.search(title) or p.search(summary[:200] if summary else ""):
            score += 3
            bonus_tags.append("新技术产品")
            break

    # ── TIER 2: 投资/收购 ─────────────────────────────────────────
    for p in _INVESTMENT_ACQ_PATTERNS:
        if p.search(title):
            score += 5
            bonus_tags.append("投资/收购")
            break

    # ── TIER 2: 高管变动 ─────────────────────────────────────────
    for p in _MGMT_CHANGE_PATTERNS:
        if p.search(title):
            score += 3
            bonus_tags.append("高管变动")
            break

    # ── TIER 2: 新产品发布 ───────────────────────────────────────
    for p in _NEW_LAUNCH_PATTERNS:
        if p.search(title):
            score += 3
            bonus_tags.append("新产品发布")
            break

    # ── TIER 3: 来源权重 ─────────────────────────────────────────
    source_weight = _get_source_weight(source_url)
    score += source_weight

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


def select_and_rank_events(days: int = 1) -> Dict[str, Any]:
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
        SELECT id, title, summary, source_url, published_date, risk_level, sentiment, attributes_json
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
        event_id, title, summary, source_url, pub_date, risk, sentiment, attributes_json = row
        priority, score, is_academic = _score_event_v8(
            title, summary or "", source_url or "", risk, sentiment, attributes_json, pub_date
        )

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
            "attributes_json": attributes_json,
            "_priority": priority,
            "_score": score,
            "_future_date": is_future,
            "_is_academic": is_academic,
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

    # ── V8 论文防火墙：分离学术事件和产业事件 ─────────────────────
    academic_events = []  # 所有学术事件（论文防火墙拦截）
    p0_industry = []
    p1_industry = []
    p2_industry = []

    for e in p0_events:
        if e.get("_is_academic"):
            academic_events.append(e)
        else:
            p0_industry.append(e)

    for e in p1_events:
        if e.get("_is_academic"):
            academic_events.append(e)
        else:
            p1_industry.append(e)

    for e in p2_events:
        if e.get("_is_academic"):
            academic_events.append(e)
        else:
            p2_industry.append(e)

    # ── 截断 ─────────────────────────────────────────────────────
    # P0产业: 最多20条
    final_p0 = p0_industry[:20]

    # P1产业: 最多10条
    final_p1 = p1_industry[:10]

    # P2产业: 最多30条
    final_p2 = p2_industry[:30]
    p2_brief = final_p2

    # 学术论文池：所有被论文防火墙拦截的事件 + 原始arXiv论文
    all_arxiv = [e for e in academic_events if _is_paper_source(e.get("source_url", ""))]
    all_academic = academic_events + all_arxiv

    return {
        "p0": final_p0,
        "p1": final_p1,
        "p2_brief": p2_brief,
        "academic_papers": all_academic,  # V8新增：所有学术论文
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# V8 综合评分函数
# ─────────────────────────────────────────────────────────────────────────────
def _score_event_v8(
    title: str,
    summary: str,
    source_url: str,
    risk_level: str,
    sentiment: str,
    attributes_json: str = None,
    pub_date: datetime = None,
) -> Tuple[str, int, bool]:
    """
    V8 综合评分：实体位阶加权 + 论文防火墙 + 时间衰减

    公式：
    Final_Score = ((Depth_Score * Entity_Multiplier) + Source_Weight + Sentiment_Bonus - Noise_Penalty) * Time_Decay

    其中：
    - Depth_Score = (tech_disruption_index * 1.5) + (industry_moat_impact * 1.0)
    - Entity_Multiplier = 2.0 if main_entity in TIER_0 else 1.2 if in TIER_1 else 1.0
    - Source_Weight = 官方博客 +5, arXiv -5, 优质媒体 +2
    - Sentiment_Bonus = 利好 +1, 利空 +2
    - Noise_Penalty = noise_level * 2.0

    论文隔离规则：
    - is_paradigm_shift=True AND tech_disruption_index=10 → 允许进入正文（罕见例外）
    - 否则：所有arXiv来源事件强制标记is_academic，不进入正文板块

    返回: (priority, score, is_academic)
    """
    # 解析战略审计字段（从attributes_json）
    audit = {
        "tech_disruption_index": 5,
        "industry_moat_impact": 5,
        "noise_level": 5,
        "is_paradigm_shift": False,
    }
    if attributes_json:
        try:
            audit = json.loads(attributes_json)
            # 确保默认值
            audit.setdefault("tech_disruption_index", 5)
            audit.setdefault("industry_moat_impact", 5)
            audit.setdefault("noise_level", 5)
            audit.setdefault("is_paradigm_shift", False)
        except (json.JSONDecodeError, TypeError):
            pass

    # Blocklist检查
    text = (title + " " + (summary or "")).lower()
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0, False

    # 计算Entity乘数
    entity_multiplier = 1.0
    main_entity = _extract_main_entity(title, summary)
    if main_entity in TIER_0_ENTITIES:
        entity_multiplier = 2.0
    elif main_entity in TIER_1_ENTITIES:
        entity_multiplier = 1.2

    # 计算Depth分数
    depth_score = (
        audit.get("tech_disruption_index", 5) * 1.5 +
        audit.get("industry_moat_impact", 5) * 1.0
    )

    # 论文防火墙
    is_arxiv = _is_paper_source(source_url)
    is_academic = False

    # 无来源事件：视为学术/低可信度内容，不进入正文
    if not source_url or source_url.strip() == "":
        is_academic = True
        depth_score = -20

    if is_arxiv and not is_academic:
        # 非范式转移的arXiv论文，强制进入论文池
        if not (audit.get("is_paradigm_shift") and audit.get("tech_disruption_index", 0) >= 10):
            is_academic = True
            depth_score = -20  # 强制负分，打入论文专属区

    # 噪音惩罚
    noise_penalty = audit.get("noise_level", 5) * 2.0

    # 来源权重
    source_weight = _get_source_weight(source_url)

    # 情感加分
    sentiment_bonus = 0
    if sentiment == "利好":
        sentiment_bonus = 1
    elif sentiment == "利空":
        sentiment_bonus = 2

    # 时间衰减因子：超过24小时衰减，每old一天减5%，最多衰减50%（10天前的新闻分数减半）
    time_decay = 1.0
    if pub_date:
        try:
            pub_dt = pub_date
            if hasattr(pub_dt, 'tzinfo') and pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            days_old = (now_dt - pub_dt).total_seconds() / 86400.0
            if days_old > 1:
                time_decay = max(0.5, 1.0 - ((days_old - 1) * 0.05))
        except Exception:
            pass

    # 最终分数
    final_score = (
        depth_score * entity_multiplier +
        source_weight +
        sentiment_bonus -
        noise_penalty
    ) * time_decay

    # 优先级判定
    if final_score >= 3:
        priority = "P0"
    elif final_score >= 1:
        priority = "P1"
    else:
        priority = "P2"

    return priority, int(final_score), is_academic
