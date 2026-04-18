# -*- coding: utf-8 -*-
"""
情报筛选与权重排序器 (intelligence_selector) V4.1
从数据库拉取事件 → P0/P1/P2 打标 → 硬性截断 → 输出精简 JSON

V4.1 改动：
- 来源权重：模型官方博客/框架博客加权，arXiv 降权
- 模型发布正则：精确识别国内外模型发布标题
- 论文截断：每天最多 1 篇 arXiv 论文进入 P0
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

# 从 collector.py 复用关键词集合（AI + DATA + BLOCKLIST）
try:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from collector import AI_KEYWORDS, DATA_KEYWORDS, BLOCKLIST_KEYWORDS
    _AI_KW = AI_KEYWORDS
    _DATA_KW = DATA_KEYWORDS
    _BLOCK_KW = BLOCKLIST_KEYWORDS
except ImportError:
    _AI_KW = {"AI", "大模型", "LLM", "Agent", "人工智能", "深度学习", "神经网络", "GPU", "AI芯片"}
    _DATA_KW = {"数据库", "向量数据库", "数据平台", "MLOps", "ETL", "数据管道", "数据基础设施", "向量检索"}
    _BLOCK_KW = {"COVID", "新冠", "科比", "枪击", "地震", "宏观经济", "美联储", "通胀"}

# P0/P1/P2 关键词权重
_P0_KW = {
    # 技术创新突破
    "技术创新", "新模型", "新架构", "新算法", "突破", "发布", "开源", "GPT", "Claude", "Gemini",
    "Llama", "Mistral", "Grok", "ChatGPT", "Claude", "奥特曼", "AGI", "ASI",
    # 数据基础设施
    "向量数据库", "向量检索", "Embedding", "RAG", "知识库", "MLOps", "数据管道", "ETL",
    "上下文", "上下文管理", "记忆", "长期记忆", "Agent", "智能体", "工具使用", "function calling",
    "数据平台", "数据基础设施", "统一语义层", "语义层",
    # 产业与组织重大改革
    "收购", "并购", "拆分", "上市", "退市", "融资", "投资", "战略合作", "合作签约",
    "裁员", "招聘", "组织调整", "架构调整", "战略转型", " CEO", "CEO", "创始人", "高管",
    "退任", "任命", "收购", "战略投资", "独角兽",
}

# 深度技术关键词 — 命中这些关键词的文章获得额外加权
_DEEP_TECH_KW = {
    # 核心技术突破
    "context window", "上下文窗口", "百万token", "上下文长度",
    "scaling law", "scaling", "涌现", "emergent",
    "rlhf", "dpo", "ppo", "reward model", "强化学习",
    "moe", "mixture of experts", "混合专家",
    "speculative decoding", "投点解码", "kv cache",
    "quantization", "量化", "int8", "fp8", "nf4", "nf8",
    "pruning", "剪枝", "knowledge distillation", "蒸馏",
    "attention sink", "paged attention",
    "chain-of-thought", "cot", "思维链", "reasoning model",
    "inference optimization", "推理优化",
    "训练", "预训练", "pre-train", "pretrain", "post-train",
    "微调", "fine-tuning", "lora", "qlora", "adapter",
    "embedding", "向量化", "vector db", "vector search",
    "graphrag", "knowledge graph", "知识图谱",
    # Agent 核心架构
    "agent architecture", "agent system", "智能体架构", "agent 调度",
    "multi-agent", "multiagent", "多智能体", "多agent",
    "memory", "long-term memory", "长期记忆", "上下文管理",
    "tool use", "tool learning", "函数调用",
    # 推理框架
    "vllm", "text-generation-inference", "tgi", "llama.cpp", "ollama",
    "paged attention", "flash attention",
    "ray", "distributed training",
    # 重要论文/研究
    "paper", "论文", "arxiv", "icml", "neurips", "iclr", "aaai", "kdd",
}

# 高质量技术 newsletter 源 — 额外 +3 加权
_TECH_NEWSLETTER_DOMAINS = {
    "importai.substack.com",
    "drfeeds.com",           # The Batch
    "deeplearning.ai",       # Andrew Ng's newsletter
    "buttondown.email",
    "jack-clark.substack.com",
    "simonw.substack.com",
    "garymarcus.substack.com",
}

_P1_KW = {
    "商业化", "落地", "收入", "估值", "营收", "盈利", "产品发布", "发布",
    "合作", "伙伴", "生态", "市场份额", "竞争",
}

_P2_KW = {
    "政策", "监管", "法规", "标准", "评测", "治理", "白皮书", "指导意见",
}

# ── V4.1 新增：来源域名权重 ──────────────────────────────────────────────
# 正分：提升高价值产业源；负分：降低学术/噪音源
_SOURCE_WEIGHTS = {
    # ── 国外模型官方博客 — 产业核心，权重 +5 ──
    "openai.com/blog": 5,
    "anthropic.com/news": 5,
    "anthropic.com/blog": 5,
    "deepmind.google": 5,
    "mistral.ai/news": 5,
    "mistral.ai/blog": 5,
    "ai.meta.com/blog": 5,
    "blog.google/technology/ai": 5,
    "blogs.nvidia.com": 5,
    # ── 国内模型官方博客 — 产业核心，权重 +5 ──
    "qwenlm.github.io/blog": 5,     # 通义千问
    "deepseek.com": 5,               # DeepSeek
    "modelscope.cn": 5,              # 魔搭/模型市场
    "zhipuai.cn": 5,                 # 智谱 AI (GLM)
    "wenxin.baidu.com": 5,           # 百度文心
    "xinghuo.xfyun.cn": 5,           # 讯飞星火
    "moonshot.cn": 5,                 # 月之暗面 (Kimi)
    "siliconflow.cn": 5,             # 硅基流动
    "01.ai": 5,                      # 零一万物
    "bilong.cn": 5,                  # 百炼智能
    # ── Agent 框架（国内外）— 权重 +4 ──
    "blog.langchain.dev": 4,        # LangChain Blog (注意：实际域名为 blog.langchain.dev)
    "llamaindex.ai/blog": 4,
    "docs.crewai.com": 4,
    "microsoft.github.io/autogen": 4,
    "docs.dify.ai": 4,               # Dify (国内)
    "coze.cn/docs": 4,               # Coze 国内版
    "coze.com/docs": 4,              # Coze 海外版
    # ── 基础设施/数据平台（国内外），权重 +3 ──
    "vllm.ai/blog": 3,
    "modal.com/blog": 3,
    "wandb.ai/blog": 3,
    "cohere.com/blog": 3,
    "stability.ai/news": 3,
    "lancedb.github.io": 3,
    "clickhouse.com/blog": 3,
    "databricks.com/blog": 3,
    # ── 优质 newsletter，权重 +3 ──
    "importai.substack.com": 3,
    "latent.space": 3,
    "tldr.tech": 3,
    "bensbites.beehiiv.com": 3,
    "drfeeds.com/thebatch": 3,
    "stratechery.com": 3,
    "pragmaticengineer.com": 3,
    # ── arXiv — 学术来源，权重 -3（降低优先级）──
    "arxiv.org": -3,
    # ── 中文媒体 — 适度降低 ──
    "ithome.com": 0,
    "36kr.com": 0,
    "tmtpost.com": 0,
    "woshipm.com": 0,
    "aibase.com": 0,
}

# ── V4.1 新增：模型发布标题检测正则 ──────────────────────────────────────
# 检测国内外模型发布标题（GPT-4.5, Claude 4, Gemini 3, DeepSeek-V3, Qwen3 等）
_MODEL_RELEASE_PATTERNS = [
    # 国外模型（支持 GPT-4o, Claude 4, Gemini 3, Llama 4, Mistral Large 3, Grok 3 等）
    # 格式：模型名 + 可选版本号（数字或数字+字母后缀，如 V3, 4o 等）
    re.compile(r'\b(GPT|Claude|Gemini|Llama|Mistral|Grok|Arctic)\s*-?\s*[vV]?\d+(?:\.\d+)?(?:\s*[A-Za-z])?', re.I),
    # 国内模型（支持 Qwen3.5, DeepSeek-V3, Kimi-2, GLM-5, ERNIE-4, 星火4, 通义千问, 文心4 等）
    re.compile(r'\b(Qwen|DeepSeek|Kimi|GLM|ERNIE|星火|通义千问|文心一言|豆包|百川|MiniCPM|Yi)\s*-?\s*[vV]?\d+(?:\.\d+)?(?:\s*[A-Za-z])?', re.I),
    # 通用发布词汇（发布、开源、新版、正式上线、v3.0 等版本格式）
    re.compile(r'\b(发布|开源|open[- ]?source|新版|新版本|正式上线)\b', re.I),
    re.compile(r'\bv\d+\.\d+(?:\.\d+)?\b', re.I),  # v3.0, v3.5.0 等版本格式
]

def _get_source_weight(source_url: str) -> int:
    """根据 source_url 返回来源权重"""
    if not source_url:
        return 0
    url_lower = source_url.lower()
    for domain, weight in _SOURCE_WEIGHTS.items():
        if domain in url_lower:
            return weight
    return 0

def _is_model_release(title: str, summary: str) -> bool:
    """检测标题/摘要是否包含模型发布信息"""
    text = (title + " " + (summary or ""))
    return any(p.search(text) for p in _MODEL_RELEASE_PATTERNS)

def _is_paper_source(source_url: str) -> bool:
    """检测来源是否为 arXiv 论文"""
    return "arxiv.org" in (source_url or "")


def _score_event(title: str, summary: str, source_url: str) -> tuple[str, int]:
    """
    给事件打 P0/P1/P2 标签和权重分。
    返回 (priority, score)

    V4.1 改动：
    - 来源域名权重加成（_SOURCE_WEIGHTS）
    - 模型发布额外 +2 加分
    """
    text = (title + " " + (summary or "")).lower()
    url_lower = (source_url or "").lower()

    # 先检查 blocklist
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0

    # ── 来源域名权重加成（V4.1 新增）───────────────
    source_weight = _get_source_weight(source_url)

    # ── 高质量技术 newsletter 额外加权（保留旧逻辑）──
    newsletter_bonus = 0
    if any(d in url_lower for d in _TECH_NEWSLETTER_DOMAINS):
        newsletter_bonus += 3

    # ── P0 核心分计算 ────────────────────────────
    p0_score = sum(1 for kw in _P0_KW if kw.lower() in text)

    # ── 深度技术关键词额外加权 ───────────────────
    deep_tech_hits = sum(1 for kw in _DEEP_TECH_KW if kw.lower() in text)
    p0_score += deep_tech_hits  # 每个深度技术关键词 +1

    # 命中多个深度技术关键词（>=2）额外 +2
    if deep_tech_hits >= 2:
        p0_score += 2

    # ── 模型发布额外加权（V4.1 新增）──────────────
    if _is_model_release(title, summary or ""):
        p0_score += 2

    # ── 交叉领域加权 ─────────────────────────────
    has_ai = any(kw.lower() in text for kw in _AI_KW)
    has_data = any(kw.lower() in text for kw in _DATA_KW)
    if has_ai and has_data:
        p0_score += 3  # 交叉领域额外加权

    # Agent + 数据系统
    if any(kw.lower() in text for kw in {"Agent", "智能体", "agent", "上下文管理", "记忆"}):
        if any(kw.lower() in text for kw in {"数据", "数据库", "向量", "知识库", "RAG"}):
            p0_score += 2

    # ── 来源加成（合并：source_weight + newsletter_bonus）──
    p0_score += source_weight + newsletter_bonus

    if p0_score >= 2:
        return "P0", p0_score

    # ── P1 检查 ──────────────────────────────────
    p1_score = sum(1 for kw in _P1_KW if kw.lower() in text)
    p1_score += source_weight + newsletter_bonus

    if p1_score >= 1:
        return "P1", p1_score

    # ── P2 检查 ──────────────────────────────────
    p2_score = sum(1 for kw in _P2_KW if kw.lower() in text)
    if p2_score >= 1:
        return "P2", p2_score

    # 没有明显标签，但有 AI 关键词的也给 P1
    if has_ai:
        return "P1", 1

    return "P0", 1  # 默认 P0，不遗漏


def _is_valid_source(source_url: str) -> bool:
    """过滤不可靠来源"""
    if not source_url:
        return False
    source_lower = source_url.lower()
    # 过滤个人博客、不知名站点（高质量 newsletter 除外）
    block_domains = ["163.com", "sohu.com", "sina.com", "qq.com", "ifeng.com"]
    for d in block_domains:
        if d in source_lower:
            # 例外：高质量 newsletter
            if any(nl in source_lower for nl in _TECH_NEWSLETTER_DOMAINS):
                continue
            return False
    return True


def _is_suspicious_future_date(pub_date_str: str) -> bool:
    """
    检查 published_date 是否为可疑的未来日期（超过当前日期 30 天以上）。
    超过 30 天的未来日期通常是数据来源错误，应降级处理。
    返回 True 表示可疑，False 表示正常。
    """
    if not pub_date_str:
        return False
    try:
        # pub_date_str 格式: "2026-06-25 00:00:00+00:00" 或 "2026-06-25T00:00:00+00:00"
        # 用 fromisoformat 解析（Python 3.7+）
        pub_date = datetime.fromisoformat(pub_date_str.replace(' ', 'T'))
        now = datetime.now(timezone.utc)
        # 如果 pub_date 是 naive datetime，视为 UTC
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        # 超过 30 天的未来日期视为可疑
        future_threshold = now + timedelta(days=30)
        return pub_date > future_threshold
    except Exception:
        return False


def select_and_rank_events(days: int = 1, max_events: int = 50) -> List[Dict[str, Any]]:
    """
    主函数：从数据库拉取事件，P0/P1/P2 筛选 + 截断，返回精简列表。

    V4.1 截断规则：
    - P0：最多 15 条，其中 arXiv 论文最多 1 篇（其余论文降入 P1）
    - P1：保留 Top5
    - P2：仅保留一句话提及（不出现在主报告，在附录）
    - 可疑未来日期（>30天）：自动降入 P2
    """
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
    except Exception as e:
        import logging
        logging.warning(f"[Selector] PostgreSQL connection failed: {e}, falling back to empty")
        return []

    time_threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    cursor.execute("""
        SELECT id, title, summary, source_url, published_date, risk_level, sentiment
        FROM events
        WHERE published_date >= %s
          AND published_date <= %s
          AND published_date >= '2019-01-01'
        ORDER BY created_at DESC
        LIMIT 300
    """, (time_threshold, time_max, max_events))

    rows = cursor.fetchall()
    conn.close()

    p0_events = []
    p1_events = []
    p2_events = []

    for row in rows:
        event_id, title, summary, source_url, pub_date, risk, sentiment = row
        priority, score = _score_event(title, summary or "", source_url or "")

        if priority == "BLOCK":
            continue

        # ── V4.1 可疑未来日期降级 ───────────────────────────────────
        # 如果 published_date 超过当前日期 30 天以上，降为 P2
        is_future = _is_suspicious_future_date(pub_date)
        if is_future:
            priority = "P2"
            score = -10  # 极低分数，确保排在最后

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

    # 按分数排序
    p0_events.sort(key=lambda x: x["_score"], reverse=True)
    p1_events.sort(key=lambda x: x["_score"], reverse=True)

    # ── V4.1 论文截断逻辑 ───────────────────────────────────────────────
    # 从 P0 中分离 arXiv 论文和产业事件（排除可疑未来日期的论文）
    p0_papers = [e for e in p0_events if _is_paper_source(e.get("source_url", "")) and not e.get("_future_date")]
    p0_industry = [e for e in p0_events if not _is_paper_source(e.get("source_url", "")) and not e.get("_future_date")]
    p0_future = [e for e in p0_events if e.get("_future_date")]

    # 论文每天最多 1 篇进入 P0（其余降入 P1）
    papers_to_promote = p0_papers[:1]
    papers_to_demote = p0_papers[1:]

    # 产业 P0 最多 12 篇（留出空间给论文）
    p0_industry = p0_industry[:12]

    # 重组 P0 和 P1
    p0_events = p0_industry + papers_to_promote
    p0_events = p0_events[:15]  # 最终上限 15 条

    # 被降级的论文放入 P1（按分数排序后取 Top5）；可疑未来日期事件直接降入 P2
    p1_events = (papers_to_demote + p1_events)[:5]
    p2_events = p2_events + p0_future
    # ── 论文截断逻辑结束 ───────────────────────────────────────────────

    # P2 只保留摘要信息，不展开
    p2_brief = [{"title": e["title"], "published_date": e["published_date"]} for e in p2_events[:3]]

    result = {
        "p0": p0_events,
        "p1": p1_events,
        "p2_brief": p2_brief,
        "generated_at": datetime.now().isoformat(),
        "days": days,
    }

    return result


def save_temp_json(days: int = 1, max_events: int = 50, output_name: str = None) -> str:
    """
    筛选结果落盘为临时 JSON，供 reporter.py 后续读取。
    返回文件路径。
    """
    data = select_and_rank_events(days=days, max_events=max_events)
    if output_name is None:
        output_name = f"intelligence_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path = os.path.join(os.path.dirname(__file__), "data", output_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


if __name__ == "__main__":
    import pprint
    result = select_and_rank_events(days=1)
    print(f"P0: {len(result['p0'])} | P1: {len(result['p1'])} | P2_brief: {len(result['p2_brief'])}")
    pprint.pprint(result)
