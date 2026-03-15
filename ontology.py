#!/usr/bin/env python3
"""
AI与数据产业智能跟踪系统 - 核心本体数据模型

采用类似 Palantir 的本体架构（实体-关系-事件）
用于构建AI产业的公司、产品、人物、技术概念数据库

作者: AI Tracker System Team
版本: 1.1.0
"""

from datetime import datetime
from typing import Optional, List, Union, Annotated, Literal
from uuid import uuid4
import enum
import pydantic
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# 枚举类型 (Enum Types) - 必须在前，因为其他模型依赖
# ============================================================================

class RelationType(str, enum.Enum):
    """关系类型枚举"""
    FOUNDED = "FOUNDED"           # 创立
    ACQUIRED = "ACQUIRED"        # 被收购
    RELEASED = "RELEASED"         # 发布
    INVESTED = "INVESTED"         # 投资
    COMPETES_WITH = "COMPETES_WITH"  # 竞争
    USES = "USES"                 # 使用技术
    PARTNERS = "PARTNERS"         # 合作
    HIRES = "HIRES"               # 雇佣
    ACQUIRED_BY = "ACQUIRED_BY"   # 被...收购


class CompanyStatus(str, enum.Enum):
    """公司状态枚举"""
    ACTIVE = "active"             # 活跃
    ACQUIRED = "acquired"         # 被收购
    DEAD = "dead"                 # 关闭/死亡
    IPO = "ipo"                   # 上市


class ProductType(str, enum.Enum):
    """产品类型枚举"""
    LARGE_MODEL = "大模型"         # 大语言模型
    SAAS = "SaaS"                 # SaaS平台
    API = "API"                   # API服务
    HARDWARE = "硬件"              # 硬件
    TOOL = "工具"                  # 工具
    DATASET = "数据集"             # 数据集


class TechCategory(str, enum.Enum):
    """技术类别枚举"""
    ALGORITHM = "算法架构"         # 算法架构
    DATA_PROCESSING = "数据处理"    # 数据处理
    HARDWARE = "硬件"              # 硬件
    SECURITY = "安全"               # 安全
    APPLICATION = "应用"            # 应用


class EntityType(str, enum.Enum):
    """实体类型枚举"""
    COMPANY = "company"
    PRODUCT = "product"
    PERSON = "person"
    TECH_CONCEPT = "tech_concept"


# ============================================================================
# 基础模型 (Base Models)
# ============================================================================

class BaseNode(BaseModel):
    """
    所有节点的基类
    
    属性:
        id: 全局唯一标识符 (UUID格式)
        created_at: 创建时间戳
    """
    id: str = Field(default_factory=lambda: str(uuid4()), description="全局唯一标识符")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间戳")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2026-03-15T01:00:00"
            }
        }
    }


class BaseRelationship(BaseModel):
    """
    关系类的基类
    
    属性:
        source_id: 源实体ID
        target_id: 目标实体ID
        relation_type: 关系类型
        start_date: 关系建立时间
        end_date: 关系结束时间(可选)
    """
    source_id: str = Field(..., description="源实体ID")
    target_id: str = Field(..., description="目标实体ID")
    relation_type: RelationType = Field(..., description="关系类型")
    start_date: Optional[datetime] = Field(default=None, description="关系建立时间")
    end_date: Optional[datetime] = Field(default=None, description="关系结束时间")


# ============================================================================
# 实体模型 (Entity Models) - 使用 Pydantic V2 多态
# ============================================================================

class Entity(BaseNode):
    """
    实体基类
    
    属性:
        entity_type: 实体类型 (使用 Literal 支持多态)
        name: 实体名称
        aliases: 别名列表
        description: 实体描述
    """
    entity_type: Literal["company", "product", "person", "tech_concept"] = Field(..., description="实体类型")
    name: str = Field(..., description="实体名称")
    aliases: List[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(default="", description="实体描述")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "OpenAI",
                "aliases": ["OpenAI Inc.", "OpenAI LP"],
                "description": "人工智能研究实验室"
            }
        }
    }


class Company(Entity):
    """
    公司实体
    
    属性:
        founded_year: 成立年份
        website: 公司官网
        status: 公司状态
    """
    entity_type: Literal["company"] = Field(default="company", description="实体类型")
    founded_year: Optional[int] = Field(default=None, description="成立年份")
    website: Optional[str] = Field(default=None, description="公司官网")
    status: CompanyStatus = Field(default=CompanyStatus.ACTIVE, description="公司状态")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Anthropic",
                "founded_year": 2021,
                "website": "https://www.anthropic.com",
                "status": "active"
            }
        }
    }


class Product(Entity):
    """
    产品实体
    
    属性:
        product_type: 产品类型
        company_id: 所属公司ID
    """
    entity_type: Literal["product"] = Field(default="product", description="实体类型")
    product_type: ProductType = Field(..., description="产品类型")
    company_id: Optional[str] = Field(default=None, description="所属公司ID")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Claude",
                "product_type": "大模型",
                "company_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }
    }


class Person(Entity):
    """
    人物实体
    
    属性:
        current_title: 当前职位
    """
    entity_type: Literal["person"] = Field(default="person", description="实体类型")
    current_title: Optional[str] = Field(default=None, description="当前职位")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Sam Altman",
                "current_title": "CEO of OpenAI"
            }
        }
    }


class TechConcept(Entity):
    """
    技术概念实体
    
    属性:
        category: 技术类别
    """
    entity_type: Literal["tech_concept"] = Field(default="tech_concept", description="实体类型")
    category: TechCategory = Field(..., description="技术类别")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Transformer",
                "category": "算法架构"
            }
        }
    }


