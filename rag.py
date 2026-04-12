#!/usr/bin/env python3
"""
AI Tracker System - L3 战略推演引擎 (Graph-RAG)
"""

import os
import anthropic
from datetime import datetime, timezone
from database import get_smart_rag_context, get_connection
from datetime import datetime, timezone, timedelta

# ── 统一的 API 配置获取 ──────────────────────────────────────────────────────
def _get_anthropic_client():
    """获取配置好的 Anthropic 客户端"""
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("参谋部无法运转，请在 .env 中配置 MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL")
    )


def _get_today_events_context(query: str) -> str:
    time_kw = ["今天", "今日", "最近", "最新", "昨天", "本周", "近日"]
    if not any(k in query for k in time_kw):
        return ""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT title, date, summary, risk_level FROM events WHERE date >= %s::date ORDER BY date DESC LIMIT 10",
        (today,)
    )
    rows = cur.fetchall()
    label = "今日事件"
    if not rows:
        cur.execute(
            "SELECT title, date, summary, risk_level FROM events WHERE date >= %s::date ORDER BY date DESC LIMIT 10",
            (week_ago,)
        )
        rows = cur.fetchall()
        label = "近7日事件"
    conn.close()
    if not rows:
        return ""
    lines_out = ["【" + label + "】（来自情报库）"]
    for r in rows:
        risk = r["risk_level"] or ""
        icon = "\U0001f534" if risk == "P0" else ("\U0001f7e1" if risk == "P1" else "")
        date_str = str(r["date"])[:10]
        lines_out.append("  " + date_str + " " + icon + " " + r["title"] + ": " + (r["summary"] or "")[:80])
    return chr(10).join(lines_out)


def chat_with_graph(user_query: str, chat_history: list = None) -> str:
    """
    接收用户提问，提取底层 L2 证据，生成 L3 战略研判
    """
    # 1. 检测日期相关query，注入今日/近7日事件
    today_ctx = _get_today_events_context(user_query)

    # 2. 核心：从数据库抽取增强版 L2 级图谱上下文 (自带风险、情感与原文证据)
    context = get_smart_rag_context(user_query)
    if today_ctx:
        context = today_ctx + chr(10) + chr(10) + context

    # 2. 注入当前日期
    now = datetime.now(timezone.utc)
    current_date_str = now.strftime("%Y年%m月%d日 %A %H:%M:%S UTC")

    # 3. 灵魂：构建 L3 级战略推演 System Prompt
    system_prompt = f"""你现在是本情报系统的「首席战略官 (Chief Intelligence Officer)」。
你的任务是基于底层数据库检索出的【客观事实 (L2 级情报)】，为用户提供【战略推演 (L3 级研判)】。

[[SYSTEM_TIME]]

【情报雷达检索到的底层事实 (包含红绿灯标签与证据)】：
{context}

【你的核心战术准则】：
1. 洞察动机：绝不要只是复述新闻！你要像顶级投行分析师一样，分析事件背后的商业动机。
2. 风险穿透：如果检索到了 🚨 高危 或 ⚠️ 中风险 的事件，你必须在回答中强力警告。
3. 证据链闭环：当你提出一个战略观点时，必须引用检索内容里的证据。
4. 降维打击：用冷酷、极客、一针见血的军事情报风格回答。
5. 无中生有是死罪：如果情报不足，直接回答"情报雷达暂未捕获相关信号"。
6. 日期判断：如果用户问"今天是几号"或类似问题，必须使用【系统时间】中的日期回答，不得臆测。

【⚠️ 排版与视觉铁律（极其重要）】：
1. 绝对不允许使用 Markdown 表格 (Table)！前端无法渲染表格。
2. 必须使用层次分明的加粗项目符号 (Bullet points) 来替代表格。
3. 段落、不同维度的观点之间，必须严格留出空行（换行），保持视觉呼吸感。
4. 善用 Emoji 作为视觉引导（如 🏢 公司、🚀 技术、💰 资本等）。
"""

    # 3. 组装历史消息 (保留上下文对话能力)
    messages = []
    if chat_history:
        for msg in chat_history:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": msg.get("content", "")})

    messages.append({"role": "user", "content": "[系统时间: " + current_date_str + "] " + user_query})

    # 4. 调用大模型进行终极推演
    try:
        client = _get_anthropic_client()

        response = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            temperature=0.2,  # 降低温度，保持冷酷的逻辑推理，减少幻觉
            system=system_prompt,
            messages=messages
        )

        final_text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                final_text += block.text
            elif hasattr(block, "text"):
                final_text += block.text

        return final_text
    except Exception as e:
        return f"❌ 参谋部引擎发生异常: {str(e)}"

# 在 rag.py 中添加
def get_intelligence_context(query: str):
    """
    供 OpenClaw 调用：仅检索底层图谱事实，不进行 LLM 总结
    """
    from database import get_smart_rag_context, get_connection
    context = get_smart_rag_context(query)
    return context

if __name__ == "__main__":
    # 简单的本地测试
    print(chat_with_graph("总结一下目前的行业风险"))
