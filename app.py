#!/usr/bin/env python3
"""
AI Tracker System - 可视化前端 v3.5 (Holographic Dossier Edition)
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

# ============================================================================
# 极客级 UI 样式注入 (V4.0 终极视觉引擎)
# ============================================================================
st.markdown('''
<style>
    /* 1. 沉浸式伪装：隐藏官方 Header 和 Footer */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    
    /* 2. 空间与进场动效：扩大视野，全局淡入 */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        max-width: 96% !important;
        animation: fadeIn 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    @keyframes fadeIn {
        0% { opacity: 0; transform: translateY(15px); }
        100% { opacity: 1; transform: translateY(0); }
    }

    /* 3. 数据看板 (Metrics) 玻璃拟态与交互反馈 */
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, rgba(15, 23, 42, 0.7), rgba(30, 41, 59, 0.3));
        border: 1px solid rgba(0, 255, 204, 0.15);
        padding: 15px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        transition: all 0.3s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-4px);
        border: 1px solid rgba(0, 255, 204, 0.5);
        box-shadow: 0 8px 25px rgba(0, 255, 204, 0.15);
        background: linear-gradient(145deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.5));
    }
    [data-testid="stMetricValue"] {
        color: #00FFCC !important;
        font-family: 'Courier New', Courier, monospace;
        font-weight: 700;
        text-shadow: 0 0 10px rgba(0, 255, 204, 0.2);
    }

    /* 4. 侧边栏深度定制 */
    [data-testid="stSidebar"] {
        background-color: #080d1a !important;
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-of-type {
        display: none; /* 隐藏单选圆圈 */
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label {
        padding: 12px 20px;
        margin-bottom: 8px;
        border-radius: 8px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        cursor: pointer;
        border-left: 3px solid transparent;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
        background-color: rgba(0, 255, 204, 0.05);
        transform: translateX(6px);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label[aria-checked="true"] {
        background-color: rgba(0, 255, 204, 0.1) !important;
        border-left: 3px solid #00FFCC !important;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] > label[aria-checked="true"] p {
        color: #00FFCC !important;
        font-weight: bold;
        text-shadow: 0 0 8px rgba(0,255,204,0.4);
    }

    /* 5. 标签页 (Tabs) 科幻风格指示器 */
    [data-testid="stTabs"] button {
        border-bottom: 2px solid transparent;
        transition: all 0.3s;
        padding-bottom: 10px;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        border-bottom: 2px solid #00FFCC !important;
        color: #00FFCC !important;
    }
    
    /* 6. 知识空投容器 (Expander) 美化 */
    [data-testid="stExpander"] {
        background-color: rgba(15, 23, 42, 0.4);
        border: 1px solid #1e293b;
        border-radius: 8px;
    }
</style>
''', unsafe_allow_html=True)





with st.sidebar:
    st.title("📡 产业追踪雷达")
    st.caption("OSINT Intelligence Platform v3.5")
    st.markdown("---")

    page = st.radio(
        "导航菜单",
        ["🎛️ 指挥中心", "📚 情报大盘", "📇 实体全息档案", "🕸️ 战术图谱", "💬 参谋部"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption(f"系统状态: 🟢 运行中\n\n更新于: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================================
# Page 1: 指挥中心
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

    with st.expander("📥 多模态情报接收舱 (Multi-modal Ingestion)", expanded=True):
        tab_url, tab_file = st.tabs(["🔗 网页直连", "📄 深度文档解析"])
        
        with tab_url:
            url_input = st.text_input("粘贴需解析的新闻、博客文章链接", placeholder="https://...")
            if st.button("🚀 提交 URL 至队列", type="primary", use_container_width=True):
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
                    
        with tab_file:
            uploaded_file = st.file_uploader(
                "拖拽上传行业研报、财报、技术白皮书", 
                type=["pdf", "docx", "txt", "md"],
                help="支持 PDF, Word, Markdown 等格式，单文件建议不超过 50MB"
            )
            if st.button("📦 将文档送入解析引擎", type="primary", use_container_width=True):
                if uploaded_file is not None:
                    # 调用真实的后端上传接口
                    try:
                        with st.spinner(f"正在将 '{uploaded_file.name}' 传输至服务器..."):
                            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                            res = requests.post("http://127.0.0.1:8000/api/upload", files=files, timeout=30)
                            
                        if res.status_code == 200:
                            st.success(f"✅ 文件 '{uploaded_file.name}' 已成功送入解析队列！状态: {res.json().get('status')}")
                        else:
                            st.error(f"❌ 上传失败: HTTP {res.status_code} - {res.text}")
                    except Exception as e:
                        st.error(f"❌ 上传请求异常: {e}")
                else:
                    st.error("⚠️ 请先拖拽或选择一个文件！")

    st.subheader("⚙️ 引擎运行监控")
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    task_stats = get_task_queue_status()
    col_t1.metric("⏳ 排队中", task_stats["pending"])
    col_t2.metric("🔄 提取中", task_stats["processing"])
    col_t3.metric("✅ 已入库", task_stats["completed"])
    col_t4.metric("❌ 失败", task_stats["failed"])

    if st.button("🔄 刷新任务队列"):
        st.rerun()

    tasks = get_recent_tasks(15)
    if tasks:
        st.dataframe(pd.DataFrame(tasks), use_container_width=True, hide_index=True)

# ============================================================================
# Page 2: 情报大盘 (Intelligence DB)
# ============================================================================
elif page == "📚 情报大盘":
    st.title("📚 情报大盘 (Intelligence Overview)")

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
        df_comp = pd.DataFrame([e for e in entities if e['type'] == 'company']).fillna("")
        if not df_comp.empty:
            st.dataframe(df_comp[['name', 'description', 'aliases_json', 'created_at']], use_container_width=True, hide_index=True)

    with tab_product:
        prod_list = [e.copy() for e in entities if e['type'] == 'product']
        if prod_list:
            for p in prod_list:
                attr_str = p.get('attributes_json')
                if attr_str and attr_str != "null":
                    try:
                        attrs = json.loads(attr_str)
                        for k, v in attrs.items():
                            p[k] = ", ".join(v) if isinstance(v, list) else str(v)
                    except:
                        pass

            df_prod = pd.DataFrame(prod_list)

            # 强制填充所有列，确保表头完整展示
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
            
            for col in col_mapping.keys():
                if col not in df_prod.columns:
                    df_prod[col] = ""  # 强行注入缺失列
                    
            # 彻底清洗掉 Pandas 自带的 NaN 和 None
            df_prod = df_prod.fillna("")

            st.dataframe(
                df_prod[list(col_mapping.keys())],
                use_container_width=True,
                hide_index=True,
                column_config=col_mapping
            )
        else:
            st.info("暂无产品数据。")

    with tab_person:
        df_pers = pd.DataFrame([e for e in entities if e['type'] == 'person']).fillna("")
        if not df_pers.empty:
            st.dataframe(df_pers[['name', 'description', 'created_at']], use_container_width=True, hide_index=True)

    with tab_concept:
        df_conc = pd.DataFrame([e for e in entities if e['type'] == 'tech_concept']).fillna("")
        if not df_conc.empty:
            st.dataframe(df_conc[['name', 'description', 'created_at']], use_container_width=True, hide_index=True)

# ============================================================================
# Page 3: 实体全息档案 (Holographic Dossier) - 新增
# ============================================================================
elif page == "📇 实体全息档案":
    st.title("📇 实体全息档案 (Holographic Dossier)")
    st.markdown("在这里，你可以穿透查看任何一个维度的技术底牌、历史大事件，以及其隐秘的关系网络。")
    
    entities = get_all_entities()
    type_emoji = {"company": "🏢", "product": "📦", "person": "👤", "tech_concept": "🔬"}
    entity_dict = {f"{type_emoji.get(e['type'], '📌')} {e['name']}": e for e in entities}
    
    selected_key = st.selectbox("🔍 搜索或选择目标实体：", options=[""] + list(entity_dict.keys()))
    
    if selected_key:
        ent = entity_dict[selected_key]
        st.markdown("---")
        
        # --- 顶部：基础档案 ---
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"## {ent['name']}")
            if ent.get('aliases_json') and ent['aliases_json'] not in ('[]', 'null', None):
                st.caption(f"已知别名/曾用名: {ent['aliases_json']}")
            st.info(ent['description'] if ent['description'] else "暂无详细简介。")
        with col2:
            st.metric("核心分类", ent['type'].upper())
            st.caption(f"系统收录时间: {ent['created_at'][:10]}")
            
            # ⚡️ 呼叫侦察兵按钮 (仅针对产品类型开放)
            if ent['type'] == 'product':
                if st.button("⚡️ 呼叫侦察兵 (全网补全)", type="primary", use_container_width=True):
                    with st.spinner("🕵️‍♂️ 侦察兵已出动，正在全网搜索技术文档与参数... (约需 10-20 秒)"):
                        try:
                            res = requests.post(f"http://127.0.0.1:8000/api/enrich/{ent['id']}", timeout=40)
                            if res.status_code == 200:
                                st.success(f"✅ {res.json().get('message')}")
                                # 清除缓存并刷新页面以显示新数据
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"❌ 侦察失败: {res.json().get('detail')}")
                        except Exception as e:
                            st.error(f"❌ API 调用异常: {e}")
            
        # --- 中部：深度特征解析 ---
        if ent.get('attributes_json') and ent['attributes_json'] != "null":
            try:
                attrs = json.loads(ent['attributes_json'])
                if attrs:
                    st.markdown("### 💡 深度剖析参数")
                    with st.container(border=True):
                        keys = list(attrs.keys())
                        cols = st.columns(4)
                        for i, k in enumerate(keys):
                            v = attrs[k]
                            v_str = ", ".join(v) if isinstance(v, list) else str(v)
                            if v_str and v_str != "None":
                                with cols[i % 4]:
                                    st.markdown(f"**{k}**")
                                    st.markdown(f"`{v_str}`")
            except:
                pass
                
        st.markdown("---")
        
        # --- 底部：历史与网络 ---
        tab_ev, tab_rel = st.tabs(["🕒 历史大事件穿透", "🕸️ 商业与技术关系网"])
        
        with tab_ev:
            events = get_events_for_entity(ent['id'])
            if events:
                for ev in events:
                    with st.container(border=True):
                        st.markdown(f"**{ev['date'][:10]}** | **{ev['title']}**")
                        st.caption(ev['summary'])
                        if ev.get('source_url'):
                            st.markdown(f"[🔗 溯源链接]({ev['source_url']})")
            else:
                st.write("情报库中暂无与该实体直接相关的重大事件。")
                
        with tab_rel:
            graph_data = get_graph_data(ent['id'])
            if graph_data["edges"]:
                for edge in graph_data["edges"]:
                    src_name = next((n['name'] for n in graph_data['nodes'] if n['id'] == edge['source_id']), edge['source_id'])
                    tgt_name = next((n['name'] for n in graph_data['nodes'] if n['id'] == edge['target_id']), edge['target_id'])
                    st.markdown(f"- **{src_name}** ➔ `[{edge['relation_type']}]` ➔ **{tgt_name}**")
            else:
                st.write("雷达暂未探测到该实体的关联连线。")

# ============================================================================
# Page 4: 战术图谱 (Graph Analytics)
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
# Page 5: 参谋部 (AI Copilot)
# ============================================================================
elif page == "💬 参谋部":
    st.title("💬 参谋部 (AI Copilot)")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg.get("role", "user")):
            st.markdown(msg.get("content", ""))

    if prompt := st.chat_input("询问关于 AI 产业的任何情报..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.spinner("🧠 正在检索底层图谱与事件库..."):
            response = chat_with_graph(prompt, st.session_state.messages[:-1])

        with st.chat_message("assistant"):
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response, "is_bot": True})
