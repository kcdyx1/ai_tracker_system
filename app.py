#!/usr/bin/env python3
"""
AI Tracker System - 可视化前端

使用 Streamlit 构建产业追踪雷达看板
"""

import streamlit as st
import pandas as pd
import sqlite3
import json
import requests
from pathlib import Path
from datetime import datetime

# 导入图谱可视化库
try:
    from streamlit_agraph import agraph, Node, Edge, Config
    AGRAPH_AVAILABLE = True
except ImportError:
    AGRAPH_AVAILABLE = False


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


def get_graph_data(entity_id: str = None) -> dict:
    """
    获取图谱数据
    
    Args:
        entity_id: 可选，指定实体ID。如果传入，则获取该实体的一度关系；
                   如果不传，则获取全局最新的50条关系。
    
    Returns:
        包含 nodes 和 edges 的字典
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    nodes = []
    edges = []
    entity_ids = set()
    
    if entity_id:
        # 查询该实体及其直接相连的一度关系
        # 作为源实体
        cursor.execute("""
            SELECT r.source_id, r.target_id, r.relation_type, 
                   e1.name as source_name, e1.type as source_type,
                   e2.name as target_name, e2.type as target_type
            FROM relationships r
            JOIN entities e1 ON r.source_id = e1.id
            JOIN entities e2 ON r.target_id = e2.id
            WHERE r.source_id = ? OR r.target_id = ?
        """, (entity_id, entity_id))
        
        for row in cursor.fetchall():
            source_id, target_id, rel_type, source_name, source_type, target_name, target_type = row
            entity_ids.add(source_id)
            entity_ids.add(target_id)
            edges.append({
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": rel_type
            })
    else:
        # 获取全局最新的50条关系
        cursor.execute("""
            SELECT r.source_id, r.target_id, r.relation_type,
                   e1.name as source_name, e1.type as source_type,
                   e2.name as target_name, e2.type as target_type
            FROM relationships r
            JOIN entities e1 ON r.source_id = e1.id
            JOIN entities e2 ON r.target_id = e2.id
            ORDER BY r.source_id DESC
            LIMIT 50
        """)
        
        for row in cursor.fetchall():
            source_id, target_id, rel_type, source_name, source_type, target_name, target_type = row
            entity_ids.add(source_id)
            entity_ids.add(target_id)
            edges.append({
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": rel_type
            })
    
    # 查询涉及的实体详情
    for eid in entity_ids:
        cursor.execute("SELECT id, name, type FROM entities WHERE id = ?", (eid,))
        row = cursor.fetchone()
        if row:
            nodes.append({
                "id": row[0],
                "name": row[1],
                "type": row[2]
            })
    
    conn.close()
    
    return {"nodes": nodes, "edges": edges}


# ============================================================================
# Streamlit 页面配置
# ============================================================================

st.set_page_config(
    page_title="AI & Data 产业追踪雷达",
    page_icon="📡",
    layout="wide"
)


# ============================================================================
# 任务队列监控函数
# ============================================================================

def get_task_queue_status() -> dict:
    """
    获取任务队列状态统计
    
    Returns:
        包含 pending, processing, completed, failed 数量的字典
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    status_counts = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0
    }
    
    for status in status_counts.keys():
        cursor.execute(
            "SELECT COUNT(*) FROM task_queue WHERE status = ?",
            (status,)
        )
        status_counts[status] = cursor.fetchone()[0]
    
    conn.close()
    return status_counts


