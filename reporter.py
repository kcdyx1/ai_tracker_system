# -*- coding: utf-8 -*-
"""
Reporter v5.1 - Pipeline 架构战略简报生成引擎
Filter → Plugin → Synthesizer → Distributors

数据清洗(intelligence_selector) → 论文解读(paper_highlight) →
LLM生成(style_prompt) → 飞书推送(feishu) + 微信草稿箱(wechat)
"""

import os
import sys
import json
import sqlite3
import requests
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# 敏感信息过滤
_SENSITIVE_KEYS = {
    "api_key", "secret", "token", "password", "auth",
    "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "TAVILY_API_KEY",
    "FEISHU_WEBHOOK_URL", "WECHAT_APPID", "WECHAT_APPSECRET",
}

def _mask_sensitive(text: str) -> str:
    import re
    result = text
    for key in _SENSITIVE_KEYS:
        pattern = rf'({re.escape(key)}["\s:=]+)[^&\s"\'}}]+'
        result = re.sub(pattern, r'\1***(已隐藏)', result)
    return result

_original_print = print
def log(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_args = tuple(_mask_sensitive(str(a)) if isinstance(a, str) else a for a in args)
    _original_print(f"[{timestamp}]", *safe_args, **kwargs)
    sys.stdout.flush()

# ── 环境变量 ──────────────────────────────────────────────────────────────
load_dotenv()
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")

# ── LLM 客户端 ────────────────────────────────────────────────────────────
def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("未配置 ANTHROPIC_API_KEY 或 MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
        timeout=120.0,
    )


# ── Pipeline Stage 1: Filter ────────────────────────────────────────────────
def _run_filter(days: int) -> dict:
    """数据清洗与过滤：P0/P1/P2 筛选 + 硬性截断"""
    try:
        from intelligence_selector import select_and_rank_events
        result = select_and_rank_events(days=days, max_events=50)
        log(f"[Filter] P0={len(result['p0'])} | P1={len(result['p1'])} | P2_brief={len(result['p2_brief'])}")
        return result
    except Exception as e:
        log(f"[Filter] 失败，使用兜底逻辑: {e}")
        return {"p0": [], "p1": [], "p2_brief": [], "days": days}


# ── Pipeline Stage 2: Plugin ────────────────────────────────────────────────
def _run_paper_plugin(days: int) -> str:
    """外围情报：arXiv 论文解读"""
    try:
        from paper_highlight import get_paper_highlight
        result = get_paper_highlight(days=days)
        if result:
            log(f"[Paper] 获取成功")
        else:
            log(f"[Paper] 无相关论文，跳过")
        return result or ""
    except Exception as e:
        log(f"[Paper] 失败: {e}")
        return ""


# ── 历史召回：Entity History ──────────────────────────────────────────────
def _extract_top_entities(filtered_data: dict, top_n: int = 3) -> list[dict]:
    """
    从 P0 事件中按关键词命中权重提取 Top N 实体名称列表。
    返回 [{"name": "实体名", "title": "相关事件标题"}, ...]
    """
    import re
    p0 = filtered_data.get("p0", [])
    # 提取实体的启发式规则：标题中的公司/组织名（连续2字以上大写词）
    # 简化处理：直接用原始标题作为实体关键词
    entities = []
    for e in p0[:top_n]:
        title = e.get("title", "")
        # 取标题前8个字作为实体标识
        name = title[:8].strip()
        if name:
            entities.append({"name": name, "title": title})
    return entities


def _retrieve_entity_history(entity_name: str, days: int = 90) -> str:
    """
    查询某实体近 N 天的相关事件摘要。
    返回格式化的历史轨迹字符串，如无记录返回空字符串。
    """
    db_path = os.path.join(os.path.dirname(__file__), "ai_tracker.db")
    if not os.path.exists(db_path):
        return ""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    time_threshold = (datetime.now() - timedelta(days=days)).isoformat()
    cursor.execute("""
        SELECT title, published_date
        FROM events
        WHERE published_date >= ?
          AND (title LIKE ? OR summary LIKE ?)
        ORDER BY published_date DESC
        LIMIT 5
    """, (time_threshold, f"%{entity_name[:4]}%", f"%{entity_name[:4]}%"))
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return f"- {entity_name}：近{days}天无重大动作记录"
    summaries = [f"{r[1][:10]}：{r[0][:30]}" for r in rows[:3]]
    return f"- {entity_name}：{'；'.join(summaries)}"


def _build_history_context(filtered_data: dict, top_n: int = 3) -> str:
    """构建历史轨迹参考上下文"""
    entities = _extract_top_entities(filtered_data, top_n)
    if not entities:
        return "（无实体历史轨迹数据）"
    parts = [_retrieve_entity_history(e["name"]) for e in entities]
    valid_parts = [p for p in parts if p and "无重大动作" not in p]
    if not valid_parts:
        return "（近3个月无重大动作记录）"
    return "\n".join(valid_parts)
def _build_context(filtered_data: dict, paper_highlight: str, report_type: str) -> str:
    """构建 LLM 上下文字符串"""
    lines = []

    # P0 事件（全部）
    p0 = filtered_data.get("p0", [])
    p1 = filtered_data.get("p1", [])
    p2_brief = filtered_data.get("p2_brief", [])

    for i, e in enumerate(p0, 1):
        lines.append(f"[P0-{i}] {e['title']}")
        if e.get("summary"):
            lines.append(f"  摘要: {e['summary'][:200]}")
        if e.get("source_url"):
            lines.append(f"  来源: {e['source_url']}")
        lines.append("")

    # P1 事件（Top3）
    for i, e in enumerate(p1, 1):
        lines.append(f"[P1-{i}] {e['title']}")
        if e.get("summary"):
            lines.append(f"  摘要: {e['summary'][:200]}")
        if e.get("source_url"):
            lines.append(f"  来源: {e['source_url']}")
        lines.append("")

    # P2 附录（不展开）
    if p2_brief:
        lines.append("【附录：其他值得关注】")
        for e in p2_brief:
            lines.append(f"  - {e['title']} ({e['published_date'][:10]})")

    context = "\n".join(lines)
    return context


def _run_synthesizer(filtered_data: dict, paper_highlight: str,
                      report_type: str, report_title: str) -> str:
    """战略脑图合成：调用 LLM 生成报告"""
    from style_prompt import REPORTER_SYSTEM_PROMPT

    context = _build_context(filtered_data, paper_highlight, report_type)
    history_context = _build_history_context(filtered_data, top_n=3)
    system_prompt = REPORTER_SYSTEM_PROMPT.format(report_title=report_title)

    user_prompt = f"""请分析以下情报，撰写{report_title}，严格遵循系统提示词的语言风格和排版规范。
【重要】请严格按"第一步通读→第二步全局推演→第三步展开"的顺序执行。

【历史轨迹参考】（分析战略判词时必须结合此信息，判断是延续还是转向）
{history_context}

【情报内容】
{context}

【今日论文】（如无相关内容可跳过）
{paper_highlight}
"""

    log(f"[Synthesizer] 正在呼叫 MiniMax-M2.7-highspeed...")

    try:
        client = _get_anthropic_client()
        message = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        )

        final_text = ""
        log("-" * 50)
        for block in message.content:
            if block.type == "thinking":
                log(f"[思考] {block.thinking[:100]}...")
            elif block.type == "text":
                final_text += block.text
                log(f"[生成] 文本块完成")
        log("-" * 50)
        return final_text

    except Exception as e:
        log(f"[Synthesizer] LLM 调用失败: {e}")
        return None


