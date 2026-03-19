#!/usr/bin/env python3
"""
AI Tracker System - Neo4j 图数据库连接客户端
负责与底层图谱引擎通信，执行 Cypher 查询。
"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# 从环境变量或写死的默认值中读取 Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "openclaw2026")

class Neo4jClient:
    def __init__(self, uri, user, password):
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            # 测试连接
            self.driver.verify_connectivity()
            print("🕸️ ✅ 成功连接到 Neo4j 图谱引擎！")
        except Exception as e:
            print(f"🕸️ ❌ Neo4j 连接失败: {e}")
            self.driver = None

    def close(self):
        if self.driver:
            self.driver.close()

    def execute_query(self, query, parameters=None):
        """通用 Cypher 查询接口"""
        if not self.driver:
            raise Exception("Neo4j 驱动未初始化")
            
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record.data() for record in result]

    def create_constraint(self):
        """初始化约束：确保实体 ID 是唯一且带索引的，极大提升检索速度"""
        query = "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE"
        try:
            self.execute_query(query)
            print("🕸️ ✅ 图谱索引约束已建立")
        except Exception as e:
            print(f"🕸️ ⚠️ 图谱索引可能已存在: {e}")

# 全局单例
neo_db = Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

if __name__ == "__main__":
    # 测试运行
    neo_db.create_constraint()
    neo_db.close()