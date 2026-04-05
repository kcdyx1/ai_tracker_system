#!/usr/bin/env python3
"""
AI 提取引擎 (AI Extraction Engine)

使用 instructor 调用 MiniMax API 进行知识提取
"""

import os
import threading
from dotenv import load_dotenv
load_dotenv()

import json
import time
import random
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
from database import query_all_entities


# ── 可配置的限流参数 ───────────────────────────────────────────────────────────
# 环境变量可覆盖默认值
DEFAULT_API_COOLDOWN = float(os.environ.get("EXTRACTOR_API_COOLDOWN", "1.0"))  # 默认 1 秒，原 2.5 秒
MAX_API_COOLDOWN = float(os.environ.get("EXTRACTOR_MAX_COOLDOWN", "5.0"))      # 最大冷却时间


# ── 线程安全的客户端工厂 ────────────────────────────────────────────────────
_client_local = threading.local()

def _get_extractor():
    """线程安全的客户端获取（每个线程独立实例）"""
    if not hasattr(_client_local, 'client') or _client_local.client is None:
        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("请设置环境变量 MINIMAX_API_KEY")
        client = Anthropic(
            api_key=api_key,
            base_url="http://114.132.200.116:3888/"
        )
        _client_local.client = instructor.from_anthropic(client)
    return _client_local.client

def create_extractor():
    """兼容旧调用，保持接口不变"""
    return _get_extractor()