# 实体联合类型，供 AI 提取使用 (支持多态)
EntityUnion = Union[Company, Product, Person, TechConcept]


# ============================================================================
# 事件模型 (Event Models)
# ============================================================================

class Event(BaseNode):
    """
    事件基类
    
    事件是改变实体状态的源动力
    例如: 产品发布、融资、收购、发布论文等
    
    属性:
        title: 事件标题
        date: 事件实际发生时间
        published_date: 媒体报道时间
        source_url: 信息来源链接
        summary: 事件摘要
        involved_entity_ids: 参与此事件的实体ID列表
    """
    title: str = Field(..., description="事件标题")
    date: datetime = Field(..., description="事件实际发生时间（尽可能推断具体日期，若无具体日期可与报道时间一致）")
    published_date: datetime = Field(..., description="媒体报道时间或文章发布时间")
    source_url: Optional[str] = Field(default=None, description="信息来源链接")
    summary: str = Field(default="", description="事件摘要")
    involved_entity_ids: List[str] = Field(default_factory=list, description="参与此事件的实体ID列表")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "OpenAI发布GPT-4",
                "date": "2023-03-14T00:00:00",
                "published_date": "2023-03-14T10:00:00",
                "source_url": "https://openai.com/gpt-4",
                "summary": "OpenAI正式发布GPT-4多模态大模型",
                "involved_entity_ids": ["entity1", "entity2"]
            }
        }
    }


# ============================================================================
# 关系模型 (Relationship Models)
# ============================================================================

class Relationship(BaseRelationship):
    """
    关系类(边)
    
    用于描述实体之间的关系
    
    关系类型:
        - FOUNDED: 创立 (Person -> Company)
        - ACQUIRED: 被收购 (Company -> Company)
        - RELEASED: 发布 (Company -> Product)
        - INVESTED: 投资 (Company -> Company)
        - COMPETES_WITH: 竞争 (Company -> Company)
        - USES: 使用技术 (Product -> TechConcept)
        - PARTNERS: 合作 (Company -> Company)
        - HIRES: 雇佣 (Company -> Person)
        - ACQUIRED_BY: 被...收购 (Company -> Company)
    """
    pass
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "source_id": "550e8400-e29b-41d4-a716-446655440000",
                "target_id": "550e8400-e29b-41d4-a716-446655440001",
                "relation_type": "FOUNDED",
                "start_date": "2015-12-11T00:00:00"
            }
        }
    }


# ============================================================================
# AI 提取结果容器 (AI Extraction Result)
# ============================================================================

class ExtractionResult(BaseModel):
    """
    AI 单次提取的结果总包
    
    用于接收大模型的批量输出，包含:
    - entities: 提取到的所有实体
    - events: 提取到的事件
    - relationships: 提取到的实体关系
    """
    entities: List[EntityUnion] = Field(description="提取到的所有实体")
    events: List[Event] = Field(description="提取到的事件")
    relationships: List[Relationship] = Field(description="提取到的实体关系")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "entities": [
                    {
                        "name": "OpenAI",
                        "entity_type": "company",
                        "description": "人工智能研究实验室"
                    }
                ],
                "events": [
                    {
                        "title": "OpenAI发布Sora",
                        "date": "2024-02-16T00:00:00"
                    }
                ],
                "relationships": []
            }
        }
    }


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    # 测试创建公司
    company = Company(
        name="OpenAI",
        aliases=["OpenAI Inc.", "OpenAI LP"],
        description="人工智能研究实验室",
        founded_year=2015,
        website="https://openai.com",
        status=CompanyStatus.ACTIVE
    )
    print("✅ Company创建成功:")
    print(company.model_dump_json(indent=2))
    
    # 测试创建产品
    product = Product(
        name="GPT-4",
        description="多模态大语言模型",
        product_type=ProductType.LARGE_MODEL,
        company_id=company.id
    )
    print("\n✅ Product创建成功:")
    print(product.model_dump_json(indent=2))
    
    # 测试创建人物
    person = Person(
        name="Sam Altman",
        aliases=["Samuel H. Altman"],
        description="OpenAI CEO",
        current_title="CEO",
        entity_type=EntityType.PERSON
    )
    print("\n✅ Person创建成功:")
    print(person.model_dump_json(indent=2))
    
    # 测试创建技术概念
    tech = TechConcept(
        name="Transformer",
        description="注意力机制神经网络架构",
        category=TechCategory.ALGORITHM,
        entity_type=EntityType.TECH_CONCEPT
    )
    print("\n✅ TechConcept创建成功:")
    print(tech.model_dump_json(indent=2))
    
    # 测试创建事件
    event = Event(
        title="OpenAI发布GPT-4",
        date=datetime(2023, 3, 14),
        source_url="https://openai.com/gpt-4",
        summary="OpenAI正式发布GPT-4多模态大模型"
    )
    print("\n✅ Event创建成功:")
    print(event.model_dump_json(indent=2))
    
    # 测试创建关系
    relationship = Relationship(
        source_id=company.id,
        target_id=product.id,
        relation_type=RelationType.RELEASED,
        start_date=datetime(2023, 3, 14)
    )
    print("\n✅ Relationship创建成功:")
    print(relationship.model_dump_json(indent=2))
    
    # 测试 ExtractionResult
    extraction_result = ExtractionResult(
        entities=[company, product, person, tech],
        events=[event],
        relationships=[relationship]
    )
    print("\n✅ ExtractionResult创建成功:")
    print(extraction_result.model_dump_json(indent=2))
    
    print("\n" + "="*60)
    print("🎉 所有模型测试通过!")
