#!/usr/bin/env python3
"""
OSINT Tracker - 飞书高级战略简报推送引擎 (v4.0 视觉旗舰版)
利用飞书原生引用语法优化视觉层级，打造顶级内参质感。
"""

import os
import sys
import json
import sqlite3
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
from prompt_templates import REPORTER_SYSTEM_PROMPT

# ── 敏感信息过滤 ────────────────────────────────────────────────────────────
_SENSITIVE_KEYS = {
    "api_key", "api_key", "secret", "token", "password", "auth",
    "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "TAVILY_API_KEY",
    "FEISHU_WEBHOOK_URL"
}

def _mask_sensitive(text: str) -> str:
    """过滤日志中的敏感信息"""
    import re
    result = text
    for key in _SENSITIVE_KEYS:
        # 匹配 key=value 或 key: value 模式
        pattern = rf'({re.escape(key)}["\s:=]+)[^&\s"\'}}]+'
        result = re.sub(pattern, r'\1***(已隐藏)', result)
    return result

# 配置日志输出带时间戳
import builtins
_original_print = builtins.print

def log(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 过滤敏感信息
    safe_args = tuple(_mask_sensitive(str(arg)) if isinstance(arg, str) else arg for arg in args)
    _original_print(f"[{timestamp}]", *safe_args, **kwargs)
    sys.stdout.flush()

# 1. 加载环境变量
load_dotenv()
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")

# ── 统一的 API 配置获取 ──────────────────────────────────────────────────────
def _get_anthropic_client():
    """获取配置好的 Anthropic 客户端（带120秒超时）"""
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("未配置 ANTHROPIC_API_KEY 或 MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL", "http://114.132.200.116:3888/"),
        timeout=120.0
    )


def get_recent_intelligence(days):
    """从数据库捞取情报"""
    db_path = os.path.join(os.path.dirname(__file__), "ai_tracker.db")

    if not os.path.exists(db_path):
        log(f"⚠️ 致命错误：数据库文件不存在: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    time_threshold = (datetime.now() - timedelta(days=days)).isoformat()

    fetch_limit = 50 if days <= 1 else 150

    cursor.execute(f"""
        SELECT title, summary, risk_level, sentiment, source_url, published_date
        FROM events
        WHERE published_date >= ?
          AND published_date <= datetime('now', '+7 days')
          AND published_date >= '2019-01-01'
        ORDER BY
          CASE WHEN source_url IS NOT NULL AND source_url != '' THEN 0 ELSE 1 END,
          published_date DESC
        LIMIT {fetch_limit}
    """, (time_threshold,))

    events = cursor.fetchall()
    conn.close()
    return events

def generate_report_content(events, report_type, report_title):
    """召唤 MiniMax-M2 撰写极具深度的战略简报 (提示词已解耦)"""
    if not events:
        return f"📡 **{report_title}**：雷达静默，设定周期内未捕获到情报。"

    context = "\n\n".join([
        f"[{e[5][:10] if e[5] else '未知'}] {e[0]}\n摘要: {e[1]}\n风险: {e[2] or '无'} | 来源: {e[4] or '无'}"
        for e in events
    ])

    # 🚀 核心改动：从外部集中库引入提示词，并动态注入标题
    system_prompt = REPORTER_SYSTEM_PROMPT.format(report_title=report_title)

    log(f"🧠 正在呼叫 MiniMax-M2.7-highspeed 引擎进行深度战略推演 ({report_type})...")

    try:
        client = _get_anthropic_client()
        message = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": f"请分析以下情报并严格按规范输出高管内参：\n\n{context}"}]}]
        )

        final_text = ""
        log("-" * 50)
        for block in message.content:
            if block.type == "thinking":
                log(f"🤔 【思维链推演中】:\n{block.thinking[:150]}...\n")
            elif block.type == "text":
                final_text += block.text
                log(f"📝 【内参文本生成完毕】")
        log("-" * 50)
        return final_text

    except Exception as e:
        log(f"❌ 大模型调用致命失败: {e}")
        return None


def send_feishu_card(markdown_content, title_text):
    """发送飞书高级交互式卡片"""
    if not FEISHU_WEBHOOK_URL:
        log("❌ 错误: 未配置 FEISHU_WEBHOOK_URL")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "indigo", # 换成靛蓝色，更有极客和高级研报的质感
                "title": {"content": f"⚡️ 产业追踪雷达 | {title_text}", "tag": "plain_text"}
            },
            "elements": [
                {"tag": "markdown", "content": markdown_content},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"🤖 MiniMax-M2.7-highspeed 战略参谋驱动 | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"}]}
            ]
        }
    }

    log(f"🚀 正在向指挥部推送【{title_text}】...")
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        log(f"✅ 推送成功！飞书响应: {response.json().get('msg')}")
    except Exception as e:
        log(f"❌ 推送失败: {e}")

if __name__ == "__main__":
    report_type = "daily"
    if len(sys.argv) > 1:
        report_type = sys.argv[1].lower()

    config = {
        "daily": {"days": 1, "title": "每日战略简报"},
        "weekly": {"days": 7, "title": "每周深度内参"},
        "monthly": {"days": 30, "title": "月度产业观察"}
    }

    selected_config = config.get(report_type, config["daily"])
    days = selected_config["days"]
    title = selected_config["title"]

    raw_events = get_recent_intelligence(days=days)
    if raw_events:
        log(f"📊 {title}：捞取到过去 {days} 天内的 {len(raw_events)} 条原生情报，准备进行大浪淘沙...")
        report = generate_report_content(raw_events, report_type, title)

        if report:
            send_feishu_card(report, title)
        else:
            log("🛑 报告生成异常，为防止发送错误信息，已自动熔断并取消飞书推送。")
    else:
        log(f"📭 过去 {days} 天无新增情报，取消推送。")