# ── Pipeline Stage 4: Distributors ─────────────────────────────────────────
def send_feishu_card(markdown_content: str, title_text: str):
    """飞书分发"""
    if not FEISHU_WEBHOOK_URL:
        log("[Feishu] 未配置 FEISHU_WEBHOOK_URL，跳过")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "indigo",
                "title": {"content": f"⚡️ 产业追踪雷达 | {title_text}", "tag": "plain_text"},
            },
            "elements": [
                {"tag": "markdown", "content": markdown_content},
                {"tag": "hr"},
                {"tag": "note", "elements": [
                    {"tag": "plain_text", "content": f"🤖 MiniMax-M2.7-highspeed 战略参谋驱动 | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
                ]},
            ],
        },
    }

    log(f"[Feishu] 正在推送【{title_text}】...")
    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=payload, timeout=15)
        resp.raise_for_status()
        log(f"[Feishu] 推送成功: {resp.json().get('msg')}")
    except Exception as e:
        log(f"[Feishu] 推送失败: {e}")


def send_wechat_draft(title: str, author: str, markdown_content: str):
    """微信草稿箱分发"""
    try:
        from wechat_draft_sender import send_to_draft
        import os
        cover_path = os.path.join(os.path.dirname(__file__), "data", "wechat_cover.png")
        log(f"[WeChat] 正在写入草稿箱【{title}】...")
        result = send_to_draft(title=title, author=author, markdown_content=markdown_content, cover_image_path=cover_path)
        log(f"[WeChat] 草稿创建成功: {result}")
    except ValueError as e:
        log(f"[WeChat] 跳过（无封面图）: {e}")
    except Exception as e:
        log(f"[WeChat] 草稿创建失败: {e}")


# ── 主入口 ─────────────────────────────────────────────────────────────────
REPORT_CONFIG = {
    "daily":   {"days": 1,  "title": "每日战略简报",   "max_events": 50},
    "weekly":  {"days": 7,  "title": "每周深度内参",   "max_events": 80},
    "monthly": {"days": 30, "title": "月度产业观察",   "max_events": 150},
}


def run_report(report_type: str = "daily", author: str = "kangchen") -> bool:
    """
    执行完整 Pipeline：
    Filter → Paper Plugin → Synthesizer → Feishu + WeChat
    """
    config = REPORT_CONFIG.get(report_type, REPORT_CONFIG["daily"])
    days = config["days"]
    title = config["title"]
    max_events = config["max_events"]

    log(f"=== [{title}] Pipeline 启动 (days={days}) ===")

    # Stage 1: Filter
    filtered = _run_filter(days)
    if not filtered["p0"] and not filtered["p1"]:
        log(f"[{title}] P0+P1 均为空，跳过本次报告")
        return False

    # Stage 2: Paper
    paper = _run_paper_plugin(days)

    # Stage 3: Synthesizer
    report_content = _run_synthesizer(filtered, paper, report_type, title)
    if not report_content:
        log(f"[{title}] 报告生成失败，熔断不推送")
        return False

    # Stage 4: Distribute（飞书 + 微信完全独立，互不阻塞）
    # 飞书推送
    try:
        send_feishu_card(report_content, title)
    except Exception as e:
        log(f"[{title}] 飞书推送异常: {e}")

    # 微信草稿箱推送（所有报告类型均尝试）
    try:
        send_wechat_draft(f"【{title}】{datetime.now().strftime('%Y-%m-%d')}", author, report_content)
    except Exception as e:
        log(f"[{title}] 微信草稿箱推送异常: {e}")

    log(f"=== [{title}] Pipeline 完成 ===")
    return True


if __name__ == "__main__":
    report_type = sys.argv[1].lower() if len(sys.argv) > 1 else "daily"
    run_report(report_type)