def get_recent_tasks(limit: int = 20) -> list:
    """
    获取最近的任务记录
    
    Args:
        limit: 返回记录数量，默认 20
        
    Returns:
        任务列表
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT *
        FROM task_queue
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {"id": row[0], "url": row[1], "status": row[2], "created_at": row[3]}
        for row in rows
    ]


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
    
    # ========== 知识空投区 ==========
    st.markdown("---")
    st.subheader("📥 知识空投")
    
    url_input = st.text_input("粘贴文章链接", placeholder="https://...")
    
    if st.button("🚀 提交分析"):
        if url_input:
            if not url_input.startswith(("http://", "https://")):
                st.error("❌ URL 必须是 http 或 https 开头")
            else:
                try:
                    response = requests.post(
                        "http://127.0.0.1:8000/api/ingest",
                        json={"url": url_input},
                        timeout=10
                    )
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("status") == "queued":
                            st.success("✅ 链接已成功加入后台处理队列！")
                        elif result.get("status") == "already_exists":
                            st.warning("⚠️ 该链接已经在队列中或已处理过。")
                        else:
                            st.success("✅ 请求已提交！")
                        st.info("💡 后台正在处理，请稍后刷新页面查看结果")
                    else:
                        st.error(f"❌ 请求失败: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    st.error(f"❌ 无法连接到 API 服务: {e}")
        else:
            st.warning("⚠️ 请输入链接")


# ============================================================================
# 主界面
# ============================================================================

st.title("📡 AI & Data 产业追踪雷达")

# 创建 Tab
tab1, tab2, tab3 = st.tabs(["📅 产业时间线", "🕸️ 动态关系图谱", "⚙️ 系统监控"])

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
# Tab 2: 动态关系图谱
# ============================================================================

with tab2:
    st.header("🕸️ 动态关系图谱")
    
    if not AGRAPH_AVAILABLE:
        st.error("❌ streamlit-agraph 未安装，请运行: pip install streamlit-agraph")
    else:
        # 提供选择：全局图谱或单个实体图谱
        graph_mode = st.radio(
            "选择图谱模式",
            ["全局关系图谱", "单个实体图谱"],
            horizontal=True
        )
        
        if graph_mode == "单个实体图谱":
            # 选择实体
            all_entities = get_all_entities()
            entity_options = {e["name"]: e["id"] for e in all_entities}
            selected_entity_name = st.selectbox("选择实体", list(entity_options.keys()))
            selected_entity_id = entity_options[selected_entity_name]
            graph_data = get_graph_data(selected_entity_id)
        else:
            graph_data = get_graph_data()
        
        if not graph_data["nodes"]:
            st.info("暂无图谱数据，请先提取一些知识")
        else:
            # 构建节点
            nodes = []
            for node in graph_data["nodes"]:
                # 根据类型设置颜色
                color_map = {
                    "company": "#3498db",    # 蓝色
                    "product": "#e74c3c",   # 红色
                    "person": "#2ecc71",    # 绿色
                    "tech_concept": "#9b59b6"  # 紫色
                }
                color = color_map.get(node["type"], "#95a5a6")
                
                nodes.append(
                    Node(
                        id=node["id"],
                        label=node["name"],
                        size=25,
                        color=color,
                        title=f"{node['name']} ({node['type']})"
                    )
                )
            
            # 构建边
            edges = []
            for edge in graph_data["edges"]:
                edges.append(
                    Edge(
                        source=edge["source_id"],
                        target=edge["target_id"],
                        label=edge["relation_type"],
                        color="#bdc3c7"
                    )
                )
            
            # 配置图谱
            config = Config(
                height=600,
                width={"percent": 100},
                directed=True,
                physics=True,
                hierarchical=False,
                interaction={"hover": True}
            )
            
            # 渲染图谱
            st.markdown(f"**节点数: {len(nodes)} | 边数: {len(edges)}**")
            agraph(nodes=nodes, edges=edges, config=config)


# ============================================================================
# Tab 3: 系统监控
# ============================================================================

with tab3:
    st.header("⚙️ 后台任务监控")
    
    # 刷新按钮
    if st.button("🔄 刷新状态"):
        st.rerun()
    
    # 获取任务状态
    status = get_task_queue_status()
    
    # 展示状态卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("⏳ 排队中", status["pending"])
    with col2:
        st.metric("🔄 处理中", status["processing"])
    with col3:
        st.metric("✅ 已完成", status["completed"])
    with col4:
        st.metric("❌ 失败", status["failed"])
    
    # 展示最近任务列表
    st.markdown("### 📋 最近任务")
    tasks = get_recent_tasks(20)
    if tasks:
        df = pd.DataFrame(tasks)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("暂无任务记录")


# ============================================================================
# 底部信息
# ============================================================================

st.markdown("---")
st.caption("🚀 AI Tracker System v1.0 | 数据来源: AI 提取引擎")
