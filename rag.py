#!/usr/bin/env python3
"""
AI Tracker System - L3 战略推演引擎 (Graph-RAG)
"""

import os
import anthropic
from database import get_smart_rag_context

def chat_with_graph(user_query: str, chat_history: list = None) -> str:
    """
    接收用户提问，提取底层 L2 证据，生成 L3 战略研判
    """
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return "⚠️ 系统错误：参谋部无法运转，请在 .env 中配置 MINIMAX_API_KEY。"

    # 1. 核心：从数据库抽取增强版 L2 级图谱上下文 (自带风险、情感与原文证据)
    context = get_smart_rag_context(user_query)

    # 2. 灵魂：构建 L3 级战略推演 System Prompt
    system_prompt = f"""你现在是本情报系统的「首席战略官 (Chief Intelligence Officer)」。
你的任务是基于底层数据库检索出的【客观事实 (L2 级情报)】，为用户提供【战略推演 (L3 级研判)】。

【情报雷达检索到的底层事实 (包含红绿灯标签与证据)】：
{context}

【你的核心战术准则】：
1. 洞察动机：绝不要只是复述新闻！你要像顶级投行分析师一样，分析事件背后的商业动机（为什么要现在发？为什么收购它？目标是谁？）。
2. 风险穿透：如果检索到了 🚨 高危 或 ⚠️ 中风险 的事件，你必须在回答中强力警告，并推演其可能引发的连锁反应或信任危机。
3. 证据链闭环：当你提出一个战略观点时，必须引用检索内容里的 [关系证据] 或具体数据来支撑你的结论。
4. 降维打击：用冷酷、极客、一针见血的军事情报风格回答。多用项目符号和加粗突出重点。
5. 无中生有是死罪：如果检索到的情报完全不足以回答用户的问题，直接回答“情报雷达暂未捕获相关信号”，绝对不能凭借你的预训练记忆瞎编。"""

    # 3. 组装历史消息 (保留上下文对话能力)
    messages = []
    if chat_history:
        for msg in chat_history:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": msg.get("content", "")})
    
    messages.append({"role": "user", "content": user_query})

    # 4. 调用大模型进行终极推演
    try:
        client = anthropic.Anthropic(
            api_key=api_key,
            base_url="https://api.minimaxi.com/anthropic"
        )
        
        response = client.messages.create(
            model="MiniMax-M2.7",
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

if __name__ == "__main__":
    # 简单的本地测试
    print(chat_with_graph("总结一下目前的行业风险"))