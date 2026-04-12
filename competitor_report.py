#!/usr/bin/env python3
"""
AI Tracker System - 竞品分析报告生成器
输入一家公司 -> 查询所有 COMPETES_WITH 关系 -> 拉取关联事件 -> LLM 生成结构化竞品分析
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(__file__))

from database import get_connection
from dotenv import load_dotenv
import anthropic

load_dotenv()

def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("未配置 ANTHROPIC_API_KEY 或 MINIMAX_API_KEY")
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
        timeout=120.0,
    )


def get_company_competitors(entity_id: str) -> List[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.source_id, r.target_id, r.relation_type,
               e.id AS competitor_id, e.name AS competitor_name, e.type AS competitor_type,
               e.description AS competitor_desc, e.attributes_json
        FROM relationships r
        JOIN entities e ON (
            (r.source_id = %s AND r.target_id = e.id) OR
            (r.target_id = %s AND r.source_id = e.id)
        )
        WHERE r.relation_type = %s
    """, (entity_id, entity_id, "COMPETES_WITH"))
    competitors = []
    for row in cur.fetchall():
        competitors.append({
            "competitor_id": row["competitor_id"],
            "competitor_name": row["competitor_name"],
            "competitor_type": row["competitor_type"],
            "competitor_desc": row["competitor_desc"] or "",
            "attributes_json": row["attributes_json"] or "{}",
        })
    conn.close()
    return competitors


def get_entity_info(entity_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, description, attributes_json FROM entities WHERE id = %s", (entity_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "description": row["description"] or "",
        "attributes_json": row["attributes_json"] or "{}",
    }


def get_entity_events(entity_ids: List[str], days: int = 90) -> Dict[str, List[dict]]:
    if not entity_ids:
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_connection()
    cur = conn.cursor()
    like_patterns = ['%"{}"'.format(eid) for eid in entity_ids]
    placeholders = " OR ".join(["involved_entities_json LIKE %s" for _ in like_patterns])
    query = """
        SELECT id, title, date, summary, risk_level, sentiment, involved_entities_json
        FROM events
        WHERE published_date >= %s AND ({})
        ORDER BY date DESC
    """.format(placeholders)
    params = [cutoff] + like_patterns
    cur.execute(query, params)
    events_by_entity = {eid: [] for eid in entity_ids}
    for row in cur.fetchall():
        involved = row["involved_entities_json"] or "[]"
        try:
            involved_list = json.loads(involved)
        except json.JSONDecodeError:
            involved_list = []
        for eid in entity_ids:
            if eid in involved_list:
                events_by_entity[eid].append({
                    "title": row["title"],
                    "date": row["date"],
                    "summary": (row["summary"] or "")[:200],
                    "risk_level": row["risk_level"],
                    "sentiment": row["sentiment"],
                })
                break
    conn.close()
    return events_by_entity


def generate_competitor_report(company_name: str, company_desc: str,
                                competitors: List[dict],
                                events_by_competitor: dict) -> str:
    competitor_sections = []
    for c in competitors:
        c_events = events_by_competitor.get(c["competitor_id"], [])
        events_text = "\n".join([
            "  - [{}] {}{}".format(e['date'][:10], e['title'], ' (P0)' if e['risk_level']=='P0' else '')
            for e in c_events
        ]) or "  近 90 天无重大动态"
        try:
            attrs = json.loads(c["attributes_json"])
        except json.JSONDecodeError:
            attrs = {}
        competitor_sections.append("""
### {}
- 简介: {}
- 属性: {}
- 近 90 天动态:
{}
""".format(
    c['competitor_name'],
    c['competitor_desc'][:100] or '暂无描述',
    json.dumps(attrs, ensure_ascii=False)[:200],
    events_text
))

    competitor_text = "\n".join(competitor_sections)

    system_prompt = "你是一个顶尖的产业情报分析师，精通 AI 行业竞争格局分析。你的任务是对给定公司的竞品进行结构化分析，输出高质量的战略简报。"

    user_prompt = """## 任务
对【{}】进行深度竞品分析，生成结构化报告。

## 主公司信息
- 名称: {}
- 描述: {}

## 竞品列表及动态（近 90 天）
{}

## 输出要求
请严格按以下结构输出 Markdown 报告：

# 【竞品分析】{}

## 一、竞品格局总览

## 二、核心竞品档案

## 三、近期动态对比

## 四、战略洞察

## 五、风险提示

---
报告使用中文，语言简洁专业，适合高管阅读。
""".format(
    company_name,
    company_name,
    company_desc[:200] or '暂无描述',
    competitor_text,
    company_name
)

    print("[竞品报告] 正在为 {} 生成竞品分析...".format(company_name))

    try:
        client = _get_client()
        message = client.messages.create(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        )
        final_text = ""
        for block in message.content:
            if block.type == "text":
                final_text += block.text
        return final_text
    except Exception as e:
        print("[竞品报告] LLM 调用失败: {}".format(e))
        return None


