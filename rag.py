#!/usr/bin/env python3
"""
AI Tracker System - Graph-RAG 引擎

用于智能问答，基于本地图谱和事件库
"""

import os
from dotenv import load_dotenv
load_dotenv()

import anthropic
from database import get_smart_rag_context


def chat_with_graph(user_message: str, history: list) -> str:
    """
    与图谱进行对话
    
    Args:
        user_message: 用户最新提问
        history: 对话历史
        
    Returns:
        AI 回复
    """
    # 获取 API Key
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return "❌ 错误: 未配置 MINIMAX_API_KEY"
    
    # 初始化客户端
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url="https://api.minimaxi.com/anthropic"
    )
    
    # 获取智能上下文
    context = get_smart_rag_context(user_message)
    
    # 构建 System Prompt
    system_prompt = f"""你是一个顶级 AI 产业情报分析师。请严格根据以下我提供的本地数据库情报上下文，回答用户的提问。如果上下文中没有相关信息，请明确说明，绝不要利用自身的预训练数据编造。

上下文：
{context}

你必须基于以上真实数据回答问题。"""
    
    # 构建 messages
    messages = []
    for msg in history:
        role = "assistant" if msg.get("is_bot") else "user"
        messages.append({
            "role": role,
            "content": msg.get("content", "")
        })
    messages.append({
        "role": "user", 
        "content": user_message
    })
    
    # 调用模型
    try:
        message = client.messages.create(
            model="MiniMax-M2.5",
            max_tokens=4000,
            system=system_prompt,
            messages=messages
        )
        
        # 解析回复
        final_text = ""
        for block in message.content:
            if getattr(block, "type", "") == "text":
                final_text += block.text
            elif hasattr(block, "text"):
                final_text += block.text
        
        return final_text if final_text else "⚠️ 未能获取有效回复"
        
    except Exception as e:
        return f"❌ 调用出错: {str(e)}"
