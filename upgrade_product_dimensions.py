import os
import re
from pathlib import Path

def patch_ontology():
    fpath = Path("ontology.py")
    content = fpath.read_text(encoding="utf-8")

    # 新的 Product 类定义
    new_product_class = '''class Product(Entity):
    """产品实体 (包含深度AI特征)"""
    entity_type: Literal["product"] = Field(default="product", description="实体类型")
    product_type: ProductType = Field(..., description="产品类型")
    company_id: Optional[str] = Field(default=None, description="所属公司ID")

    # 深度特征字段
    is_open_source: Optional[bool] = Field(default=None, description="是否开源")
    license_type: Optional[str] = Field(default=None, description="开源协议(如Apache 2.0)")
    parameters_size: Optional[str] = Field(default=None, description="参数量级(如7B, 1.5T)")
    architecture: Optional[str] = Field(default=None, description="模型架构(如MoE, Transformer)")
    context_window: Optional[str] = Field(default=None, description="上下文窗口(如128k, 1M)")
    modalities: List[str] = Field(default_factory=list, description="支持模态(文本/图像/视频等)")
    supported_languages: List[str] = Field(default_factory=list, description="支持语言")
    base_model: Optional[str] = Field(default=None, description="底层依赖的基础模型")
    pricing_model: Optional[str] = Field(default=None, description="商业模式/定价机制")
    deployment_options: List[str] = Field(default_factory=list, description="部署方式(公有云/私有化/端侧)")
    paper_url: Optional[str] = Field(default=None, description="相关论文链接")
    github_url: Optional[str] = Field(default=None, description="开源代码仓库链接")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Claude 3.5 Sonnet",
                "product_type": "大模型",
                "context_window": "200k",
                "modalities": ["文本", "图像"]
            }
        }
    }'''

    # 使用正则替换原有的 Product 类
    content = re.sub(r'class Product\(Entity\):.*?(?=class Person\(Entity\):)', new_product_class + '\n\n\n', content, flags=re.DOTALL)
    fpath.write_text(content, encoding="utf-8")
    print("✅ ontology.py 升级完成")

def patch_database():
    fpath = Path("database.py")
    content = fpath.read_text(encoding="utf-8")

    # 1. 在 init_db 中添加 attributes_json 字段
    if "ALTER TABLE entities ADD COLUMN attributes_json" not in content:
        injection = """
    # 兼容旧数据：尝试添加 attributes_json 字段用于弹性存储
    try:
        cursor.execute("ALTER TABLE entities ADD COLUMN attributes_json TEXT")
    except:
        pass  # 字段已存在则忽略"""
        content = content.replace('try:\n        cursor.execute("ALTER TABLE events ADD COLUMN published_date TEXT")', injection + '\n\n    try:\n        cursor.execute("ALTER TABLE events ADD COLUMN published_date TEXT")')

    # 2. 修改 save_extraction_result 保存弹性属性
    old_save = """        cursor.execute(\"\"\"
            INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        \"\"\", (
            entity.id,
            entity_type,
            entity.name,
            json.dumps(entity.aliases),
            entity.description,
            entity.created_at.isoformat() if isinstance(entity.created_at, datetime) else str(entity.created_at)
        ))"""

    new_save = """        # 提取基类之外的弹性属性
        entity_dict = entity.model_dump()
        base_keys = {'id', 'entity_type', 'name', 'aliases', 'description', 'created_at'}
        attributes = {k: v for k, v in entity_dict.items() if k not in base_keys and v is not None and v != []}

        cursor.execute(\"\"\"
            INSERT OR REPLACE INTO entities (id, type, name, aliases_json, description, created_at, attributes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        \"\"\", (
            entity.id,
            entity_type,
            entity.name,
            json.dumps(entity.aliases),
            entity.description,
            entity.created_at.isoformat() if isinstance(entity.created_at, datetime) else str(entity.created_at),
            json.dumps(attributes, ensure_ascii=False)
        ))"""

    content = content.replace(old_save, new_save)
    fpath.write_text(content, encoding="utf-8")
    print("✅ database.py 升级完成")

def patch_extractor():
    fpath = Path("extractor.py")
    content = fpath.read_text(encoding="utf-8")

    old_prompt_part = "- 产品 (Product): 产品名称、类型、所属公司"
    new_prompt_part = "- 产品 (Product): 除名称、类型、所属公司外，【必须极力深挖】以下 AI 特征：是否开源(is_open_source)、参数量级(parameters_size)、上下文窗口(context_window)、架构(architecture)、支持模态(modalities)、底座模型(base_model)、定价模式(pricing_model)和部署方式(deployment_options)。"

    content = content.replace(old_prompt_part, new_prompt_part)

    # 加入防超载提示
    if "确保 JSON 结构的完整性" not in content:
        content = content.replace("你是一个专业的知识提取助手。你的任务是从给定的文本中提取结构化的知识，包括：", "你是一个专业的知识提取助手。你的任务是从给定的文本中提取结构化的知识。如果文本内容极其丰富，请专注于提取『最具代表性』的 15 个实体和 5 个核心事件，确保 JSON 结构的完整性。提取范围包括：")

    fpath.write_text(content, encoding="utf-8")
    print("✅ extractor.py 升级完成")

if __name__ == '__main__':
    patch_ontology()
    patch_database()
    patch_extractor()
