# -*- coding: utf-8 -*-
"""NL Understanding Engine — 调用 MiniMax API 将自然语言转为 SQL 查询"""
import os
import re
from typing import Optional

from anthropic import Anthropic

# MiniMax API 配置
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cp-W86nFgVDO6HwjK4jGw-_WrtN_b84EFi-u7OC1fUoBEeZ-0o_4sJ9r6sCR9lRI4AbolC4QurzaniyLjdI6s9I_hYzBrbpVw2dDeiJ0tQNoTSCQGa5yO6OkX4")
MINIMAX_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
MINIMAX_MODEL = "MiniMax-M2.7-highspeed"

# NL 理解 System Prompt
NL_SYSTEM_PROMPT = """你是一个 AI Tracker 知识库的自然语言查询接口。

可用数据表结构（PostgreSQL）：
- events: id, title, summary, published_date, source_url, risk_level, sentiment, created_at
- entities: id, name, entity_type, description, created_at
- relationships: source_id, target_id, relation_type, evidence

字段说明：
- published_date: 事件发布时间（ISO格式，带时区）
- risk_level: 高危/中风险/低风险/无风险/null
- sentiment: 利好/利空/中性/null
- entity_type: Company/Product/Person/TechConcept

用户会提出关于 AI 行业动态的问题，你需要：
1. 提取关键实体（公司名、产品名、人名）
2. 识别查询的时间窗口（默认7天）
3. 判断查询类型（模型发布/投资收购/风险事件/技术动态/高管变动）
4. 生成对应的 WHERE 条件

重要约束：
- 始终加上 published_date 过滤（默认最近7天）
- 如果用户没有指定时间，默认最近7天
- 只查询 events 表，不需要关联 entities 表
- limit 固定为传入参数 limit（默认10）
- 始终返回结构化文本，不要返回 JSON

返回格式：
先说明"根据查询'xxx'，找到 N 条结果："，然后逐条列出。
"""

# 降级规则匹配模式
FALLBACK_PATTERNS = [
    (re.compile(r'(大模型|模型发布|release|launch|上线|发布)', re.I), "model_release"),
    (re.compile(r'(DeepSeek|Qwen|Kimi|ChatGPT|Claude|GPT|Gemini|Llama)', re.I), "entity"),
    (re.compile(r'(投资|融资|收购|acqui|invest)', re.I), "investment"),
    (re.compile(r'(风险|漏洞|攻击|data breach)', re.I), "risk"),
    (re.compile(r'(高管|CEO|CTO|executive)', re.I), "management"),
    (re.compile(r'(Agent|框架|dify|coze|langchain)', re.I), "agent"),
]


