# -*- coding: utf-8 -*-
"""
情报筛选与权重排序器 (intelligence_selector)
从数据库拉取事件 → P0/P1/P2 打标 → 硬性截断 → 输出精简 JSON
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
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

_P1_KW = {
    "商业化", "落地", "收入", "估值", "营收", "盈利", "产品发布", "发布",
    "合作", "伙伴", "生态", "市场份额", "竞争",
}

_P2_KW = {
    "政策", "监管", "法规", "标准", "评测", "治理", "白皮书", "指导意见",
}


def _score_event(title: str, summary: str, source_url: str) -> tuple[str, int]:
    """
    给事件打 P0/P1/P2 标签和权重分。
    返回 (priority, score)
    """
    text = (title + " " + (summary or "")).lower()

    # 先检查 blocklist
    for kw in _BLOCK_KW:
        if kw.lower() in text:
            return "BLOCK", 0

    # P0 检查
    p0_score = sum(1 for kw in _P0_KW if kw.lower() in text)

    # 数据+AI 交叉加权
    has_ai = any(kw.lower() in text for kw in _AI_KW)
    has_data = any(kw.lower() in text for kw in _DATA_KW)
    if has_ai and has_data:
        p0_score += 3  # 交叉领域额外加权

    # Agent + 数据系统
    if any(kw.lower() in text for kw in {"Agent", "智能体", "agent", "上下文管理", "记忆"}):
        if any(kw.lower() in text for kw in {"数据", "数据库", "向量", "知识库", "RAG"}):
            p0_score += 2

    if p0_score >= 2:
        return "P0", p0_score

    # P1 检查
    p1_score = sum(1 for kw in _P1_KW if kw.lower() in text)
    if p1_score >= 1:
        return "P1", p1_score

    # P2 检查
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
    # 过滤个人博客、不知名站点
    block_domains = ["163.com", "sohu.com", "sina.com", "qq.com", "ifeng.com"]
    for d in block_domains:
        if d in source_lower:
            return False
    return True


def select_and_rank_events(days: int = 1, max_events: int = 50) -> List[Dict[str, Any]]:
    """
    主函数：从数据库拉取事件，P0/P1/P2 筛选 + 截断，返回精简列表。

    截断规则：
    - P0：全部保留（上限10条）
    - P1：保留 Top3
    - P2：仅保留一句话提及（不出现在主报告，在附录）
    """
    db_path = os.path.join(os.path.dirname(__file__), "ai_tracker.db")
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    time_threshold = (datetime.now() - timedelta(days=days)).isoformat()
    cursor.execute("""
        SELECT id, title, summary, source_url, published_date, risk_level, sentiment
        FROM events
        WHERE published_date >= ?
          AND published_date <= datetime('now', '+7 days')
          AND published_date >= '2019-01-01'
        ORDER BY published_date DESC
        LIMIT ?
    """, (time_threshold, max_events))

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

    # 硬性截断
    p0_events = p0_events[:10]
    p1_events = p1_events[:3]
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
