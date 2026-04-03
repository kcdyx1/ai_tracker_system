#!/usr/bin/env python3
"""
deduplicate_entities.py — 实体去重脚本
对每组 name+type 相同的实体，保留最完整的一个，其余合并到它身上。
"""
import sqlite3
import json
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB = "ai_tracker.db"


def _safe_json_loads(json_str: str, default=None):
    """安全地解析 JSON，避免异常被静默吞掉"""
    if not json_str or json_str in ('null', '', 'None'):
        return default if default is not None else {}
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {json_str[:50]}... 错误: {e}")
        return default if default is not None else {}


def merge_entities():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # 找出所有有重复的 (name, type) 组
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

    for name, etype, cnt in groups:
        # 找出该组所有实体ID及其完整度（description + attributes 非空字段数）
        c.execute("""
            SELECT id, description, attributes_json
            FROM entities
            WHERE name = ? AND type = ?
        """, (name, etype))
        rows = c.fetchall()

        # 计算完整度分数
        def completeness(row):
            eid, desc, attrs_str = row
            score = 0
            if desc and desc != 'null' and len(str(desc)) > 5:
                score += 2
            if attrs_str and attrs_str != 'null':
                attrs = _safe_json_loads(attrs_str, {})
                if attrs:
                    score += len([v for v in attrs.values() if v and str(v) not in ('[]', '{}', 'null', 'None', '')])
            return score

        scored = [(r, completeness(r)) for r in rows]
        scored.sort(key=lambda x: x[1], reverse=True)

        keep_id = scored[0][0][0]   # 最完整的保留
        dup_ids = [r[0] for r, _ in scored[1:]]  # 其余的是副本

        print(f"  【{name}】({etype}) x{cnt} → 保留 {keep_id}，合并 {len(dup_ids)} 个副本")

        # 1. 处理 relationships：先把副本的独立关系嫁接到保留ID上
        #    规则：只迁移副本独有的关系（保留ID没有同类型指向同target的）
        for dup_id in dup_ids:
            try:
                c.execute("SELECT source_id, target_id, relation_type FROM relationships WHERE source_id = ?", (dup_id,))
                for src, tgt, rtype in c.fetchall():
                    # 跳过已存在相同关系的情况（避免 UNIQUE 约束冲突）
                    c.execute("""
                        SELECT COUNT(*) FROM relationships
                        WHERE source_id = ? AND target_id = ? AND relation_type = ?
                    """, (keep_id, tgt, rtype))
                    if c.fetchone()[0] == 0:
                        c.execute("""
                            UPDATE relationships SET source_id = ?
                            WHERE source_id = ? AND target_id = ? AND relation_type = ?
                        """, (keep_id, dup_id, tgt, rtype))
                    else:
                        c.execute("DELETE FROM relationships WHERE source_id = ? AND target_id = ? AND relation_type = ?",
                                 (dup_id, tgt, rtype))
            except sqlite3.Error as e:
                logger.error(f"处理 source_id 关系时出错 (dup_id={dup_id}): {e}")

            try:
                c.execute("SELECT source_id, target_id, relation_type FROM relationships WHERE target_id = ?", (dup_id,))
                for src, tgt, rtype in c.fetchall():
                    c.execute("""
                        SELECT COUNT(*) FROM relationships
                        WHERE source_id = ? AND target_id = ? AND relation_type = ?
                    """, (src, keep_id, rtype))
                    if c.fetchone()[0] == 0:
                        c.execute("""
                            UPDATE relationships SET target_id = ?
                            WHERE source_id = ? AND target_id = ? AND relation_type = ?
                        """, (keep_id, src, dup_id, rtype))
                    else:
                        c.execute("DELETE FROM relationships WHERE source_id = ? AND target_id = ? AND relation_type = ?",
                                 (src, dup_id, rtype))
            except sqlite3.Error as e:
                logger.error(f"处理 target_id 关系时出错 (dup_id={dup_id}): {e}")

        # 2. 更新 events 表的 involved_entities_json
        try:
            c.execute("SELECT id, involved_entities_json FROM events")
            for event_id, json_str in c.fetchall():
                if not json_str or json_str == 'null':
                    continue
                ids = _safe_json_loads(json_str, [])
                if not isinstance(ids, list):
                    ids = []
                if dup_id in ids:
                    ids = [keep_id if i == dup_id else i for i in ids]
                    # 去重
                    seen, unique_ids = set(), []
                    for i in ids:
                        if i not in seen:
                            seen.add(i)
                            unique_ids.append(i)
                    c.execute("UPDATE events SET involved_entities_json = ? WHERE id = ?",
                             (json.dumps(unique_ids), event_id))
        except sqlite3.Error as e:
            logger.error(f"更新事件实体关联时出错: {e}")

        # 3. 合并 attributes：副本中的额外属性合并到保留实体
        keep_attrs = _safe_json_loads(
            c.execute("SELECT attributes_json FROM entities WHERE id = ?", (keep_id,)).fetchone()[0],
            {}
        )

        for dup_id in dup_ids:
            try:
                dup_attrs_str = c.execute("SELECT attributes_json FROM entities WHERE id = ?", (dup_id,)).fetchone()[0]
                dup_attrs = _safe_json_loads(dup_attrs_str, {})
                if dup_attrs:
                    for k, v in dup_attrs.items():
                        if k not in keep_attrs or keep_attrs[k] in (None, '', '[]'):
                            keep_attrs[k] = v
            except sqlite3.Error as e:
                logger.error(f"合并属性时出错 (dup_id={dup_id}): {e}")

        new_attrs_json = json.dumps(keep_attrs, ensure_ascii=False)

        # 4. 合并 description：保留最长的非空描述
        keep_desc = ''
        try:
            keep_desc = c.execute("SELECT description FROM entities WHERE id = ?", (keep_id,)).fetchone()[0] or ''
        except sqlite3.Error as e:
            logger.error(f"获取保留实体描述时出错: {e}")

        for dup_id in dup_ids:
            try:
                dup_desc = c.execute("SELECT description FROM entities WHERE id = ?", (dup_id,)).fetchone()[0] or ''
                if len(dup_desc) > len(keep_desc) and dup_desc not in ('', 'null', 'None'):
                    keep_desc = dup_desc
            except sqlite3.Error as e:
                logger.error(f"获取副本描述时出错 (dup_id={dup_id}): {e}")

        try:
            c.execute("UPDATE entities SET description = ?, attributes_json = ? WHERE id = ?",
                     (keep_desc, new_attrs_json, keep_id))
        except sqlite3.Error as e:
            logger.error(f"更新实体数据时出错 (keep_id={keep_id}): {e}")

        # 5. 删除副本
        if dup_ids:
            placeholders = ','.join('?' * len(dup_ids))
            try:
                c.execute(f"DELETE FROM entities WHERE id IN ({placeholders})", dup_ids)
                total_merged += len(dup_ids)
            except sqlite3.Error as e:
                logger.error(f"删除重复实体时出错: {e}")

    conn.commit()
    print(f"\n✅ 去重完成！共合并 {total_merged} 个重复实体副本。")
    conn.close()


if __name__ == "__main__":
    merge_entities()
