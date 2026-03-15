#!/usr/bin/env python3
"""
AI Tracker System - 智能报告生成与推送模块

功能：
- 获取近期事件数据
- 调用大模型生成行业报告
- 保存本地 Markdown 报告
- 支持飞书 Webhook 推送
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path

import requests
import anthropic

from database import get_recent_events, query_entity_by_id


# 配置
REPORTS_DIR = Path(__file__).parent / "reports"


def build_report_context(days: int = 7) -> str:
    """
    构建报告上下文
    
    Args:
        days: 获取最近几天的事件
        
    Returns:
        用于大模型阅读的文本上下文
    """
    events = get_recent_events(days)
    
    if not events:
        return "暂无近期事件数据"
    
    context_lines = [f"📅 最近 {days} 天的 AI 产业重大事件：\n"]
    
    for event in events:
        # 解析时间
        try:
            event_date = datetime.fromisoformat(event.get("date", "")).strftime("%Y-%m-%d")
        except:
            event_date = event.get("date", "未知")
        
        try:
            pub_date = datetime.fromisoformat(event.get("published_date", "")).strftime("%Y-%m-%d %H:%M")
        except:
            pub_date = event.get("published_date", "未知")
        
        # 获取参与实体名称
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
        
        # 拼接事件行
        line = f"- [{event_date}] {event.get('title', '无标题')}"
        if event_date != pub_date:
            line += f" (报道时间: {pub_date})"
        line += f"\n  参与实体: {entities_str}"
        if event.get("summary"):
            line += f"\n  摘要: {event.get('summary', '')[:100]}..."
        
        context_lines.append(line)
    
    return "\n".join(context_lines)


def generate_ai_report(context: str, report_type: str = "周报") -> str:
    """
    调用大模型生成行业报告
    
    Args:
        context: 事件上下文
        report_type: 报告类型（周报/月报）
        
    Returns:
        Markdown 格式的报告
    """
    # 初始化 Anthropic 客户端
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 MINIMAX_API_KEY")
    
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url="https://api.minimaxi.com/anthropic"
    )
    
    # System Prompt
    system_prompt = f"""你是一个资深 AI 产业分析师。请根据提供的近期事件数据，写一份结构清晰、排版精美的 Markdown 格式行业{report_type}。

必须包含：
1. 核心动向总结
2. 资本与融资
3. 产品与技术发布
4. 关键人物动态

请注意区分事件的真实发生时间与媒体报道时间，进行深度解读，不要流水账。"""
    
    # 调用模型
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
    
    # 兼容不同版本的 anthropic sdk 对象属性，提取真实文本
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
    """
    保存报告到本地
    
    Args:
        markdown_content: Markdown 内容
        report_type: 报告类型
        
    Returns:
        保存的文件路径
    """
    # 生成文件名
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}_AI产业{report_type}.md"
    filepath = REPORTS_DIR / filename
    
    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    print(f"✅ 报告已保存到: {filepath}")
    return str(filepath)


def send_feishu_webhook(markdown_content: str, webhook_url: str) -> bool:
    """
    发送飞书 Webhook 推送
    
    Args:
        markdown_content: Markdown 内容
        webhook_url: 飞书 Webhook URL
        
    Returns:
        是否成功
    """
    try:
        # 构造飞书富文本卡片 payload
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "📡 AI 产业周报"
                    },
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": markdown_content[:5000]  # 飞书有长度限制
                    }
                ]
            }
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print("✅ 飞书推送成功")
            return True
        else:
            print(f"❌ 飞书推送失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 飞书推送异常: {e}")
        return False


def main(days: int = 7, report_type: str = "周报"):
    """
    主函数
    
    Args:
        days: 获取最近几天的事件
        report_type: 报告类型
    """
    print("=" * 50)
    print(f"🚀 开始生成 AI 产业 {report_type}")
    print("=" * 50)
    
    # 1. 获取数据
    print("\n📥 步骤 1: 获取近期事件数据...")
    context = build_report_context(days)
    print(f"   获取到上下文长度: {len(context)} 字符")
    
    # 2. 生成报告
    print("\n🤖 步骤 2: 调用大模型生成报告...")
    report = generate_ai_report(context, report_type)
    print(f"   报告长度: {len(report)} 字符")
    
    # 3. 保存本地
    print("\n💾 步骤 3: 保存本地报告...")
    filepath = save_local_report(report, report_type)
    
    # 4. 飞书推送
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
    
    # 解析命令行参数
    days = 7
    report_type = "周报"
    
    if len(sys.argv) > 1:
        days = int(sys.argv[1])
    if len(sys.argv) > 2:
        report_type = sys.argv[2]
    
    main(days=days, report_type=report_type)
