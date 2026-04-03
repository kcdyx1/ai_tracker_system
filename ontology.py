#!/usr/bin/env python3
"""
AI与数据产业智能跟踪系统 - 核心本体数据模型 (L2 深度情报版)
"""

from datetime import datetime
from typing import Optional, List, Union, Literal
from uuid import uuid4
import enum
from pydantic import BaseModel, Field

class RelationType(str, enum.Enum):
    FOUNDED = "FOUNDED"
    ACQUIRED = "ACQUIRED"
    RELEASED = "RELEASED"
    INVESTED = "INVESTED"
    COMPETES_WITH = "COMPETES_WITH"
    USES = "USES"
    PARTNERS = "PARTNERS"
    HIRES = "HIRES"
    ACQUIRED_BY = "ACQUIRED_BY"

class CompanyStatus(str, enum.Enum):
    ACTIVE = "active"
    ACQUIRED = "acquired"
    DEAD = "dead"
    IPO = "ipo"

class ProductType(str, enum.Enum):
    LARGE_MODEL = "大模型"
    SAAS = "SaaS"
    API = "API"
    HARDWARE = "硬件"
    TOOL = "工具"
    DATASET = "数据集"

class TechCategory(str, enum.Enum):
    ALGORITHM = "算法架构"
    DATA_PROCESSING = "数据处理"
    HARDWARE = "硬件"
    SECURITY = "安全"
    APPLICATION = "应用"

class EntityType(str, enum.Enum):
    COMPANY = "company"
    PRODUCT = "product"
    PERSON = "person"
    TECH_CONCEPT = "tech_concept"

class BaseNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)

class BaseRelationship(BaseModel):
    source_id: str = Field(...)
    target_id: str = Field(...)
    relation_type: RelationType = Field(...)
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)

class Entity(BaseNode):
    entity_type: Literal["company", "product", "person", "tech_concept"] = Field(...)
    name: str = Field(...)
    aliases: List[str] = Field(default_factory=list)
    description: str = Field(default="")

class Company(Entity):
    entity_type: Literal["company"] = "company"
    founded_year: Optional[int] = Field(default=None)
    website: Optional[str] = Field(default=None)
    status: CompanyStatus = Field(default=CompanyStatus.ACTIVE)

class Product(Entity):
    entity_type: Literal["product"] = "product"
    product_type: ProductType = Field(...)
    company_id: Optional[str] = Field(default=None)
    is_open_source: Optional[bool] = Field(default=None)
    license_type: Optional[str] = Field(default=None)
    parameters_size: Optional[str] = Field(default=None)
    architecture: Optional[str] = Field(default=None)
    context_window: Optional[str] = Field(default=None)
    modalities: List[str] = Field(default_factory=list)
    supported_languages: List[str] = Field(default_factory=list)
    base_model: Optional[str] = Field(default=None)
    pricing_model: Optional[str] = Field(default=None)
    deployment_options: List[str] = Field(default_factory=list)
    paper_url: Optional[str] = Field(default=None)
    github_url: Optional[str] = Field(default=None)

class Person(Entity):
    entity_type: Literal["person"] = "person"
    current_title: Optional[str] = Field(default=None)

class TechConcept(Entity):
    entity_type: Literal["tech_concept"] = "tech_concept"
    category: TechCategory = Field(...)

EntityUnion = Union[Company, Product, Person, TechConcept]

class Event(BaseNode):
    title: str = Field(..., description="事件标题")
    date: datetime = Field(..., description="事件实际发生时间")
    published_date: datetime = Field(..., description="媒体报道时间或文章发布时间")
    source_url: Optional[str] = Field(default=None, description="信息来源链接")
    summary: str = Field(default="", description="事件摘要")
    involved_entity_ids: List[str] = Field(default_factory=list, description="参与此事件的实体ID列表")
    # L2 情报榨取字段
    risk_level: Optional[str] = Field(default=None, description="风险等级：高危/中风险/低风险/无风险。仅对Top3核心事件提取，其余为null")
    sentiment: Optional[str] = Field(default=None, description="情感倾向：利好/利空/中性。仅对Top3核心事件提取，其余为null")

class Relationship(BaseRelationship):
    # L2 证据榨取字段
    evidence: Optional[str] = Field(default=None, description="关系证据：提取原文中的关键逻辑、数据或原话金句。仅对高价值关系提取，其余为null")

class ExtractionResult(BaseModel):
    entities: List[EntityUnion] = Field(description="提取到的所有实体")
    events: List[Event] = Field(description="提取到的事件")
    relationships: List[Relationship] = Field(description="提取到的实体关系")