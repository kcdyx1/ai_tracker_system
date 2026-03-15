#!/usr/bin/env python3
"""
AI Tracker System - 可视化前端 v2.0
OSINT Intelligence Platform
"""

import streamlit as st
import pandas as pd
import sqlite3
import json
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

try:
    from streamlit_agraph import agraph, Node, Edge, Config
    AGRAPH_AVAILABLE = True
except ImportError:
    AGRAPH_AVAILABLE = False

from rag import chat_with_graph
from database import get_events_for_entity

DB_PATH = Path(__file__).parent / "ai_tracker.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================================
# 数据读取函数
# ============================================================================
@st.cache_data(ttl=60)
def get_summary_stats():
    conn = get_connection()
    cursor = conn.cursor()
    stats = {}
    cursor.execute("SELECT COUNT(*) FROM entities")
    stats["entity_count"] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM events")
    stats["event_count"] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM relationships")
    stats["relationship_count"] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'company'")
    stats["company_count"] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'product'")
    stats["product_count"] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM entities WHERE type = 'person'")
    stats["person_count"] = cursor.fetchone()[0]
    conn.close()
    return stats

@st.cache_data(ttl=60)
def get_all_entities():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@st.cache_data(ttl=60)
def get_latest_events(limit: int = 20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events ORDER BY date DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_entity_by_id(entity_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_entity_name_by_id(entity_id: str) -> str:
    entity = get_entity_by_id(entity_id)
    return entity["name"] if entity else entity_id

def convert_event_entities_to_names(event: dict) -> dict:
    if event.get("involved_entities_json"):
        try:
            entity_ids = json.loads(event["involved_entities_json"])
            event["involved_entity_names"] = [get_entity_name_by_id(eid) for eid in entity_ids]
        except:
            event["involved_entity_names"] = []
    return event

def get_graph_data(entity_id: str = None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    nodes, edges, entity_ids = [], [], set()

    if entity_id:
        cursor.execute("""
            SELECT r.source_id, r.target_id, r.relation_type
            FROM relationships r
            WHERE r.source_id = ? OR r.target_id = ?
        """, (entity_id, entity_id))
    else:
        cursor.execute("""
            SELECT r.source_id, r.target_id, r.relation_type
            FROM relationships r ORDER BY r.id DESC LIMIT 150
        """)

    for row in cursor.fetchall():
        source_id, target_id, rel_type = row
        entity_ids.update([source_id, target_id])
        edges.append({"source_id": source_id, "target_id": target_id, "relation_type": rel_type})

    for eid in entity_ids:
        cursor.execute("SELECT id, name, type FROM entities WHERE id = ?", (eid,))
        row = cursor.fetchone()
        if row:
            nodes.append({"id": row[0], "name": row[1], "type": row[2]})

    conn.close()
    return {"nodes": nodes, "edges": edges}

def get_task_queue_status():
    conn = get_connection()
    cursor = conn.cursor()
    status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
    for status in status_counts.keys():
        cursor.execute("SELECT COUNT(*) FROM task_queue WHERE status = ?", (status,))
        status_counts[status] = cursor.fetchone()[0]
    conn.close()
    return status_counts

def get_recent_tasks(limit: int = 20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, status, error_message, created_at FROM task_queue ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ============================================================================
# 页面配置与路由
# ============================================================================
st.set_page_config(page_title="AI & Data 产业追踪雷达", page_icon="📡", layout="wide")

with st.sidebar:
    st.title("📡 AI 产业追踪雷达")
    st.caption("OSINT Intelligence Platform v2.0")
    st.markdown("---")

    page = st.radio(
        "导航菜单",
        ["🎛️ 指挥中心", "📚 情报档案", "🕸️ 战术图谱", "💬 参谋部"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption(f"系统状态: 🟢 运行中\n\n更新于: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================================
# Page 1: 指挥中心 (Ops Center)
# ============================================================================
if page == "🎛️ 指挥中心":
    st.title("🎛️ 指挥中心 (Ops Center)")
    st.markdown("全局数据概览与数据摄入监控")

    stats = get_summary_stats()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总实体数", stats["entity_count"])
    col2.metric("总事件数", stats["event_count"])
    col3.metric("总关系数", stats["relationship_count"])
    col4.metric("公司数", stats["company_count"])
    col5.metric("产品数", stats["product_count"])

    st.markdown("---")

    with st.expander("📥 手动知识空投 (URL Ingestion)", expanded=True):
        url_input = st.text_input("粘贴需解析的文章链接", placeholder="https://...")
        if st.button("🚀 提交至处理队列", type="primary"):
            if url_input.startswith(("http://", "https://")):
                try:
                    res = requests.post("http://127.0.0.1:8000/api/ingest", json={"url": url_input}, timeout=10)
                    if res.status_code == 200:
                        st.success(f"✅ 链接提交成功！状态: {res.json().get('status')}")
                    else:
                        st.error(f"❌ 提交失败: {res.status_code}")
                except Exception as e:
                    st.error(f"❌ API 连接失败: {e}")
            else:
                st.warning("⚠️ 链接格式不正确")

    st.subheader("⚙️ 引擎运行监控")
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    task_stats = get_task_queue_status()
    col_t1.metric("⏳ 排队中 (Pending)", task_stats["pending"])
    col_t2.metric("🔄 提取中 (Processing)", task_stats["processing"])
    col_t3.metric("✅ 已入库 (Completed)", task_stats["completed"])
    col_t4.metric("❌ 失败 (Failed)", task_stats["failed"])

    if st.button("🔄 刷新任务队列"):
        st.rerun()

    tasks = get_recent_tasks(15)
    if tasks:
        st.dataframe(pd.DataFrame(tasks), use_container_width=True, hide_index=True)

# ============================================================================
# Page 2: 情报档案 (Intelligence DB)
# ============================================================================
elif page == "📚 情报档案":
    st.title("📚 情报档案 (Intelligence DB)")

    tab_timeline, tab_company, tab_product, tab_person, tab_concept = st.tabs([
        "📅 产业时间线", "🏢 公司库", "📦 产品库", "👤 人物库", "🔬 技术概念"
    ])

    with tab_timeline:
        events = get_latest_events(30)
        for event in events:
            event = convert_event_entities_to_names(event)
            with st.container(border=True):
                st.markdown(f"### {event['title']}")
                st.caption(f"发生日期: {event['date'][:10]} | 报道日期: {event['published_date'][:10]}")
                st.markdown(f"**摘要:** {event['summary']}")
                if event.get('involved_entity_names'):
                    st.markdown(f"**关联实体:** `{', '.join(event['involved_entity_names'])}`")

    entities = get_all_entities()

    with tab_company:
        df_comp = pd.DataFrame([e for e in entities if e['type'] == 'company'])
        if not df_comp.empty:
            st.dataframe(df_comp[['name', 'description', 'aliases_json', 'created_at']], use_container_width=True, hide_index=True)

    with tab_product:
        prod_list = [e.copy() for e in entities if e['type'] == 'product']
        if prod_list:
            import json
            for p in prod_list:
                attr_str = p.get('attributes_json')
                if attr_str:
                    try:
                        attrs = json.loads(attr_str)
                        for k, v in attrs.items():
                            # 将列表转换为逗号分隔的字符串，否则表格无法完美渲染
                            p[k] = ", ".join(v) if isinstance(v, list) else str(v)
                    except:
                        pass

            df_prod = pd.DataFrame(prod_list)

            # 定义期望展示的列和专业的列名映射
            col_mapping = {
                "name": "🚀 产品名称",
                "parameters_size": "🧮 参数量级",
                "context_window": "📚 上下文",
                "is_open_source": "🔓 开源",
                "architecture": "🏗️ 架构",
                "modalities": "👁️ 支持模态",
                "base_model": "🧬 底座模型",
                "pricing_model": "💰 定价模式",
                "description": "📝 简介"
            }

            # 只提取数据中真实存在的列，防止报错
            existing_cols = [c for c in col_mapping.keys() if c in df_prod.columns]

            st.dataframe(
                df_prod[existing_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_mapping
            )
        else:
            st.info("暂无产品数据。")

    with tab_person:
        df_pers = pd.DataFrame([e for e in entities if e['type'] == 'person'])
        if not df_pers.empty:
            st.dataframe(df_pers[['name', 'description', 'created_at']], use_container_width=True, hide_index=True)

    with tab_concept:
        df_conc = pd.DataFrame([e for e in entities if e['type'] == 'tech_concept'])
        if not df_conc.empty:
            st.dataframe(df_conc[['name', 'description', 'created_at']], use_container_width=True, hide_index=True)

# ============================================================================
# Page 3: 战术图谱 (Graph Analytics)
# ============================================================================
elif page == "🕸️ 战术图谱":
    st.title("🕸️ 战术图谱 (Graph Analytics)")

    if not AGRAPH_AVAILABLE:
        st.error("请安装依赖: pip install streamlit-agraph")
    else:
        col1, col2 = st.columns([1, 4])
        with col1:
            st.markdown("#### 图谱过滤器")
            selected_types = st.multiselect(
                "显示实体类型",
                ["company", "product", "person", "tech_concept"],
                default=["company", "product", "person", "tech_concept"]
            )

        with col2:
            raw_data = get_graph_data()

            filtered_nodes = [n for n in raw_data["nodes"] if n["type"] in selected_types]
            valid_node_ids = {n["id"] for n in filtered_nodes}
            filtered_edges = [e for e in raw_data["edges"] if e["source_id"] in valid_node_ids and e["target_id"] in valid_node_ids]

            nodes, edges = [], []
            color_map = {"company": "#3498db", "product": "#e74c3c", "person": "#2ecc71", "tech_concept": "#9b59b6"}

            for node in filtered_nodes:
                nodes.append(Node(id=node["id"], label=node["name"], size=25, color=color_map.get(node["type"], "#95a5a6")))

            for edge in filtered_edges:
                edges.append(Edge(source=edge["source_id"], target=edge["target_id"], label=edge["relation_type"], color="#7f8c8d"))

            st.caption(f"当前渲染: {len(nodes)} 个节点, {len(edges)} 条连线")

            config = Config(height=700, width={"percent": 100}, directed=True, physics=True, interaction={"hover": True})
            if nodes:
                agraph(nodes=nodes, edges=edges, config=config)
            else:
                st.info("当前过滤条件下没有可显示的图谱数据。")

# ============================================================================
# Page 4: 参谋部 (AI Copilot)
# ============================================================================
elif page == "💬 参谋部":
    st.title("💬 参谋部 (AI Copilot)")

    # 初始化会话状态
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 显示历史消息
    for msg in st.session_state.messages:
        with st.chat_message(msg.get("role", "user")):
            st.markdown(msg.get("content", ""))

    # 接收用户输入
    if prompt := st.chat_input("询问关于 AI 产业的任何情报..."):
        # 显示用户消息
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 调用 RAG 获取回复
        with st.spinner("🧠 正在检索底层图谱与事件库..."):
            response = chat_with_graph(prompt, st.session_state.messages[:-1])

        # 显示 AI 回复
        with st.chat_message("assistant"):
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response, "is_bot": True})