def send_report(report_content: str, company_name: str):
    title = "{} 竞品分析".format(company_name)
    timestamp = datetime.now().strftime("%Y-%m-%d")

    try:
        FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")
        if FEISHU_WEBHOOK_URL:
            import requests
            payload = {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True, "enable_forward": True},
                    "header": {
                        "template": "purple",
                        "title": {"content": "竞品追踪 | {}".format(company_name), "tag": "plain_text"},
                    },
                    "elements": [
                        {"tag": "markdown", "content": report_content},
                        {"tag": "hr"},
                        {"tag": "note", "elements": [
                            {"tag": "plain_text", "content": "MiniMax-M2.7-highspeed 战略参谋驱动 | 生成于 {}".format(timestamp)}
                        ]},
                    ],
                },
            }
            resp = requests.post(FEISHU_WEBHOOK_URL, headers={"Content-Type": "application/json"}, json=payload, timeout=15)
            resp.raise_for_status()
            print("[飞书] 推送成功")
        else:
            print("[飞书] 未配置 FEISHU_WEBHOOK_URL，跳过")
    except Exception as e:
        print("[飞书] 推送失败: {}".format(e))

    try:
        from wechat_draft_sender import send_to_draft
        cover_path = os.path.join(os.path.dirname(__file__), "data", "wechat_cover.png")
        result = send_to_draft(
            title="【竞品分析】{} | {}".format(company_name, timestamp),
            author="AI Tracker",
            markdown_content=report_content,
            cover_image_path=cover_path
        )
        print("[微信] 草稿推送结果: {}".format(result))
    except Exception as e:
        print("[微信] 草稿推送失败: {}".format(e))


def run_competitor_report(entity_id: str, push: bool = True) -> str:
    print("\n" + "="*60)
    print("[竞品分析] 目标公司 entity_id={}".format(entity_id))

    company = get_entity_info(entity_id)
    if not company:
        print("[竞品分析] 未找到 entity_id={}".format(entity_id))
        return None
    print("[竞品分析] 锁定目标: {}".format(company['name']))

    competitors = get_company_competitors(entity_id)
    if not competitors:
        print("[竞品分析] {} 没有 COMPETES_WITH 竞品关系，跳过".format(company['name']))
        return None
    print("[竞品分析] 找到 {} 家竞品".format(len(competitors)))

    competitor_ids = [c["competitor_id"] for c in competitors]
    events_by_competitor = get_entity_events(competitor_ids, days=90)

    report = generate_competitor_report(
        company["name"],
        company["description"],
        competitors,
        events_by_competitor
    )

    if not report:
        print("[竞品分析] 报告生成失败")
        return None

    print("[竞品分析] 报告生成成功，长度: {} 字".format(len(report)))

    if push:
        send_report(report, company["name"])

    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="竞品分析报告生成")
    parser.add_argument("entity_id", help="目标公司的 entity_id")
    parser.add_argument("--no-push", action="store_true", help="仅生成，不推送")
    args = parser.parse_args()
    report = run_competitor_report(args.entity_id, push=not args.no_push)
    if report:
        print("\n=== 报告内容 ===")
        print(report[:500])