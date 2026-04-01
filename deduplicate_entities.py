#!/usr/bin/env python3
"""
deduplicate_entities.py — 实体去重脚本
对每组 name+type 相同的实体，保留最完整的一个，其余合并到它身上。
"""
import sqlite3, json
from datetime import datetime

DB = "ai_tracker.db"

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
            if desc and desc != 'null' and len(str(desc)) > 5: score += 2
            if attrs_str and attrs_str != 'null':
                try:
                    try:
                        attrs = json.loads(attrs_str)
                    except json.JSONDecodeError:
                        attrs = {}
                    score += len([v for v in attrs.values() if v and str(v) not in ('[]', '{}', 'null', 'None', '')])
                except: pass
            return score

        scored = [(r, completeness(r)) for r in rows]
        scored.sort(key=lambda x: x[1], reverse=True)

        keep_id = scored[0][0][0]   # 最完整的保留
        dup_ids = [r[0] for r, _ in scored[1:]]  # 其余的是副本

        print(f"  【{name}】({etype}) x{cnt} → 保留 {keep_id}，合并 {len(dup_ids)} 个副本")

        # 1. 处理 relationships：先把副本的独立关系嫁接到保留ID上
        #    规则：只迁移副本独有的关系（保留ID没有同类型指向同target的）
        for dup_id in dup_ids:
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

        # 2. 更新 events 表的 involved_entities_json
        c.execute("SELECT id, involved_entities_json FROM events")
        for event_id, json_str in c.fetchall():
            if not json_str or json_str == 'null': continue
            try:
                try:
                    ids = json.loads(json_str)
                except json.JSONDecodeError:
                    ids = []
                if dup_id in ids:
                    ids = [keep_id if i == dup_id else i for i in ids]
                    # 去重
                    seen, unique_ids = set(), []
                    for i in ids:
                        if i not in seen: seen.add(i); unique_ids.append(i)
                    c.execute("UPDATE events SET involved_entities_json = ? WHERE id = ?",
                             (json.dumps(unique_ids), event_id))
            except: pass

        # 3. 合并 attributes：副本中的额外属性合并到保留实体
        c.execute("SELECT attributes_json FROM entities WHERE id = ?", (keep_id,))
        keep_attrs_str = c.fetchone()[0]
        try:
            keep_attrs = json.loads(keep_attrs_str) if keep_attrs_str and keep_attrs_str not in ('null', '') else {}
        except json.JSONDecodeError:
            keep_attrs = {}

        for dup_id in dup_ids:
            c.execute("SELECT attributes_json FROM entities WHERE id = ?", (dup_id,))
            dup_attrs_str = c.fetchone()[0]
            if dup_attrs_str and dup_attrs_str not in ('null', ''):
                try:
                    try:
                        dup_attrs = json.loads(dup_attrs_str)
                    except json.JSONDecodeError:
                        dup_attrs = {}
                    for k, v in dup_attrs.items():
                        if k not in keep_attrs or keep_attrs[k] in (None, '', '[]'):
                            keep_attrs[k] = v
                except: pass

        new_attrs_json = json.dumps(keep_attrs, ensure_ascii=False)

        # 4. 合并 description：保留最长的非空描述
        c.execute("SELECT description FROM entities WHERE id = ?", (keep_id,))
        keep_desc = c.fetchone()[0] or ''
        for dup_id in dup_ids:
            c.execute("SELECT description FROM entities WHERE id = ?", (dup_id,))
            dup_desc = c.fetchone()[0] or ''
            if len(dup_desc) > len(keep_desc) and dup_desc not in ('', 'null', 'None'):
                keep_desc = dup_desc

        c.execute("UPDATE entities SET description = ?, attributes_json = ? WHERE id = ?",
                 (keep_desc, new_attrs_json, keep_id))

        # 5. 删除副本
        placeholders = ','.join('?' * len(dup_ids))
        c.execute(f"DELETE FROM entities WHERE id IN ({placeholders})", dup_ids)

        total_merged += len(dup_ids)

    conn.commit()
    print(f"\n✅ 去重完成！共合并 {total_merged} 个重复实体副本。")
    conn.close()

if __name__ == "__main__":
    merge_entities()
