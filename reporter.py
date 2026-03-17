#!/usr/bin/env python3
"""
OSINT Tracker - 飞书高级战略简报推送引擎 (v4.0 旗舰版)
修复超时问题，增加防误报熔断机制，强制显式绑定 MiniMax 接口。
"""

import os
import sys
import json
import sqlite3
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic

# 1. 加载环境变量
load_dotenv()
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")

# 2. 强制显式读取配置，配置默认备用 URL 防止遗漏
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# 如果 .env 没写，这里强制兜底到 MiniMax 的接口
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")

print(f"🔧 正在初始化客户端，目标接口: {ANTHROPIC_BASE_URL}")

# 3. 显式实例化客户端，并增加超时时间（M2.5 的思维链可能需要较长时间）
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
    timeout=120.0  # 强制 120 秒超时容忍度
)

def get_recent_intelligence(days):
    """从数据库捞取情报（使用绝对路径）"""
    db_path = os.path.join(os.path.dirname(__file__), "ai_tracker.db")
    
    if not os.path.exists(db_path):
        print(f"⚠️ 致命错误：数据库文件不存在: {db_path}")
        return []
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    time_threshold = (datetime.now() - timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT title, summary, risk_level, sentiment, source_url 
        FROM events 
        WHERE created_at >= ? 
        ORDER BY id DESC LIMIT 30
    """, (time_threshold,))
    
    events = cursor.fetchall()
    conn.close()
    return events

def generate_report_content(events, report_title):
    """召唤 MiniMax-M2.5 撰写简报（失败则返回 None 触发熔断）"""
    if not events:
        return f"📡 **{report_title}**：雷达静默，设定周期内未捕获到高价值产业情报。"

    context = "\n\n".join([
        f"标题: {e[0]}\n摘要: {e[1]}\n风险: {e[2] or '无'}\n倾向: {e[3] or '中性'}" 
        for e in events
    ])

    system_prompt = f"""你是一个资深 AI 产业分析师。请根据提供的近期事件数据，写一份结构清晰、排版精美的 Markdown 格式行业{report_type}。

必须包含：
1. 核心动向总结和战略研判
2. 资本融资趋势
3. 爆款产品与关键技术发布
4. 关键人物动态

请注意区分事件的真实发生时间与媒体报道时间，进行深度解读，事件讲清楚来龙去脉，观点要有深刻的洞察，不要流水账。【{report_title}】。
    
    【🚨 飞书专属排版军规 - 极度重要 🚨】
    1. 绝对禁止使用 Markdown 标题语法（严禁使用 #, ##, ###）。板块名称请直接使用【Emoji + 加粗】，例如：**🚗 智能出行板块**。
    2. 绝对禁止使用 Markdown 分割线（严禁使用 --- 或 *** 或 --）。
    3. 绝对禁止使用表格（严禁使用 |---|）。
    4. 事件罗列必须使用无序列表 `- ` 配合加粗，格式如下：
       - **小米释放调价预警**：雷军表示手机业务面临压力，行业预判上半年消费电子成本压力持续。
       - **哈啰斥资收购永安行**：被视作借壳上市铺路，出行赛道整合加速。
    5. 语言风格要像顶级咨询公司的简报，极其精炼，直击要害。
    """

    print(f"🧠 正在呼叫 MiniMax-M2.5 引擎生成【{report_title}】...")
    
    try:
        message = client.messages.create(
            model="MiniMax-M2.5",
            max_tokens=3000,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": f"请分析以下情报并严格按规范输出：\n\n{context}"}]}]
        )
        
        final_text = ""
        print("-" * 50)
        for block in message.content:
            if block.type == "thinking":
                print(f"🤔 【思维链】:\n{block.thinking[:100]}...\n") # 终端里只截取前100字展示，防刷屏
            elif block.type == "text":
                final_text += block.text
                print(f"📝 【文本生成完毕】")
        print("-" * 50)
        return final_text
        
    except Exception as e:
        print(f"❌ 大模型调用致命失败: {e}")
        return None # ⚠️ 核心修复：失败直接返回 None，触发底下的熔断保护

def send_feishu_card(markdown_content, title_text):
    """发送飞书高级交互式卡片"""
    if not FEISHU_WEBHOOK_URL:
        print("❌ 错误: 未配置 FEISHU_WEBHOOK_URL")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "blue",
                "title": {"content": f"⚡️ 产业追踪雷达 | {title_text}", "tag": "plain_text"}
            },
            "elements": [
                {"tag": "markdown", "content": markdown_content},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"🤖 MiniMax-M2.5 驱动 | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"}]}
            ]
        }
    }

    print(f"🚀 正在向指挥部推送【{title_text}】...")
    try:
        response = requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        print(f"✅ 推送成功！飞书响应: {response.json().get('msg')}")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

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

    # 这里为了测试不断网，可以先强制传 7，或者你在终端跑 python reporter.py weekly
    raw_events = get_recent_intelligence(days=days)
    if raw_events:
        print(f"📊 {title}：捞取到过去 {days} 天内的 {len(raw_events)} 条情报...")
        report = generate_report_content(raw_events, title)
        
        # 🛡️ 熔断机制：如果报告生成成功才推送
        if report:
            send_feishu_card(report, title)
        else:
            print("🛑 报告生成异常，为防止发送错误信息，已自动熔断并取消飞书推送。")
    else:
        print(f"📭 过去 {days} 天无新增情报，取消推送。")