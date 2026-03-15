#!/usr/bin/env python3
"""
AI Tracker System - 可视化前端

使用 Streamlit 构建产业追踪雷达看板
"""

import streamlit as st
import pandas as pd
import sqlite3
import json
from pathlib import Path
from datetime import datetime


# 数据库路径
DB_PATH = Path(__file__).parent / "ai_tracker.db"


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# 数据读取函数
# ============================================================================

def get_summary_stats():
    """获取大盘统计数据"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 实体总数
    cursor.execute("SELECT COUNT(*) FROM entities")
    entity_count = cursor.fetchone()[0]
    
    # 事件总数
    cursor.execute("SELECT COUNT(*) FROM events")
    event_count = cursor.fetchone()[0]
    
    # 关系总数
    cursor.execute("SELECT COUNT(*) FROM relationships")
    relationship_count = cursor.fetchone()[0]
    
    # 公司数量
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'company'")
    company_count = cursor.fetchone()[0]
    
    # 产品数量
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'product'")
    product_count = cursor.fetchone()[0]
    
    # 人物数量
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'person'")
    person_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "entity_count": entity_count,
        "event_count": event_count,
        "relationship_count": relationship_count,
        "company_count": company_count,
        "product_count": product_count,
        "person_count": person_count
    }


def get_all_entities():
    """获取所有实体"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_entity_by_id(entity_id: str):
    """根据ID获取实体详情"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_entity_by_name(name: str):
    """根据名称搜索实体"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM entities WHERE name LIKE ? OR aliases_json LIKE ? ORDER BY name",
        (f"%{name}%", f"%{name}%")
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_entity_relationships(entity_id: str):
    """获取与实体相关的所有关系"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 作为源实体的关系
    cursor.execute("""
        SELECT r.*, e.name as target_name, e.type as target_type
        FROM relationships r
        JOIN entities e ON r.target_id = e.id
        WHERE r.source_id = ?
    """, (entity_id,))
    outgoing = [dict(row) for row in cursor.fetchall()]
    
    # 作为目标实体的关系
    cursor.execute("""
        SELECT r.*, e.name as source_name, e.type as source_type
        FROM relationships r
        JOIN entities e ON r.source_id = e.id
        WHERE r.target_id = ?
    """, (entity_id,))
    incoming = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {"outgoing": outgoing, "incoming": incoming}


def get_latest_events(limit: int = 20):
    """获取最新事件列表"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY date DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_entity_name_by_id(entity_id: str) -> str:
    """根据实体ID获取名称"""
    entity = get_entity_by_id(entity_id)
    return entity["name"] if entity else entity_id


def convert_event_entities_to_names(event: dict) -> dict:
    """将事件中的实体ID列表转换为名称"""
    if event.get("involved_entities_json"):
        try:
            entity_ids = json.loads(event["involved_entities_json"])
            entity_names = [get_entity_name_by_id(eid) for eid in entity_ids]
            event["involved_entity_names"] = entity_names
        except:
            event["involved_entity_names"] = []
    return event


# ============================================================================
# Streamlit 页面配置
# ============================================================================

st.set_page_config(
    page_title="AI & Data 产业追踪雷达",
    page_icon="📡",
    layout="wide"
)


# ============================================================================
# 侧边栏
# ============================================================================

