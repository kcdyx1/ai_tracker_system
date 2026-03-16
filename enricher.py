#!/usr/bin/env python3
"""
AI Tracker System - 实体侦察兵 (Enricher Agent)
自动调用 Tavily 搜索全网，使用大模型提取缺失的高价值参数并自愈写回数据库。
"""

import os
import json
import requests
from typing import Optional, List
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic
from database import get_connection, query_entity_by_id

# 定义要提取的缺失特征结构 (严格控制幻觉)
class EnrichedFeatures(BaseModel):
    is_open_source: Optional[bool] = Field(default=None, description="是否开源，如果搜不到则必须为 null")
    parameters_size: Optional[str] = Field(default=None, description="参数量级，如 8B, 70B, 1.5T")
    context_window: Optional[str] = Field(default=None, description="上下文窗口，如 128k, 1M")
    architecture: Optional[str] = Field(default=None, description="模型架构，如 MoE, Transformer")
    modalities: Optional[List[str]] = Field(default=None, description="支持的模态，如 文本, 图像, 音频")
    base_model: Optional[str] = Field(default=None, description="如果是套壳应用，其底座模型是什么")
    pricing_model: Optional[str] = Field(default=None, description="定价模式，如 免费, API计费, 订阅制")

def search_tavily(query: str) -> str:
    """调用 Tavily 搜索引擎获取高质量上下文"""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("未配置 TAVILY_API_KEY")
    
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "include_answer": False,
        "max_results": 5
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    
    # 拼接搜索摘要
    context = ""
    for res in data.get("results", []):
        context += f"【来源】{res['url']}\n【内容】{res['content']}\n\n"
    return context

def fuse_intelligence(entity_name: str, search_context: str) -> dict:
    """使用大模型从搜索结果中榨取参数"""
    api_key = os.environ.get("MINIMAX_API_KEY")
    client = instructor.from_anthropic(Anthropic(
        api_key=api_key,
        base_url="https://api.minimaxi.com/anthropic"
    ))
    
    sys_prompt = f"""你是一个冷酷的情报融合特工。目标产品：【{entity_name}】。
请从以下最新的全网搜索结果中，精确提取出该产品的技术参数和商业模式。
【红线警告】：
1. 你的职责仅仅是“提取”。
2. 如果搜索内容中没有明确提及某个参数，该字段必须严格返回 null！绝对不允许凭借你的历史记忆去猜测或编造！"""

    result = client.chat.completions.create(
        model="MiniMax-M2.5",
        max_tokens=2000,
        system=sys_prompt,
        messages=[{"role": "user", "content": f"搜索结果如下：\n\n{search_context}"}],
        response_model=EnrichedFeatures,
    )
    # 过滤掉 None 值，只返回真正提取到的增量情报
    return {k: v for k, v in result.model_dump().items() if v is not None and v != []}

def run_enrichment(entity_id: str) -> dict:
    """侦察兵主流程：抓取 -> 提取 -> 融合 -> 写回"""
    entity = query_entity_by_id(entity_id)
    if not entity or entity['type'] != 'product':
        return {"status": "error", "message": "实体不存在或不是产品类型"}
    
    print(f"🕵️‍♂️ 侦察兵出动：锁定目标 [{entity['name']}]")
    
    # 构建高精度定向搜索词
    query = f"{entity['name']} AI model context window parameters open source pricing architecture"
    
    try:
        print(f"  🌐 正在调用 Tavily 扫描全网...")
        search_context = search_tavily(query)
        if not search_context.strip():
            return {"status": "error", "message": "全网未搜索到相关情报"}
            
        print(f"  🧠 正在调用 MiniMax 进行情报提炼...")
        new_attrs = fuse_intelligence(entity['name'], search_context)
        
        if not new_attrs:
            return {"status": "warning", "message": "全网扫描完毕，但未提取到高价值增量参数"}
            
        # 数据库融合与写回
        conn = get_connection()
        cursor = conn.cursor()
        
        # 读取旧的 attributes
        old_attr_str = entity.get('attributes_json')
        current_attrs = json.loads(old_attr_str) if old_attr_str and old_attr_str != "null" else {}
        
        # 合并新旧属性 (旧属性为主，新属性填补空白或覆写)
        current_attrs.update(new_attrs)
        
        cursor.execute("UPDATE entities SET attributes_json = ? WHERE id = ?", 
                       (json.dumps(current_attrs, ensure_ascii=False), entity_id))
        conn.commit()
        conn.close()
        
        print(f"  ✅ 侦察成功！成功注入 {len(new_attrs)} 项新情报: {list(new_attrs.keys())}")
        return {"status": "success", "message": f"成功挖掘并补全 {len(new_attrs)} 项参数", "new_data": new_attrs}
        
    except Exception as e:
        print(f"  ❌ 侦察任务失败: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # 测试用例
    # run_enrichment("替换为一个真实的实体ID")
    pass