def extract_knowledge(text: str, context_entities_str: str = "") -> ExtractionResult:
    """
    从文本中提取知识

    Args:
        text: 输入文本
        context_entities_str: 现有实体上下文（用于实体对齐）

    Returns:
        ExtractionResult: 包含实体、事件、关系的结构化结果
    """
    extractor = create_extractor()

    # 构建系统提示词
    system_prompt = f"""你是一个专业的知识提取助手。你的任务是从给定的文本中提取结构化的知识，包括：

1. 实体 (Entities):
   - 公司 (Company): 公司名称、成立年份、官网、状态
   - 产品 (Product): 除名称、类型、所属公司外，【必须极力深挖】以下 AI 特征：是否开源(is_open_source)、参数量级(parameters_size)、上下文窗口(context_window)、架构(architecture)、支持模态(modalities)、底座模型(base_model)、定价模式(pricing_model)和部署方式(deployment_options)。
   - 人物 (Person): 人名、职位
   - 技术概念 (TechConcept): 技术名称、类别

2. 事件 (Events):
   - 事件标题、发生时间 (date)、报道/发布时间 (published_date)、摘要
   - 必须严格区分 date（事件真实发生的历史时间）和 published_date（这篇新闻报道发布的时间）。

3. 关系 (Relationships):
   - 公司与产品: RELEASED (发布)
   - 人物与公司: FOUNDED (创立)、HIRES (雇佣)
   - 产品与技术: USES (使用技术)
   - 公司之间: INVESTED (投资)、ACQUIRED (收购)、PARTNERS (合作)、COMPETES_WITH (竞争)

【重要】ID 生成规则：
- 你必须为每个实体生成一个简短且唯一的字符串 ID（例如 'ent_01', 'ent_02', 'ent_03'）
- 在生成 Events 和 Relationships 时，source_id, target_id 和 involved_entity_ids 必须严格使用你刚才为实体生成的这些 ID
- 绝对不能使用实体名称，必须使用 ID！

【重要】内容限制：
- 如果文本内容极其丰富，请专注于提取「最具代表性」的 15 个实体和 5 个核心事件，确保 JSON 结构的完整性。不要试图穷尽所有细节。

请严格按照JSON格式返回结果。日期格式使用 ISO 8601 (如 2024-02-16)。

{context_entities_str}

请严格按照JSON格式返回结果。"""

    # 使用 instructor 调用模型
    result = extractor.chat.completions.create(
        model="MiniMax-M2",
        max_tokens=8000,
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



def validate_extraction_result(result: ExtractionResult) -> ExtractionResult:
    """
    提取质量门禁：过滤低质量、无关、日期异常的事件
    """
    from datetime import datetime, timedelta, timezone

    # AI/科技相关关键词（用于过滤无关内容）
    ai_keywords = [
        "ai", "artificial intelligence", "machine learning", "deep learning",
        "neural network", "llm", "gpt", "claude", "openai", "anthropic",
        "模型", "人工智能", "大模型", "算法", "芯片", "gpu", "nvidia",
        "agent", "rag", "embedding", "transformer", "nlp", "cv",
        "robot", "自动驾驶", "智能体", "机器学习", "深度学习",
        "startup", "funding", " Series ", "Series A", "Series B",
        "acquisition", "merger", "ipo", "public", "launch", "release"
    ]

    # 日期边界（统一使用 UTC，避免时区比较错误）
    min_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    max_date = datetime.now(timezone.utc) + timedelta(days=7)

    valid_events = []
    for event in result.events:
        # 1. 日期校验（统一为 UTC 比较）
        event_date = None
        try:
            event_date = event.date
            if hasattr(event_date, 'year'):
                # 标准化为 UTC 时区再比较
                ed = event_date
                if ed.tzinfo is None:
                    ed = ed.replace(tzinfo=timezone.utc)
                if ed < min_date or ed > max_date:
                    print(f"过滤异常日期事件: {event.title[:30]}... (日期: {ed.year})")
                    continue
        except (ValueError, TypeError, AttributeError) as e:
            print(f"过滤日期解析失败的事件: {event.title[:30]}... 错误: {e}")
            continue

        # 1b. published_date validation (prevent LLM from using historical dates)
        try:
            pub_date = event.published_date
            if hasattr(pub_date, 'year'):
                pd = pub_date
                if pd.tzinfo is None:
                    pd = pd.replace(tzinfo=timezone.utc)
                if pd < min_date:
                    print(f"过滤异常报道日期事件: {event.title[:30]}... (报道日期: {pd.year})")
                    continue
        except (ValueError, TypeError, AttributeError):
            pass

        # 2. 相关性校验 - 检查标题和摘要是否包含AI相关关键词
        text_to_check = (event.title + " " + event.summary).lower()
        is_relevant = any(kw.lower() in text_to_check for kw in ai_keywords)
        if not is_relevant:
            # 再检查实体类型 - 如果有关联的公司/产品/技术实体，也认为是相关的
            if event.involved_entity_ids:
                # 有关联实体，保留
                pass
            else:
                print(f"⚠️ 过滤低相关事件: {event.title[:30]}...")
                continue

        # 3. 来源校验 - 有来源URL的事件优先保留
        # 这可以作为后续排序依据，这里先不过滤

        valid_events.append(event)

    print(f"✅ 质量门禁: {len(result.events)} -> {len(valid_events)} 有效事件")

    # 返回过滤后的事件
    result.events = valid_events
    return result

def extract_with_validation(text: str, max_retries: int = 5) -> ExtractionResult:
    """
    带验证与 MiniMax 强力限流保护的提取函数

    修复：使用可配置的冷却时间，减少不必要的阻塞等待
    """
    # 获取现有实体库，但只注入文本中实际提到的实体
    from database import query_all_entities # 确保在作用域内
    existing_entities = query_all_entities()
    text_lower = text.lower()

    # 过滤：只保留文本中提到的实体
    matched_entities = []
    for e in existing_entities:
        name_lower = e['name'].lower()
        # 匹配名称
        if name_lower in text_lower:
            matched_entities.append(e)
            continue
        # 匹配别名
        if e.get('aliases_json'):
            try:
                aliases = json.loads(e['aliases_json'])
                for alias in aliases:
                    if alias.lower() in text_lower:
                        matched_entities.append(e)
                        break
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    context_entities_str = ""
    if matched_entities:
        context_entities_str = "\n【现有实体库参考】(极度重要)\n如果在文本中发现以下实体（或其别名），你**必须**严格复用对应的【现有 ID】，绝对不能生成新 ID：\n"
        for e in matched_entities:
            context_entities_str += f"- 现有 ID: {e['id']} | 名称: {e['name']} | 类型: {e['type']}\n"

    for attempt in range(max_retries):
        try:
            result = extract_knowledge(text, context_entities_str)

            # 基本验证
            if result is None:
                raise ValueError("返回结果为空")

            # 确保实体不为空
            if not result.entities:
                print(f"⚠️ 第 {attempt + 1} 次尝试未提取到实体，休眠 2 秒后重试...")
                time.sleep(2)
                continue

            # ✅ 成功提取！使用可配置的冷却时间保护账户余额与并发额度
            cooldown = min(DEFAULT_API_COOLDOWN + random.uniform(0, 0.5), MAX_API_COOLDOWN)
            print(f"✅ 成功调用 MiniMax API，休眠 {cooldown:.1f} 秒以保护账户余额与并发额度...")
            time.sleep(cooldown)

            # 🛡️ 质量门禁：过滤低质量、异常日期、无关事件
            result = validate_extraction_result(result)

            return result

        except Exception as e:
            error_msg = str(e).lower()
            print(f"❌ 提取失败 (尝试 {attempt + 1}/{max_retries}): {e}")

            # 🚨 限流报错：指数退避算法
            if "429" in error_msg or "too many requests" in error_msg or "rate limit" in error_msg:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                wait_time = min(wait_time, MAX_API_COOLDOWN)  # 不超过最大冷却时间
                print(f"🛡️ 触发 MiniMax 官方限流！启动防爆盾，休眠 {wait_time:.1f} 秒后重试...")
                time.sleep(wait_time)

            # token 限制错误，减少上下文重试
            elif "length" in error_msg or "token" in error_msg:
                print("📉 检测到 token 限制，缩减上下文后休眠重试...")
                context_entities_str = ""
                time.sleep(2)

            else:
                # 其他网络波动错误
                time.sleep(2)

            if attempt == max_retries - 1:
                print("☠️ 达到最大重试次数，放弃当前文本！")
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