with st.sidebar:
    st.title("📡 AI 产业追踪雷达")
    st.markdown("---")
    
    # 大盘数据
    stats = get_summary_stats()
    
    st.subheader("📊 产业大盘")
    st.metric("收录实体总数", stats["entity_count"])
    st.metric("追踪事件总数", stats["event_count"])
    st.metric("关系连线总数", stats["relationship_count"])
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("公司", stats["company_count"])
    with col2:
        st.metric("产品", stats["product_count"])
    
    col3, col4 = st.columns(2)
    with col3:
        st.metric("人物", stats["person_count"])
    with col4:
        st.metric("概念", stats["entity_count"] - stats["company_count"] - stats["product_count"] - stats["person_count"])
    
    st.markdown("---")
    st.caption("数据更新于: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ============================================================================
# 主界面
# ============================================================================

st.title("📡 AI & Data 产业追踪雷达")

# 创建 Tab
tab1, tab2 = st.tabs(["📅 产业时间线", "🔍 实体探索器"])

# ============================================================================
# Tab 1: 产业时间线
# ============================================================================

with tab1:
    st.header("最新产业动态")
    
    events = get_latest_events(10)
    
    if not events:
        st.info("暂无事件数据，请先运行 main.py 提取数据")
    else:
        for event in events:
            event = convert_event_entities_to_names(event)
            
            with st.container():
                col1, col2 = st.columns([1, 4])
                
                with col1:
                    try:
                        event_date = datetime.fromisoformat(event["date"]).strftime("%Y-%m-%d")
                    except:
                        event_date = event["date"]
                    st.markdown(f"**{event_date}**")
                
                with col2:
                    st.subheader(event["title"])
                    if event.get("involved_entity_names"):
                        st.caption("参与实体: " + " | ".join(event["involved_entity_names"]))
                    if event.get("summary"):
                        st.write(event["summary"])
                
                st.markdown("---")


# ============================================================================
# Tab 2: 实体探索器
# ============================================================================

with tab2:
    st.header("🔍 实体探索器")
    
    # 搜索框
    search_query = st.text_input("🔎 搜索公司、产品或人物", placeholder="输入名称搜索...")
    
    if search_query:
        results = get_entity_by_name(search_query)
        
        if results:
            st.success(f"找到 {len(results)} 个结果")
            
            # 创建选择列表
            options = [f"{r['name']} ({r['type']})" for r in results]
            selected = st.selectbox("选择实体查看详情", options)
            
            if selected:
                # 解析选中的实体
                selected_name = selected.split(" (")[0]
                entity = next((r for r in results if r["name"] == selected_name), None)
                
                if entity:
                    # 展示基本信息
                    st.markdown("### 📋 实体详情")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**名称**: {entity['name']}")
                        st.markdown(f"**类型**: {entity['type']}")
                    with col2:
                        aliases = json.loads(entity.get("aliases_json", "[]"))
                        if aliases:
                            st.markdown(f"**别名**: {', '.join(aliases)}")
                    
                    if entity.get("description"):
                        st.markdown(f"**描述**: {entity['description']}")
                    
                    # 展示关系网
                    st.markdown("### 🕸️ 关系网络")
                    
                    relationships = get_entity_relationships(entity["id"])
                    
                    # 出向关系
                    if relationships["outgoing"]:
                        st.markdown("**该实体 → 其他实体:**")
                        for rel in relationships["outgoing"]:
                            st.markdown(f"- {entity['name']} --[{rel['relation_type']}]--> {rel['target_name']} ({rel['target_type']})")
                    
                    # 入向关系
                    if relationships["incoming"]:
                        st.markdown("**其他实体 → 该实体:**")
                        for rel in relationships["incoming"]:
                            st.markdown(f"- {rel['source_name']} --[{rel['relation_type']}]--> {entity['name']}")
                    
                    if not relationships["outgoing"] and not relationships["incoming"]:
                        st.info("暂无关系数据")
        else:
            st.warning("未找到匹配结果")
    else:
        # 显示所有实体列表
        all_entities = get_all_entities()
        
        st.markdown("### 所有实体")
        
        # 按类型分组
        companies = [e for e in all_entities if e["type"] == "company"]
        products = [e for e in all_entities if e["type"] == "product"]
        persons = [e for e in all_entities if e["type"] == "person"]
        techs = [e for e in all_entities if e["type"] == "tech_concept"]
        
        with st.expander(f"🏢 公司 ({len(companies)})", expanded=True):
            for c in companies:
                st.markdown(f"- **{c['name']}**")
        
        with st.expander(f"📦 产品 ({len(products)})"):
            for p in products:
                st.markdown(f"- **{p['name']}**")
        
        with st.expander(f"👤 人物 ({len(persons)})"):
            for p in persons:
                st.markdown(f"- **{p['name']}**")
        
        with st.expander(f"💡 技术概念 ({len(techs)})"):
            for t in techs:
                st.markdown(f"- **{t['name']}**")


# ============================================================================
# 底部信息
# ============================================================================

st.markdown("---")
st.caption("🚀 AI Tracker System v1.0 | 数据来源: AI 提取引擎")
