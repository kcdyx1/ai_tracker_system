#!/usr/bin/env python3
"""
deduplicate_entities.py — 实体去重脚本 (PostgreSQL版)
对每组 name+type 相同的实体，保留最完整的一个，其余合并到它身上。
"""
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import sys
sys.path.insert(0, "/home/kangchen/.openclaw/workspace/ai_tracker_system")
from database import get_connection


def _safe_json_loads(json_str: str, default=None):
    if not json_str or json_str in ('null', '', 'None'):
        return default if default is not None else {}
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {json_str[:50]}... 错误: {e}")
        return default if default is not None else {}


def merge_entities():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT name, type, COUNT(*) as cnt
        FROM entities
        WHERE name IS NOT NULL AND name != ''
        GROUP BY name, type
        HAVING cnt > 1
    """)
    groups = c.fetchall()
    print(f"发现 {len(groups)} 组重复实体\n")

    total_merged = 0

    for row in groups:
        name = row["name"]
        etype = row["type"]
        cnt = row["cnt"]

        c.execute("""
            SELECT id, description, attributes_json
            FROM entities
            WHERE name = %s AND type = %s
        """, (name, etype))
        entity_rows = c.fetchall()

        def completeness(erow):
            eid = erow["id"]
            desc = erow["description"]
            attrs_str = erow["attributes_json"]
            score = 0
            if desc and desc != 'null' and len(str(desc)) > 5:
                score += 2
            if attrs_str and attrs_str != 'null':
                attrs = _safe_json_loads(attrs_str, {})
                if attrs:
                    score += len([v for v in attrs.values() if v and str(v) not in ('[]', '{}', 'null', 'None', '')])
            return score

        scored = [(r, completeness(r)) for r in entity_rows]
        scored.sort(key=lambda x: x[1], reverse=True)

        keep_id = scored[0][0]["id"]
        dup_ids = [r["id"] for r, _ in scored[1:]]

        print(f"  【{name}】({etype}) x{cnt} -> 保留 {keep_id}，合并 {len(dup_ids)} 个副本")

        for dup_id in dup_ids:
            try:
                c.execute("SELECT source_id, target_id, relation_type FROM relationships WHERE source_id = %s", (dup_id,))
                for rel_row in c.fetchall():
                    src, tgt, rtype = rel_row["source_id"], rel_row["target_id"], rel_row["relation_type"]
                    c.execute("""
                        SELECT COUNT(*) FROM relationships
                        WHERE source_id = %s AND target_id = %s AND relation_type = %s
                    """, (keep_id, tgt, rtype))
                    if c.fetchone()["count"] == 0:
                        c.execute("""
                            UPDATE relationships SET source_id = %s
                            WHERE source_id = %s AND target_id = %s AND relation_type = %s
                        """, (keep_id, dup_id, tgt, rtype))
                    else:
                        c.execute("DELETE FROM relationships WHERE source_id = %s AND target_id = %s AND relation_type = %s",
                                 (dup_id, tgt, rtype))
            except Exception as e:
                logger.error(f"处理 source_id 关系时出错 (dup_id={dup_id}): {e}")

            try:
                c.execute("SELECT source_id, target_id, relation_type FROM relationships WHERE target_id = %s", (dup_id,))
                for rel_row in c.fetchall():
                    src, tgt, rtype = rel_row["source_id"], rel_row["target_id"], rel_row["relation_type"]
                    c.execute("""
                        SELECT COUNT(*) FROM relationships
                        WHERE source_id = %s AND target_id = %s AND relation_type = %s
                    """, (src, keep_id, rtype))
                    if c.fetchone()["count"] == 0:
                        c.execute("""
                            UPDATE relationships SET target_id = %s
                            WHERE source_id = %s AND target_id = %s AND relation_type = %s
                        """, (keep_id, src, dup_id, rtype))
                    else:
                        c.execute("DELETE FROM relationships WHERE source_id = %s AND target_id = %s AND relation_type = %s",
                                 (src, dup_id, rtype))
            except Exception as e:
                logger.error(f"处理 target_id 关系时出错 (dup_id={dup_id}): {e}")

        try:
            c.execute("SELECT id, involved_entities_json FROM events")
            for event_row in c.fetchall():
                event_id = event_row["id"]
                json_str = event_row["involved_entities_json"]
                if not json_str or json_str == 'null':
                    continue
                ids = _safe_json_loads(json_str, [])
                if not isinstance(ids, list):
                    ids = []
                changed = False
                for i in range(len(ids)):
                    if ids[i] in dup_ids:
                        ids[i] = keep_id
                        changed = True
                if changed:
                    seen, unique_ids = set(), []
                    for i in ids:
                        if i not in seen:
                            seen.add(i)
                            unique_ids.append(i)
                    c.execute("UPDATE events SET involved_entities_json = %s WHERE id = %s",
                             (json.dumps(unique_ids), event_id))
        except Exception as e:
            logger.error(f"更新事件实体关联时出错: {e}")

        keep_attrs = _safe_json_loads(
            c.execute("SELECT attributes_json FROM entities WHERE id = %s", (keep_id,)).fetchone()["attributes_json"] or '{}',
            {}
        )

        for dup_id in dup_ids:
            try:
                dup_attrs_str = c.execute("SELECT attributes_json FROM entities WHERE id = %s", (dup_id,)).fetchone()["attributes_json"]
                dup_attrs = _safe_json_loads(dup_attrs_str, {})
                if dup_attrs:
                    for k, v in dup_attrs.items():
                        if k not in keep_attrs or keep_attrs[k] in (None, '', '[]'):
                            keep_attrs[k] = v
            except Exception as e:
                logger.error(f"合并属性时出错 (dup_id={dup_id}): {e}")

        new_attrs_json = json.dumps(keep_attrs, ensure_ascii=False)

        keep_desc = ''
        try:
            result = c.execute("SELECT description FROM entities WHERE id = %s", (keep_id,)).fetchone()
            keep_desc = result["description"] or '' if result else ''
        except Exception as e:
            logger.error(f"获取保留实体描述时出错: {e}")

        for dup_id in dup_ids:
            try:
                result = c.execute("SELECT description FROM entities WHERE id = %s", (dup_id,)).fetchone()
                dup_desc = result["description"] or '' if result else ''
                if len(dup_desc) > len(keep_desc) and dup_desc not in ('', 'null', 'None'):
                    keep_desc = dup_desc
            except Exception as e:
                logger.error(f"获取副本描述时出错 (dup_id={dup_id}): {e}")

        try:
            c.execute("UPDATE entities SET description = %s, attributes_json = %s WHERE id = %s",
                     (keep_desc, new_attrs_json, keep_id))
        except Exception as e:
            logger.error(f"更新实体数据时出错 (keep_id={keep_id}): {e}")

        if dup_ids:
            try:
                for dup_id in dup_ids:
                    c.execute("DELETE FROM entities WHERE id = %s", (dup_id,))
                    total_merged += 1
            except Exception as e:
                logger.error(f"删除重复实体时出错: {e}")

    conn.commit()
    print(f"\n 去重完成！共合并 {total_merged} 个重复实体副本。")
    conn.close()


if __name__ == "__main__":
    merge_entities()
