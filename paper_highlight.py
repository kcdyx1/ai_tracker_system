# -*- coding: utf-8 -*-
"""
论文解读模块 (paper_highlight)
从 arXiv 官方 API 拉取最新论文 → LLM 生成 100-200 字解读
"""

import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import anthropic

# 从 style_prompt 导入论文 prompt
try:
    from style_prompt import PAPER_HIGHLIGHT_PROMPT
except ImportError:
    PAPER_HIGHLIGHT_PROMPT = """你是一位跟踪前沿AI技术的快速反应分析师。请分析以下论文，用100-200字写出简单解读。..."""

# arXiv API 搜索类别
ARXIV_CATEGORIES = ["cs.CL", "cs.AI", "cs.LG"]

# Agent + 数据系统相关关键词（优先选择）
_AGENT_DATA_KW = [
    "agent", "context", "memory", "retrieval", "rag", "knowledge",
    "tool", "planning", "reasoning", "reasoning", "workflow",
    "vector", "embedding", "database", "data system",
]


def _get_arxiv_client() -> anthropic.Anthropic:
    """获取 Anthropic 客户端"""
    import dotenv
    dotenv.load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
        timeout=120.0,
    )


def _fetch_arxiv_feed(days: int = 1, max_results: int = 30) -> list[Dict[str, Any]]:
    """
    调用 arXiv 官方 API，获取近 N 天的 CS.CL/AI/LG 论文。
    使用 OAI-PMH 兼容查询，带重试退避。
    """
    # 计算日期范围
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    base_url = "https://export.arxiv.org/api/query"
    all_entries = []

    for category in ARXIV_CATEGORIES:
        query = f"cat:{category}+AND+submittedDate:[{start_date.replace('-', '')}+TO+{end_date.replace('-', '')}]"
        params = urllib.parse.urlencode({
            "search_query": query,
            "sort_by": "submittedDate",
            "sort_order": "descending",
            "max_results": str(max_results),
        })

        url = f"{base_url}?{params}"
        backoff = 2

        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AI-Tracker/1.0"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    xml_text = response.read().decode("utf-8")
                entries = _parse_arxiv_xml(xml_text)
                all_entries.extend(entries)
                break
            except Exception as e:
                time.sleep(backoff)
                backoff *= 2
                if attempt == 2:
                    pass  # 静默失败，不阻塞主流程

    # 去重
    seen_ids = set()
    unique = []
    for e in all_entries:
        if e["id"] not in seen_ids:
            seen_ids.add(e["id"])
            unique.append(e)

    return unique


def _parse_arxiv_xml(xml_text: str) -> list[Dict[str, Any]]:
    """简单解析 arXiv Atom Feed，提取论文元数据"""
    import re
    entries = []

    # 提取 entry block
    entry_blocks = re.findall(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)
    for block in entry_blocks:
        title = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        summary = re.search(r"<summary>(.*?)</summary>", block, re.DOTALL)
        published = re.search(r"<published>(.*?)</published>", block, re.DOTALL)
        arxiv_id = re.search(r"<id>(.*?)</id>", block, re.DOTALL)
        link = re.search(r'<link[^>]+title="pdf"[^>]*href="(.*?)"', block)

        title_text = title.group(1).strip().replace("\n", " ") if title else "Unknown"
        abstract = summary.group(1).strip().replace("\n", " ")[:500] if summary else ""  # 截断摘要
        pub_date = published.group(1).strip()[:10] if published else ""
        arxiv_url = arxiv_id.group(1).strip() if arxiv_id else ""
        pdf_url = link.group(1).strip() if link else f"https://arxiv.org/abs/{arxiv_url.split('/')[-1]}"

        entries.append({
            "id": arxiv_url,
            "title": title_text,
            "abstract": abstract,
            "published_date": pub_date,
            "pdf_url": pdf_url,
        })

    return entries


def _score_paper_relevance(title: str, abstract: str) -> int:
    """评估论文与 Agent+数据系统 相关度"""
    text = (title + " " + abstract).lower()
    score = 0
    for kw in _AGENT_DATA_KW:
        if kw.lower() in text:
            score += 1
    return score


def get_paper_highlight(days: int = 1) -> Optional[str]:
    """
    主函数：获取今日论文解读。
    返回三段式 Markdown 字符串，或 None（无合适论文时）。
    """
    entries = _fetch_arxiv_feed(days=days, max_results=30)
    if not entries:
        return None

    # 按相关度排序，优先选择 Agent+数据 系统相关的论文
    for e in entries:
        e["_score"] = _score_paper_relevance(e["title"], e["abstract"])

    entries.sort(key=lambda x: x["_score"], reverse=True)

    # 取最相关的一篇
    best = entries[0]
    prompt = PAPER_HIGHLIGHT_PROMPT.format(
        title=best["title"],
        abstract=best["abstract"],
    )

    try:
        client = _get_arxiv_client()
        message = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=1024,
            system="你是一个专业的AI技术解读分析师，语言风格直接、冷峻、务实。",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )

        result_text = ""
        for block in message.content:
            if block.type == "text":
                result_text += block.text

        if result_text:
            # 追加论文链接
            result_text += f"\n> 论文来源：{best['pdf_url']}"
            return result_text

    except Exception as e:
        print(f"[paper_highlight] LLM 调用失败: {e}")

    return None


if __name__ == "__main__":
    result = get_paper_highlight(days=1)
    if result:
        print(result)
    else:
        print("无相关论文")
