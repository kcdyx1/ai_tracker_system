#!/usr/bin/env python3
"""
AI Tracker System - 实体侦察兵 (动态 Schema 满血版)
根据实体类型（公司/产品/人物）动态下发不同的 JSON 提取格式，消除无效字段。
"""

import os
import json
import re
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from database import get_connection, query_entity_by_id

load_dotenv()

def search_tavily(query: str) -> str:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("未配置 TAVILY_API_KEY")
    url = "https://api.tavily.com/search"
    resp = requests.post(url, json={"api_key": api_key, "query": query, "search_depth": "advanced", "max_results": 4}, timeout=20)
    resp.raise_for_status()
    context = ""
    for res in resp.json().get("results", []):
        context += f"【来源】{res['url']}\n【内容】{res['content']}\n\n"
    return context

def fuse_intelligence(entity_name: str, entity_type: str, search_context: str) -> dict:
    api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key, base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic"), timeout=60.0)
    
    # 💡 核心升级：根据类型动态定制要提取的 JSON 字段！
    if entity_type == 'company':
        json_schema = """{ "description": "详细简介（核心业务与行业地位）", "website": "官网", "founded_year": "成立年份", "founders": "创始人", "core_business": "核心业务/投资偏好", "latest_funding": "最新融资信息" }"""
    elif entity_type == 'product' or entity_type == 'tech_concept':
        json_schema = """{ "description": "详细简介", "website": "官网/GitHub", "is_open_source": "开源情况", "parameters_size": "模型参数量级", "context_window": "上下文窗口", "pricing_model": "定价模式", "base_model": "底层依赖模型" }"""
    elif entity_type == 'person':
        json_schema = """{ "description": "详细人物简介", "current_title": "当前职务", "core_achievements": "核心成就/代表作", "social_media": "社交媒体或主页链接" }"""
    else:
        json_schema = """{ "description": "详细简介", "attributes": "其他核心属性的键值对" }"""

    sys_prompt = f"""你是一个顶尖的产业情报分析师。当前目标：【{entity_name}】(情报类型: {entity_type})。
【核心原则】
1. 尽最大努力提取信息，哪怕是碎片的线索。
2. 如果文中毫无线索，请填入 "未提及"。
3. 必须返回一个纯净的 JSON 对象，严格使用以下结构：
{json_schema}"""

    print(f"  🧠 正在让 MiniMax 提炼【{entity_type}】专属结构化 JSON...")
    
    msg = client.messages.create(
        model="MiniMax-M2.5", max_tokens=2000, system=sys_prompt,
        messages=[{"role": "user", "content": f"搜索结果如下：\n\n{search_context}"}]
    )
    
    raw_text = ""
    for block in msg.content:
        if block.type == "thinking":
            print(f"  🤔 [思维链]: {block.thinking[:45].replace(chr(10), '')}...") 
        elif block.type == "text":
            raw_text += block.text
            
    match = re.search(r'\{[\s\S]*\}', raw_text)
    if match: raw_text = match.group(0)
        
    try:
        dump = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"description": None, "attributes": {}}

    desc = dump.pop("description", None)
    if desc and "未提及" in desc: desc = ""
    
    # 💡 增强过滤逻辑：只要包含这些词，就视为无效数据
    invalid_keywords = ["none", "null", "未提及", "未知", "暂无", "不适用", "n/a", "无"]
    attrs = {}
    for k, v in dump.items():
        v_str = str(v).strip().lower()
        if v_str and not any(kw in v_str for kw in invalid_keywords):
            attrs[k] = v
            
    return {"description": desc, "attributes": attrs}

def run_enrichment(entity_id: str) -> dict:
    entity = query_entity_by_id(entity_id)
    if not entity: return {"status": "error", "message": "实体不存在"}
    
    name, e_type = entity['name'], entity['type']
    print(f"\n🕵️‍♂️ 侦察兵出动：锁定目标 [{name}] (类型: {e_type})")
    
    if e_type == 'company': query = f"{name} 投资机构 公司简介 创始人 投资偏好 融资"
    elif e_type == 'person': query = f"{name} AI 履历 职务 核心成就"
    else: query = f"{name} AI model context window open source architecture"
    
    try:
        print(f"  🌐 正在调用 Tavily 扫描全网...")
        search_context = search_tavily(query)
        if not search_context.strip(): return {"status": "error", "message": "未搜索到情报"}
            
        fused_data = fuse_intelligence(name, e_type, search_context)
        
        conn = get_connection(); cursor = conn.cursor()
        old_attr_str = entity.get('attributes_json')
        current_attrs = json.loads(old_attr_str) if old_attr_str and old_attr_str != "null" else {}
        
        if fused_data['attributes']: current_attrs.update(fused_data['attributes'])
        new_desc = fused_data['description'] or entity.get('description', '')
        
        cursor.execute("UPDATE entities SET description = ?, attributes_json = ? WHERE id = ?", 
                       (new_desc, json.dumps(current_attrs, ensure_ascii=False), entity_id))
        conn.commit(); conn.close()
        
        print(f"  ✅ 侦察成功！最终写入的扩展参数量: {len(fused_data['attributes'])}")
        return {"status": "success", "message": "成功挖掘并补全情报"}
    except Exception as e:
        print(f"  ❌ 侦察任务失败: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    pass