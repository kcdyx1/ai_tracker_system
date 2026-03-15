#!/usr/bin/env python3
"""
AI 提取引擎 (AI Extraction Engine)

使用 instructor 调用 MiniMax API 进行知识提取
"""

import os
import json
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

import instructor
from anthropic import Anthropic

from ontology import (
    ExtractionResult,
    Entity,
    Event,
    Relationship,
    Company,
    Product,
    Person,
    TechConcept,
    CompanyStatus,
    ProductType,
    TechCategory,
    RelationType,
    EntityType,
)


def create_extractor():
    """
    创建 instructor 包装的 Anthropic 客户端
    
    使用 MiniMax API (国内节点)
    """
    # 从环境变量获取 API Key
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 MINIMAX_API_KEY")
    
    # 创建 Anthropic 客户端 (使用 MiniMax 兼容的 API 端点)
    client = Anthropic(
        api_key=api_key,
        base_url="https://api.minimaxi.com/anthropic"
    )
    
    # 使用 instructor 包装客户端
    # instructor 会自动解析 JSON 响应为 Pydantic 模型
    extractor = instructor.from_anthropic(client)
    
    return extractor


def extract_knowledge(text: str) -> ExtractionResult:
    """
    从文本中提取知识
    
    Args:
        text: 输入文本
        
    Returns:
        ExtractionResult: 包含实体、事件、关系的结构化结果
    """
    extractor = create_extractor()
    
    # 构建系统提示词
    system_prompt = """你是一个专业的知识提取助手。你的任务是从给定的文本中提取结构化的知识，包括：

1. 实体 (Entities):
   - 公司 (Company): 公司名称、成立年份、官网、状态
   - 产品 (Product): 产品名称、类型、所属公司
   - 人物 (Person): 人名、职位
   - 技术概念 (TechConcept): 技术名称、类别

2. 事件 (Events):
   - 事件标题、发生时间、摘要

3. 关系 (Relationships):
   - 公司与产品: RELEASED (发布)
   - 人物与公司: FOUNDED (创立)、HIRES (雇佣)
   - 产品与技术: USES (使用技术)
   - 公司之间: INVESTED (投资)、ACQUIRED (收购)、PARTNERS (合作)、COMPETES_WITH (竞争)

【重要】ID 生成规则：
- 你必须为每个实体生成一个简短且唯一的字符串 ID（例如 'ent_01', 'ent_02', 'ent_03'）
- 在生成 Events 和 Relationships 时，source_id, target_id 和 involved_entity_ids 必须严格使用你刚才为实体生成的这些 ID
- 绝对不能使用实体名称，必须使用 ID！

请严格按照JSON格式返回结果。日期格式使用 ISO 8601 (如 2024-02-16)。"""
    
    # 使用 instructor 调用模型
    result = extractor.chat.completions.create(
        model="MiniMax-M2.5",
        max_tokens=4000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"请从以下文本中提取知识：\n\n{text}"
            }
        ],
        response_model=ExtractionResult,
    )
    
    return result


def extract_with_validation(text: str, max_retries: int = 3) -> ExtractionResult:
    """
    带验证的提取函数
    
    如果模型返回结果不符合要求，会自动重试
    """
    for attempt in range(max_retries):
        try:
            result = extract_knowledge(text)
            
            # 基本验证
            if result is None:
                raise ValueError("返回结果为空")
            
            # 确保实体不为空
            if not result.entities:
                print(f"警告: 第 {attempt + 1} 次尝试未提取到实体，正在重试...")
                continue
                
            return result
            
        except Exception as e:
            print(f"提取失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
    
    # 如果所有尝试都失败，返回空结果
    return ExtractionResult(
        entities=[],
        events=[],
        relationships=[]
    )


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    # 测试文本
    test_text = """2024年2月16日，人工智能巨头 OpenAI 正式发布了首个文生视频大模型 Sora。CEO Sam Altman 表示，这是实现 AGI 的重要一步。Sora 采用了独特的 Diffusion Transformer 架构。"""
    
    print("=" * 60)
    print("🧪 开始测试 AI 提取功能")
    print("=" * 60)
    print(f"\n📝 输入文本:\n{test_text}\n")
    
    try:
        result = extract_with_validation(test_text)
        
        print("✅ 提取成功!\n")
        print("=" * 60)
        print("📊 结构化 JSON 结果:")
        print("=" * 60)
        # 使用 model_dump_json 直接序列化，支持 datetime
        print(result.model_dump_json(indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"❌ 提取失败: {e}")
        import traceback
        traceback.print_exc()
