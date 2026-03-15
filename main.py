#!/usr/bin/env python3
"""
AI Tracker System - 主流程入口

1. 初始化数据库
2. 调用 AI 提取新闻文本
3. 保存到数据库
4. 验证数据完整性
"""

import json
from extractor import extract_with_validation
from database import init_db, save_extraction_result, query_all_entities, query_all_events, query_all_relationships, verify_relationships_integrity


# 测试文本：最新的 AI 新闻
TEST_TEXT = """
2024年12月5日，AI 创业公司 Anthropic 宣布完成 4 亿美元融资，由 Google 领投。这轮融资使 Anthropic 的估值达到 200 亿美元。Anthropic 由前 OpenAI 研究副总裁 Dario Amodei 于 2021 年创立，核心产品是 Claude 大模型。同一天，Anthropic 发布了 Claude 3.5 新版本，进一步提升了编程能力。Google 此前已在今年早期向 Anthropic 投资了 20 亿美元。双方表示将在 AI 安全领域展开深入合作。
"""


def main():
    print("=" * 60)
    print("🚀 AI Tracker System 主流程")
    print("=" * 60)
    
    # 1. 初始化数据库
    print("\n📦 步骤 1: 初始化数据库")
    init_db()
    
    # 2. 调用 AI 提取
    print("\n🧠 步骤 2: AI 知识提取")
    print(f"📝 输入文本:\n{TEST_TEXT}")
    result = extract_with_validation(TEST_TEXT)
    
    # 3. 保存到数据库
    print("\n💾 步骤 3: 保存到数据库")
    save_extraction_result(result)
    
    # 4. 查询验证
    print("\n🔍 步骤 4: 查询验证")
    
    print("\n--- 实体表 ---")
    entities = query_all_entities()
    for e in entities:
        print(f"  ID: {e['id']}")
        print(f"    类型: {e['type']}, 名称: {e['name']}")
        print(f"    别名: {e['aliases_json']}")
        print(f"    描述: {e['description'][:50]}...")
        print()
    
    print("\n--- 事件表 ---")
    events = query_all_events()
    for ev in events:
        print(f"  ID: {ev['id']}")
        print(f"    标题: {ev['title']}")
        print(f"    日期: {ev['date']}")
        print(f"    参与实体: {ev['involved_entities_json']}")
        print(f"    摘要: {ev['summary'][:50]}...")
        print()
    
    print("\n--- 关系表 ---")
    relationships = query_all_relationships()
    for r in relationships:
        print(f"  {r['source_id']} --[{r['relation_type']}]--> {r['target_id']}")
    
    # 5. 验证关系完整性
    print("\n✅ 步骤 5: 验证关系完整性")
    integrity = verify_relationships_integrity()
    print(f"  总关系数: {integrity['total_relationships']}")
    print(f"  孤立关系数: {integrity['orphaned_relationships']}")
    if integrity['orphaned_details']:
        print("  ⚠️ 孤立关系详情:")
        for o in integrity['orphaned_details']:
            print(f"    - {o}")
    else:
        print("  🎉 所有关系 ID 都正确映射到实体!")
    
    print("\n" + "=" * 60)
    print("🎉 主流程执行完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
