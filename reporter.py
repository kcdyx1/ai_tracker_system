#!/usr/bin/env python3
"""
AI Tracker System - 智能报告生成与推送模块
"""

import os
from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime, timedelta
from pathlib import Path

import requests
import anthropic

from database import get_recent_events, query_entity_by_id

# 配置
REPORTS_DIR = Path(__file__).parent / "reports"

def build_report_context(days: int = 7) -> str:
    events = get_recent_events(days)
    if not events:
        return "暂无近期事件数据"
    
    context_lines = [f"📅 最近 {days} 天的 AI 产业重大事件：\n"]
    for event in events:
        try:
            event_date = datetime.fromisoformat(event.get("date", "")).strftime("%Y-%m-%d")
        except:
            event_date = event.get("date", "未知")
        
        try:
            pub_date = datetime.fromisoformat(event.get("published_date", "")).strftime("%Y-%m-%d %H:%M")
        except:
            pub_date = event.get("published_date", "未知")
        
        entity_names = []
        try:
            entity_ids = json.loads(event.get("involved_entities_json", "[]"))
            for eid in entity_ids:
                entity = query_entity_by_id(eid)
                if entity:
                    entity_names.append(entity["name"])
        except:
            pass
        
        entities_str = " | ".join(entity_names) if entity_names else "无"
        
        line = f"- [{event_date}] {event.get('title', '无标题')}"
        if event_date != pub_date:
            line += f" (报道时间: {pub_date})"
        line += f"\n  参与实体: {entities_str}"
        if event.get("summary"):
            line += f"\n  摘要: {event.get('summary', '')[:100]}..."
        
        context_lines.append(line)
    return "\n".join(context_lines)

def generate_ai_report(context: str, report_type: str = "周报") -> str:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 MINIMAX_API_KEY")
    
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url="https://api.minimaxi.com/anthropic"
    )
    
    system_prompt = f"""你是一个资深 AI 产业分析师。请根据提供的近期事件数据，写一份结构清晰、排版精美的 Markdown 格式行业{report_type}。

必须包含：
1. 核心动向总结
2. 资本与融资
3. 产品与技术发布
4. 关键人物动态

请注意区分事件的真实发生时间与媒体报道时间，进行深度解读，不要流水账。"""
    
    message = client.messages.create(
        model="MiniMax-M2.5",
        max_tokens=8000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"请根据以下数据生成报告：\n\n{context}"
            }
        ]
    )
    
    final_text = ""
    for block in message.content:
        if getattr(block, "type", "") == "text":
            final_text += block.text
        elif hasattr(block, "text"):
            final_text += block.text
    
    if not final_text:
        return "⚠️ 报告生成失败：未能从大模型返回结果中提取出有效文本。"
    return final_text

def save_local_report(markdown_content: str, report_type: str = "周报") -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}_AI产业{report_type}.md"
    filepath = REPORTS_DIR / filename
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    print(f"✅ 报告已保存到: {filepath}")
    return str(filepath)

def send_feishu_webhook(markdown_content: str, webhook_url: str) -> bool:
    """发送飞书 Webhook 推送 (精美排版版)"""
    import requests
    try:
        elements = []
        current_text = []
        
        for line in markdown_content.split('\n'):
            line_stripped = line.strip()
            if line_stripped.startswith('# '):
                current_text.append(f"**🔥 {line_stripped[2:].strip()}**\n")
            elif line_stripped.startswith('## '):
                if current_text and any(t.strip() for t in current_text):
                    elements.append({"tag": "markdown", "content": "\n".join(current_text).strip()})
                    current_text = []
                elements.append({"tag": "hr"})
                elements.append({"tag": "markdown", "content": f"**📌 {line_stripped[3:].strip()}**"})
            elif line_stripped.startswith('### '):
                current_text.append(f"\n**🔹 {line_stripped[4:].strip()}**")
            elif line_stripped.startswith('#### '):
                current_text.append(f"**{line_stripped[5:].strip()}**")
            elif line_stripped == '---':
                pass
            else:
                current_text.append(line)
        
        if current_text and any(t.strip() for t in current_text):
            elements.append({"tag": "markdown", "content": "\n".join(current_text).strip()})

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "📡 AI 产业情报雷达"},
                    "template": "blue"
                },
                "elements": elements[:50]
            }
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ 飞书精美卡片推送成功")
            return True
        else:
            print(f"❌ 飞书推送失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 飞书推送异常: {e}")
        return False

def main(days: int = 7, report_type: str = "周报"):
    print("=" * 50)
    print(f"🚀 开始生成 AI 产业 {report_type}")
    print("=" * 50)
    
    print("\n📥 步骤 1: 获取近期事件数据...")
    context = build_report_context(days)
    print(f"   获取到上下文长度: {len(context)} 字符")
    
    print("\n🤖 步骤 2: 调用大模型生成报告...")
    report = generate_ai_report(context, report_type)
    print(f"   报告长度: {len(report)} 字符")
    
    print("\n💾 步骤 3: 保存本地报告...")
    filepath = save_local_report(report, report_type)
    
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    if webhook_url:
        print("\n📢 步骤 4: 飞书推送...")
        send_feishu_webhook(report, webhook_url)
    else:
        print("\n⏭️ 步骤 4: 跳过飞书推送（未配置 FEISHU_WEBHOOK_URL）")
    
    print("\n" + "=" * 50)
    print("🎉 报告生成完成!")
    print("=" * 50)
    return filepath

if __name__ == "__main__":
    import sys
    days = 7
    report_type = "周报"
    if len(sys.argv) > 1:
        days = int(sys.argv[1])
    if len(sys.argv) > 2:
        report_type = sys.argv[2]
    main(days=days, report_type=report_type)