# -*- coding: utf-8 -*-
"""
Reporter v5.1 - Pipeline 架构战略简报生成引擎
Filter → Plugin → Synthesizer → Distributors

数据清洗(intelligence_selector) → 论文解读(paper_highlight) →
LLM生成(style_prompt) → 飞书推送(feishu) + 微信草稿箱(wechat)
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# 敏感信息过滤
_SENSITIVE_KEYS = {
    "api_key", "secret", "token", "password", "auth",
    "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "TAVILY_API_KEY",
    "FEISHU_WEBHOOK_URL", "WECHAT_APPID", "WECHAT_APPSECRET",
}

def _mask_sensitive(text: str) -> str:
    import re
    result = text
    for key in _SENSITIVE_KEYS:
        pattern = rf'({re.escape(key)}["\s:=]+)[^&\s"\'}}]+'
        result = re.sub(pattern, r'\1***(已隐藏)', result)
    return result

_original_print = print
def log(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_args = tuple(_mask_sensitive(str(a)) if isinstance(a, str) else a for a in args)
    _original_print(f"[{timestamp}]", *safe_args, **kwargs)
    sys.stdout.flush()

# ── 环境变量 ──────────────────────────────────────────────────────────────
load_dotenv()
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")

# ── LLM 客户端 ────────────────────────────────────────────────────────────
def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("未配置 ANTHROPIC_API_KEY 或 MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
        timeout=120.0,
    )


# ── Pipeline Stage 1: Filter ────────────────────────────────────────────────
def _run_filter(days: int) -> dict:
    """数据清洗与过滤：P0/P1/P2 筛选 + 硬性截断"""
    try:
        from intelligence_selector import select_and_rank_events
        result = select_and_rank_events(days=days, max_events=50)
        log(f"[Filter] P0={len(result['p0'])} | P1={len(result['p1'])} | P2_brief={len(result['p2_brief'])}")
        return result
    except Exception as e:
        log(f"[Filter] 失败，使用兜底逻辑: {e}")
        return {"p0": [], "p1": [], "p2_brief": [], "days": days}


# ── Pipeline Stage 2: Plugin ────────────────────────────────────────────────
def _run_paper_plugin(days: int) -> str:
    """外围情报：arXiv 论文解读"""
    try:
        from paper_highlight import get_paper_highlight
        result = get_paper_highlight(days=days)
        if result:
            log(f"[Paper] 获取成功")
        else:
            log(f"[Paper] 无相关论文，跳过")
        return result or ""
    except Exception as e:
        log(f"[Paper] 失败: {e}")
        return ""


# ── 历史召回：Entity History ──────────────────────────────────────────────
def _extract_top_entities(filtered_data: dict, top_n: int = 3) -> list[dict]:
    """
    从 P0 事件中按关键词命中权重提取 Top N 实体名称列表。
    返回 [{"name": "实体名", "title": "相关事件标题"}, ...]
    """
    import re
    p0 = filtered_data.get("p0", [])
    # 提取实体的启发式规则：标题中的公司/组织名（连续2字以上大写词）
    # 简化处理：直接用原始标题作为实体关键词
    entities = []
    for e in p0[:top_n]:
        title = e.get("title", "")
        # 取标题前8个字作为实体标识
        name = title[:8].strip()
        if name:
            entities.append({"name": name, "title": title})
    return entities


def _retrieve_entity_history(entity_name: str, days: int = 90) -> str:
    """
    查询某实体近 N 天的相关事件摘要。
    返回格式化的历史轨迹字符串，如无记录返回空字符串。
    """
    try:
        from database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        time_threshold = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("""
            SELECT title, published_date
            FROM events
            WHERE published_date >= %s
              AND (title LIKE %s OR summary LIKE %s)
            ORDER BY published_date DESC
            LIMIT 5
        """, (time_threshold, f"%{entity_name[:4]}%", f"%{entity_name[:4]}%"))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return f"- {entity_name}：近{days}天无重大动作记录"
        summaries = [f"{row['published_date'][:10]}：{row['title'][:30]}" for row in rows[:3]]
        return f"- {entity_name}：{'；'.join(summaries)}"
    except Exception:
        return f"- {entity_name}：近{days}天无重大动作记录"


def _build_history_context(filtered_data: dict, top_n: int = 3) -> str:
    """构建历史轨迹参考上下文"""
    entities = _extract_top_entities(filtered_data, top_n)
    if not entities:
        return "（无实体历史轨迹数据）"
    parts = [_retrieve_entity_history(e["name"]) for e in entities]
    valid_parts = [p for p in parts if p and "无重大动作" not in p]
    if not valid_parts:
        return "（近3个月无重大动作记录）"
    return "\n".join(valid_parts)
def _build_context(filtered_data: dict, paper_highlight: str, report_type: str, industry_report: str = "") -> str:
    """构建 LLM 上下文字符串"""
    lines = []

    # P0 事件（全部）
    p0 = filtered_data.get("p0", [])
    p1 = filtered_data.get("p1", [])
    p2_brief = filtered_data.get("p2_brief", [])

    for i, e in enumerate(p0, 1):
        lines.append(f"[P0-{i}] {e['title']}")
        if e.get("summary"):
            lines.append(f"  摘要: {e['summary'][:200]}")
        if e.get("source_url"):
            lines.append(f"  来源: {e['source_url']}")
        lines.append("")

    # P1 事件（Top3）
    for i, e in enumerate(p1, 1):
        lines.append(f"[P1-{i}] {e['title']}")
        if e.get("summary"):
            lines.append(f"  摘要: {e['summary'][:200]}")
        if e.get("source_url"):
            lines.append(f"  来源: {e['source_url']}")
        lines.append("")

    # P2 附录（不展开）
    if p2_brief:
        lines.append("【附录：其他值得关注】")
        for e in p2_brief:
            lines.append(f"  - {e['title']} ({e['published_date'][:10]})")

    context = "\n".join(lines)
    return context


def _run_synthesizer(filtered_data: dict, paper_highlight: str,
                      report_type: str, report_title: str, industry_report: str = "") -> str:
    """战略脑图合成：调用 LLM 生成报告"""
    from style_prompt import REPORTER_SYSTEM_PROMPT

    context = _build_context(filtered_data, paper_highlight, report_type, industry_report)
    history_context = _build_history_context(filtered_data, top_n=3)
    system_prompt = REPORTER_SYSTEM_PROMPT.format(report_title=report_title)

    user_prompt = f"""请分析以下情报，撰写{report_title}，严格遵循系统提示词的语言风格和排版规范。\n行业竞争格局：{industry_report if industry_report else "（非行业报告）"}