class NLEngine:
    """自然语言理解引擎"""

    def __init__(self):
        self.client = Anthropic(
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
        )

    def parse_question(self, question: str, limit: int = 10) -> dict:
        """
        调用 MiniMax API 理解自然语言问题，生成查询条件

        Returns:
            dict: {
                "sql": "SELECT ... WHERE ...",
                "explanation": "解析说明",
                "success": bool
            }
        """
        try:
            response = self.client.messages.create(
                model=MINIMAX_MODEL,
                max_tokens=1024,
                system=NL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": question}]
            )
            # Handle different response block types (TextBlock, ThinkingBlock, etc.)
            result_text = ""
            for block in response.content:
                if hasattr(block, 'text') and block.text:
                    result_text = block.text
                    break
                elif hasattr(block, 'type') and block.type == 'text':
                    result_text = block.text
                    break
            if not result_text:
                result_text = str(response.content)
            return self._parse_nl_response(result_text, question, limit)
        except Exception as e:
            return self._fallback_parse(question, limit, error=str(e))

    def _parse_nl_response(self, response_text: str, question: str, limit: int) -> dict:
        """解析 MiniMax 返回的文本，提取 WHERE 条件"""
        # 从响应中提取关键信息来构建 SQL
        # MiniMax 应该返回格式化的文本说明，我们会解析并构建 SQL

        explanation = []
        where_parts = []
        order_by = "ORDER BY published_date DESC"

        # 检测时间范围（默认7天）
        days = 7
        if any(w in question for w in ['一周', '七天', '最近', '近期', 'this week']):
            days = 7
        elif any(w in question for w in ['两周', '14天', '半个月']):
            days = 14
        elif any(w in question for w in ['一个月', '30天', '本月']):
            days = 30
        elif any(w in question for w in ['三个月', '90天']):
            days = 90

        where_parts.append(f"published_date >= NOW() - INTERVAL '{days} days'")

        # 关键词检测
        question_lower = question.lower()

        # 模型发布
        if any(k in question_lower for k in ['大模型', '模型发布', 'release', 'launch', '上线', '发布', 'new model']):
            model_keywords = ['GPT', 'Claude', 'Gemini', 'Llama', 'Mistral', 'Qwen', 'DeepSeek', 'Kimi', 'GLM', 'ERNIE']
            model_conditions = " OR ".join([f"(title ILIKE '%{k}%' OR summary ILIKE '%{k}%')" for k in model_keywords])
            where_parts.append(f"({model_conditions})")
            explanation.append("模型发布相关")

        # 实体名检测
        entities = ['DeepSeek', 'Qwen', 'Anthropic', 'OpenAI', 'Google', 'Meta', 'Mistral']
        for entity in entities:
            if entity.lower() in question_lower or entity in question:
                where_parts.append(f"(title ILIKE '%{entity}%' OR summary ILIKE '%{entity}%')")
                explanation.append(f"实体: {entity}")

        # 投资/收购
        if any(k in question_lower for k in ['投资', '融资', '收购', 'acquisition', 'funding', 'invest']):
            where_parts.append("(title ILIKE '%融资%' OR title ILIKE '%收购%' OR title ILIKE '%投资%' OR title ILIKE '%funding%' OR title ILIKE '%acquisition%')")
            explanation.append("投资/收购")

        # 风险事件
        if any(k in question for k in ['风险', '风险事件', '高危']):
            where_parts.append("risk_level = '高危'")
            explanation.append("高危风险")

        # 利空/利好
        if '利空' in question:
            where_parts.append("sentiment = '利空'")
            explanation.append("利空")
        elif '利好' in question:
            where_parts.append("sentiment = '利好'")
            explanation.append("利好")

        # Agent 框架
        if any(k in question_lower for k in ['agent', '框架', 'dify', 'coze', 'langchain']):
            where_parts.append("(title ILIKE '%Agent%' OR title ILIKE '%框架%' OR title ILIKE '%Dify%' OR title ILIKE '%Coze%')")
            explanation.append("Agent框架")

        # 如果没有匹配任何关键词，只做时间过滤
        if len(where_parts) == 1:
            explanation.append("综合查询")

        where_clause = " AND ".join(where_parts)

        sql = f"""
SELECT title, summary, published_date, source_url, risk_level, sentiment
FROM events
WHERE {where_clause}
{order_by}
LIMIT {limit}
        """.strip()

        return {
            "sql": sql,
            "explanation": f"查询类型: {', '.join(explanation) if explanation else '综合查询'}，时间窗口: 近{days}天",
            "success": True
        }

    def _fallback_parse(self, question: str, limit: int, error: str = None) -> dict:
        """
        降级解析：当 MiniMax API 不可用时，使用规则匹配
        """
        explanation = ["[降级模式-规则匹配]"]
        where_parts = []
        days = 7

        # 检测时间范围
        if any(w in question for w in ['一周', '七天', '最近']):
            days = 7
        elif '一个月' in question or '30天' in question:
            days = 30
        elif '三个月' in question:
            days = 90

        where_parts.append(f"published_date >= NOW() - INTERVAL '{days} days'")

        # 遍历模式
        matched = False
        for pattern, ptype in FALLBACK_PATTERNS:
            if pattern.search(question):
                if ptype == "model_release":
                    model_keywords = ['GPT', 'Claude', 'Gemini', 'Llama', 'Mistral', 'Qwen', 'DeepSeek', 'Kimi']
                    model_conds = " OR ".join([f"(title ILIKE '%{k}%' OR summary ILIKE '%{k}%')" for k in model_keywords])
                    where_parts.append(f"({model_conds})")
                    explanation.append("模型发布(规则)")
                    matched = True
                elif ptype == "entity":
                    for ent in ['DeepSeek', 'Qwen', 'Anthropic', 'OpenAI']:
                        if ent.lower() in question.lower() or ent in question:
                            where_parts.append(f"(title ILIKE '%{ent}%' OR summary ILIKE '%{ent}%')")
                            explanation.append(f"实体:{ent}(规则)")
                            matched = True
                elif ptype == "investment":
                    where_parts.append("(title ILIKE '%融资%' OR title ILIKE '%收购%' OR title ILIKE '%投资%')")
                    explanation.append("投资收购(规则)")
                    matched = True
                elif ptype == "risk":
                    where_parts.append("risk_level = '高危'")
                    explanation.append("高危风险(规则)")
                    matched = True

        if not matched:
            explanation.append("综合查询(规则)")

        where_clause = " AND ".join(where_parts)

        sql = f"""
SELECT title, summary, published_date, source_url, risk_level, sentiment
FROM events
WHERE {where_clause}
ORDER BY published_date DESC
LIMIT {limit}
        """.strip()

        return {
            "sql": sql,
            "explanation": f"{', '.join(explanation)}，时间窗口: 近{days}天（API错误: {error}）",
            "success": False,
            "degraded": True
        }


def get_nl_engine() -> NLEngine:
    return NLEngine()