【重要】请严格按"第一步通读→第二步全局推演→第三步展开"的顺序执行。

【历史轨迹参考】（分析战略判词时必须结合此信息，判断是延续还是转向）
{history_context}

【情报内容】
{context}

【今日论文】（如无相关内容可跳过）
{paper_highlight}

【行业竞争格局】（P2-1，仅 industry 报告类型）
{industry_report}
"""

    log(f"[Synthesizer] 正在呼叫 MiniMax-M2.7-highspeed...")

    try:
        client = _get_anthropic_client()
        message = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        )

        final_text = ""
        log("-" * 50)
        for block in message.content:
            if block.type == "thinking":
                log(f"[思考] {block.thinking[:100]}...")
            elif block.type == "text":
                final_text += block.text
                log(f"[生成] 文本块完成")
        log("-" * 50)
        return final_text

    except Exception as e:
        log(f"[Synthesizer] LLM 调用失败: {e}")
        return None


# ── Pipeline Stage 4: Distributors ─────────────────────────────────────────
def send_feishu_card(markdown_content: str, title_text: str):
    """飞书分发"""
    if not FEISHU_WEBHOOK_URL:
        log("[Feishu] 未配置 FEISHU_WEBHOOK_URL，跳过")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "indigo",
                "title": {"content": f"⚡️ 产业追踪雷达 | {title_text}", "tag": "plain_text"},
            },
            "elements": [
                {"tag": "markdown", "content": markdown_content},
                {"tag": "hr"},
                {"tag": "note", "elements": [
                    {"tag": "plain_text", "content": f"🤖 MiniMax-M2.7-highspeed 战略参谋驱动 | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
                ]},
            ],
        },
    }

    log(f"[Feishu] 正在推送【{title_text}】...")
    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=payload, timeout=15)
        resp.raise_for_status()
        log(f"[Feishu] 推送成功: {resp.json().get('msg')}")
    except Exception as e:
        log(f"[Feishu] 推送失败: {e}")


def send_wechat_draft(title: str, author: str, markdown_content: str):
    """微信草稿箱分发"""
    try:
        from wechat_draft_sender import send_to_draft
        import os
        cover_path = os.path.join(os.path.dirname(__file__), "data", "wechat_cover.png")
        log(f"[WeChat] 正在写入草稿箱【{title}】...")
        result = send_to_draft(title=title, author=author, markdown_content=markdown_content, cover_image_path=cover_path)
        log(f"[WeChat] 草稿创建成功: {result}")
    except ValueError as e:
        log(f"[WeChat] 跳过（无封面图）: {e}")
    except Exception as e:
        log(f"[WeChat] 草稿创建失败: {e}")


# ── 主入口 ─────────────────────────────────────────────────────────────────

# ── P2-1: 行业情报周刊 ────────────────────────────────────────────────────────
def _run_industry_report(days: int = 7) -> str:
    """
    按行业聚类输出周刊补充上下文
    行业划分：COMPETES_WITH 关系中的竞争对手群体
    """
    from database_pg import get_connection
    from datetime import datetime, timezone, timedelta
    import json

    conn = get_connection()
    cur = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # 获取所有有 COMPETES_WITH 关系的公司
    cur.execute("""
        SELECT DISTINCT e.id, e.name, e.type
        FROM entities e
        JOIN relationships r ON (e.id = r.source_id OR e.id = r.target_id)
        WHERE r.relation_type = 'COMPETES_WITH' AND e.type IN ('company', 'product')
        LIMIT 50
    """)
    companies = {row["id"]: row["name"] for row in cur.fetchall()}

    if not companies:
        conn.close()
        return ""

    entity_ids = list(companies.keys())

    # 获取本周这些公司的事件
    cur.execute("""
        SELECT e.id, e.title, e.date, e.summary, e.risk_level, e.involved_entities_json
        FROM events e
        WHERE e.date >= %s
        ORDER BY e.date DESC
        LIMIT 100
    """, (cutoff,))

    events = []
    for row in cur.fetchall():
        events.append(dict(row))

    # 把事件分配到行业（公司）
    company_events = {eid: [] for eid in entity_ids}
    for event in events:
        involved = []
        try:
            involved = json.loads(event.get("involved_entities_json") or "[]")
        except:
            pass

        for eid in entity_ids:
            if eid in involved:
                risk = event.get("risk_level", "")
                risk_icon = "🔴" if risk == "P0" else ("⚠️" if risk == "P1" else "🟢")
                company_events[eid].append({
                    "title": event.get("title", ""),
                    "date": event.get("date", ""),
                    "summary": (event.get("summary") or "")[:80],
                    "risk_icon": risk_icon,
                    "risk": risk,
                })
                break  # 一个事件只归属一个公司

    # 找有事件的公司，按事件数排序
    active_companies = [(eid, events_list) for eid, events_list in company_events.items() if events_list]
    active_companies.sort(key=lambda x: len(x[1]), reverse=True)

    lines = []
    lines.append("")
    lines.append("【行业竞争格局补充】（基于 COMPETES_WITH 关系）")
    lines.append("")

    for eid, evts in active_companies[:8]:
        name = companies[eid]
        lines.append(f"## {name}（{len(evts)}条本周事件）")

        p0_evts = [e for e in evts if e["risk"] == "P0"]
        p1_evts = [e for e in evts if e["risk"] == "P1"]
        other_evts = [e for e in evts if e["risk"] not in ("P0", "P1")]

        if p0_evts:
            lines.append("🔴 核心动态:")
            for e in p0_evts[:3]:
                lines.append(f"  - {e['risk_icon']} {e['title']} ({e['date'][:10]})")
        if p1_evts:
            lines.append("⚠️ 重要进展:")
            for e in p1_evts[:2]:
                lines.append(f"  - {e['risk_icon']} {e['title']} ({e['date'][:10]})")
        if other_evts:
            for e in other_evts[:2]:
                lines.append(f"  - {e['risk_icon']} {e['title']}")
        lines.append("")

    conn.close()

    if not active_companies:
        return ""

    return "\n".join(lines)

    """
    按行业聚类输出周刊补充上下文
    行业划分：COMPETES_WITH 关系形成的竞争群体
    """
    from database_pg import get_connection
    from datetime import datetime, timezone, timedelta

    conn = get_connection()
    cur = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Step 1: 找出所有竞争群体（COMPETES_WITH 图的连通分量）
    # 用 PostgreSQL 的递归 CTE 找连通分量
    cur.execute("""
        WITH RECURSIVE comp_graph AS (
            -- 基础：所有参与 COMPETES_WITH 的实体
            SELECT DISTINCT source_id as entity_id FROM relationships WHERE relation_type = 'COMPETES_WITH'
            UNION
            SELECT DISTINCT target_id FROM relationships WHERE relation_type = 'COMPETES_WITH'
        ),
        connected AS (
            SELECT DISTINCT r1.source_id as e1, r1.target_id as e2
            FROM relationships r1
            WHERE r1.relation_type = 'COMPETES_WITH'
        ),
        clusters AS (
            SELECT entity_id, cluster_id
            FROM (
                SELECT entity_id,
                       SUM(is_new_cluster) OVER (ORDER BY entity_id) + 1 as cluster_id
                FROM (
                    SELECT entity_id,
                           CASE WHEN lag_entity IS NULL OR
                                NOT EXISTS (SELECT 1 FROM connected c2
                                           WHERE c2.e1 = lag_entity AND c2.e2 = connected.e1
                                              OR c2.e2 = lag_entity AND c2.e1 = connected.e1)
                           THEN 1 ELSE 0 END as is_new_cluster
                    FROM (
                        SELECT entity_id,
                               LAG(entity_id) OVER (ORDER BY entity_id) as lag_entity
                        FROM comp_graph
                    ) sub
                ) sub2
            ) clusters_with_id
        )
        SELECT cluster_id, ARRAY_AGG(entity_id) as companies
        FROM clusters
        GROUP BY cluster_id
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
        LIMIT 20
    """)

    clusters = []
    for row in cur.fetchall():
        clusters.append({
            "cluster_id": row["cluster_id"],
            "entity_ids": row["entity_ids"] if hasattr(row, "entity_ids") else row[1]
        })

    if not clusters:
        conn.close()
        return ""

    # Step 2: 获取集群中每个实体的名称
    all_entity_ids = []
    for c in clusters:
        all_entity_ids.extend(c["entity_ids"])

    cur.execute("""
        SELECT id, name, type FROM entities WHERE id = ANY(%s)
    """, (all_entity_ids,))
    entity_names = {row["id"]: row["name"] for row in cur.fetchall()}

    # Step 3: 获取本周事件
    cur.execute("""
        SELECT e.id, e.title, e.date, e.summary, e.risk_level, e.involved_entities_json
        FROM events e
        WHERE e.date >= %s
        ORDER BY e.date DESC
    """, (cutoff,))

    events = []
    for row in cur.fetchall():
        events.append(dict(row))

    # Step 4: 把事件分配到行业集群
    for cluster in clusters:
        cluster["events"] = []

    for event in events:
        involved = []
        try:
            involved = json.loads(event.get("involved_entities_json") or "[]")
        except:
            pass

        if not involved:
            continue

        # 检查这个事件是否涉及某个集群的公司
        for cluster in clusters:
            cluster_ids = set(cluster["entity_ids"])
            event_entities = set(involved)
            overlap = cluster_ids & event_entities
            if overlap:
                # 事件属于这个行业
                risk = event.get("risk_level", "")
                risk_icon = "🔴" if risk == "P0" else ("⚠️" if risk == "P1" else "🟢")
                cluster["events"].append({
                    "title": event.get("title", ""),
                    "date": event.get("date", ""),
                    "summary": (event.get("summary") or "")[:100],
                    "risk": risk,
                    "risk_icon": risk_icon,
                })
                break  # 一个事件只属于一个行业

    # Step 5: 生成分组文本
    lines = []
    lines.append("")
    lines.append("【行业竞争格局补充】")
    lines.append("")

    industry_count = 0
    for cluster in clusters:
        if not cluster["events"]:
            continue

        # 获取行业成员名称
        names = [entity_names.get(eid, eid) for eid in cluster["entity_ids"][:5]]
        industry_name = " / ".join(names) if names else f"行业{cluster['cluster_id']}"

        lines.append(f"## {industry_name}（{len(cluster['events'])}条本周事件）")

        # 按风险分组
        p0_events = [e for e in cluster["events"] if e["risk"] == "P0"]
        p1_events = [e for e in cluster["events"] if e["risk"] == "P1"]
        other_events = [e for e in cluster["events"] if e["risk"] not in ("P0", "P1")]

        if p0_events:
            lines.append("🔴 核心动态:")
            for e in p0_events[:3]:
                lines.append(f"  - {e['risk_icon']} {e['title']} ({e['date'][:10]})")

        if p1_events:
            lines.append("⚠️ 重要进展:")
            for e in p1_events[:2]:
                lines.append(f"  - {e['risk_icon']} {e['title']} ({e['date'][:10]})")

        if other_events:
            lines.append("其他动态:")
            for e in other_events[:2]:
                lines.append(f"  - {e['risk_icon']} {e['title']}")

        lines.append("")
        industry_count += 1

        if industry_count >= 5:
            break

    conn.close()

    if industry_count == 0:
        return ""

    return "\n".join(lines)


REPORT_CONFIG = {
    "daily":   {"days": 1,  "title": "每日战略简报",   "max_events": 50},
    "weekly":  {"days": 7,  "title": "每周深度内参",   "max_events": 80},
    "monthly": {"days": 30, "title": "月度产业观察",   "max_events": 150},
    "industry": {"days": 7, "title": "行业竞争格局周刊", "max_events": 80},
}


def run_report(report_type: str = "daily", author: str = "kangchen") -> bool:
    """
    执行完整 Pipeline：
    Filter → Paper Plugin → Synthesizer → Feishu + WeChat
    """
    config = REPORT_CONFIG.get(report_type, REPORT_CONFIG["daily"])
    days = config["days"]
    title = config["title"]
    max_events = config["max_events"]

    log(f"=== [{title}] Pipeline 启动 (days={days}) ===")

    # Stage 1: Filter
    filtered = _run_filter(days)
    if not filtered["p0"] and not filtered["p1"]:
        log(f"[{title}] P0+P1 均为空，跳过本次报告")
        return False

    # Stage 2: Paper
    paper = _run_paper_plugin(days)

    # Stage 2.5: Industry Report (P2-1)
    industry = _run_industry_report(days)

    # Stage 3: Synthesizer
    report_content = _run_synthesizer(filtered, paper, report_type, title, industry)
    if not report_content:
        log(f"[{title}] 报告生成失败，熔断不推送")
        return False

    # Stage 4: Distribute（飞书 + 微信完全独立，互不阻塞）
    # 飞书推送
    try:
        send_feishu_card(report_content, title)
    except Exception as e:
        log(f"[{title}] 飞书推送异常: {e}")

    # 微信草稿箱推送（所有报告类型均尝试）
    try:
        send_wechat_draft(f"【{title}】{datetime.now().strftime('%Y-%m-%d')}", author, report_content)
    except Exception as e:
        log(f"[{title}] 微信草稿箱推送异常: {e}")

    log(f"=== [{title}] Pipeline 完成 ===")
    return True


if __name__ == "__main__":
    report_type = sys.argv[1].lower() if len(sys.argv) > 1 else "daily"
    run_report(report_type)
