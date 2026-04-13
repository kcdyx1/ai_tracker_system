#!/usr/bin/env python3
"""
AI Tracker System - 统一情报采集器 (v2.2 双主线过滤版)

追踪主线：AI + 数据基础设施

三层过滤策略：
  Tier 1: 白名单域名 → 直接通过
  Tier 2: 综合媒体 → 需命中 AI 关键词 或 数据关键词 组合（>=2）
  Tier 3: 负面关键词 → 任何源出现都直接过滤
"""

import os
import json
import time
import random
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── HTTP Proxy (Clash Verge) ────────────────────────────────────────────────
_proxy = os.environ.get("HTTP_PROXY", "") or os.environ.get("http_proxy", "") or "http://127.0.0.1:7897"
os.environ["HTTP_PROXY"] = _proxy
os.environ["http_proxy"] = _proxy
os.environ["HTTPS_PROXY"] = _proxy
os.environ["https_proxy"] = _proxy
logger.info(f"代理已启用: {_proxy}")


CONFIG_DIR = Path(__file__).parent / "config"
FEEDS_V2_FILE = CONFIG_DIR / "feeds_v2.json"
FEEDS_UNIFIED_FILE = CONFIG_DIR / "feeds_unified.json"
HISTORY_FILE = CONFIG_DIR / "collector_history.json"
METADATA_FILE = CONFIG_DIR / "collector_metadata.json"

ARXIV_API_URL = "http://export.arxiv.org/api/query"
GITHUB_API_URL = "https://api.github.com"
HACKERNEWS_API = "https://hacker-news.firebaseio.com/v0"

# ═══════════════════════════════════════════════════════════════════
# 第一层：白名单域名 — 高质量 AI + 数据来源，直接通过
# ═══════════════════════════════════════════════════════════════════
WHITELIST_DOMAINS = {
    # ── 国际大厂 & 实验室 ─────────────────────────────
    "arxiv.org", "openai.com", "anthropic.com", "deepmind.google",
    "ai.google", "blog.google", "developers.google.com",
    "huggingface.co", "huggingface.com", "meta.ai",
    "blogs.nvidia.com", "developer.nvidia.com", "nvidia.com",
    "aws.amazon.com", "awsdeveloper.com", "azure.microsoft.com",
    "microsoft.com/research", "blogs.microsoft.com",
    "bai.com", "baidu.com", "qianwen.aliyun.com", "tongyi.aliyun.com",
    "tencent.com", "weixin.qq.com", "qq.com",
    "bytedance.com", "douyin.com", "feishu.cn", "larkoffice.com",
    "x.ai", "mistral.ai", "cohere.com", "stability.ai",
    "midjourney.com", "runwayml.com", "replicate.com",
    "together.ai", "groq.com", "perplexity.ai",
    "wandb.ai", "weights.gg", "clearml.ai", "mlflow.org",
    "modal.com", "anyscale.com", "beam.cloud", "fal.ai",
    # ── 数据基础设施 ───────────────────────────────────
    "snowflake.com", "snowflakedb.com",
    "databricks.com", "databricks.io", "spark.apache.org",
    "confluent.io", "kafka.apache.org",
    "flink.apache.org", "blink.apache.org",
    "clickhouse.com", "clickhouse.tech",
    "starrocks.com", "starrocks.io",
    "doris.apache.org",
    "apache.org", "parquet.apache.org", "iceberg.apache.org",
    "delta.io", "hudi.apache.org",
    "airflow.apache.org", "prefect.io", "mage.ai",
    "dbt.com", "getdbt.com", "sqlmesh.com",
    "fivetran.com", "airbyte.com", "meltano.com", "stitchdata.com",
    "hex.com", "ModeAnalytics", "looker.com", "thoughtspot.com",
    "tableau.com", "powerbi.microsoft.com", "quicksight.aws",
    "bigquery.google.com", "redshift.aws", "synapse.azure",
    "planet-scale.com", "neon.tech", "supabase.com", "supabase.io",
    "turso.tech", "libsql.com",
    "mongodb.com", "atlas.mongodb.com",
    "postgresq", "postgresql.org", "crunchydata.com",
    "cockroachdb.com", "yugabyte.com", "scylladb.com",
    "redis.io", "valkey.io", "dragonflydb.io",
    "neo4j.com", "neo4j.org", "memgraph.com",
    "singlestore.com", "SingleStore",
    "rockset.com", "Elastic", "elasticsearch.com",
    "weaviate.io", "Qdrant", "qdrant.tech",
    "chroma.ai", "Milvus", "milvus.io", "Zilliz", "zilliz.com",
    "pinecone.io", "LanceDB", "lancedb.com", "Marqo", "marqo.ai",
    "opensearch.org",
    "timescale.com", "influxdata.com",
    "questdb.com", "Tdengine", "taosdata.com",
    "apache-druid", "imply.io",
    # ── AI Infra ─────────────────────────────────────
    "langchain.dev", "langchain.com", "dify.ai", "coze.com", "coze.cn",
    "llamaindex.ai", "llamaindex.com", "llama.cpp",
    "ollama.ai", "ollama.com", "localai.io", "localai.gg",
    "vllm.ai", "pytorch.org", "jax.ai", "chainer.org",
    "Papers With Code", "paperswithcode.com",
    # ── 国内 AI 厂商 & 研究机构 ──────────────────────
    "zhipuai.cn", "zhipuai.com", "chatglm.cn", "chatglm.com",
    "minimax.io", "minimaxi.com", "mab.lib.xiaomi.com",
    "kimi.moonshot.cn", "moshi.moonshot.cn",
    "xunfei.cn", "xfyun.cn", "iflytek.com",
    "sensetime.com", "megvii.com", "yitu.com", "deepglint.com",
    "horizon.ai", "cambricon.com", "bitmain.com",
    "alibaba.com", "aliyun.com", "taobao.com", "alipay.com",
    "huawei.com", "huaweicloud.com", "hiqilin.huawei.com",
    "iqiyi.com", "bilibili.com",
    "xiaomi.com", "xiaomi.cn", "mi.com",
    "jd.com", "jdcache.com",
    "360.cn", "360.com", "360ai.com",
    "sina.com.cn", "weibo.com",
    # ── 学术 ─────────────────────────────────────────
    "mit.edu", "stanford.edu", "berkeley.edu", "cmu.edu",
    "ox.ac.uk", "cam.ac.uk", "ic.ac.uk", "ucl.ac.uk",
    "mila.quebec", "mila.ca", "vectorinstitute.ai",
    "allenai.org", "allenai-oai.github.io",
    "bair.berkeley.edu", "crfm.stanford.edu",
    "msra.cn", "msra.com", "turing.com",
    # ── AI 媒体 & 垂直社区 ──────────────────────────
    "jiqizhixin.com", "机器之心.com", "qbitai.com", "量子位.com",
    "leiphone.com", "ithome.com", "tmtpost.com",
    "aibase.com", "aigc.com", "woshipm.com",
    "199it.com",
    "garymarcus.substack.com", "importai.substack.com",
    "substack.com", "buttondown.email",
    "theinformation.com",
    # ── Hacker News / Reddit ─────────────────────────
    "news.ycombinator.com", "reddit.com/r/MachineLearning",
    # ── Tools / Infra ────────────────────────────────
    "github.com", "gitlab.com", "bitbucket.org",
}

# ═══════════════════════════════════════════════════════════════════
# 第二层-A：AI 关键词（中英文覆盖）
# ═══════════════════════════════════════════════════════════════════
AI_KEYWORDS = {
    # 核心 AI 概念
    "llm", "llms", "大模型", "语言模型", "基础模型", "foundation model",
    "vlm", "vision language model", "多模态", "multimodal",
    "moe", "mixture of experts", "混合专家", "slm", "端侧模型",
    "端侧ai", "edge ai", "模型蒸馏", "model compression",
    "transformer", "diffusion", "dit", "gans", "vae",
    "rl", "reinforcement learning", "强化学习",
    "rlhf", "dpo", "ppo", "reward model",
    "sft", "supervised fine-tuning", "指令微调", "instruction tuning",
    "cot", "chain of thought", "思维链", "reasoning model",
    "agi", "artificial general intelligence", "通用人工智能",
    "aigc", "生成式ai", "generative ai",
    "copilot", "ai assistant", "code assistant",
    "agent", "智能体", "ai agent", "multi-agent", "multiagent",
    "rag", "retrieval augmented", "检索增强", "graphrag",
    "knowledge graph", "知识图谱",
    "embedding", "向量化", "vector db", "vector search",
    "fine-tuning", "微调", "lora", "qlora", "adapter",
    "涌现", "emergent", "scaling law",
    "对齐", "alignment", "constitutional ai",
    "AI安全", "AI safety", "AI alignment",
    # 模型 & 产品
    "gpt", "gpt-4", "gpt-4o", "o1", "o3", "chatgpt",
    "dall-e", "sora", "whisper", "openai",
    "claude", "claude-3", "claude-4", "sonnet", "anthropic",
    "gemini", "gemma", "deepmind", "google ai",
    "llama", "llama-2", "llama-3", "llama-4", "meta-llama",
    "deepseek", "深度求索", "deepseek r1",
    "qwen", "qwen-turbo", "qwen-plus", "通义千问",
    "baichuan", "百川", "baichuan-2", "baichuan3",
    "kimi", "moonshot", "月之暗面",
    "minimax", "稀宇科技",
    "zhipu", "智谱ai", "chatglm", "glm-4",
    "spark", "科大讯飞", "iflytek", "xunfei",
    "yi", "零一", "01ai", "step", "step-2", "step-3",
    "jina", "bge", "bce", "bge embeddings",
    "m3e", "qanything",
    "rwkv",
    # 公司 & 厂商
    "openai", "anthropic", "deepmind", "mistral ai", "cohere",
    "stability ai", "midjourney", "runway", "runwayml",
    "huggingface", "langchain", "llamaindex", "dify", "coze",
    "nvidia", "英伟达", "amd", "intel ai", "tpu", "gpu",
    "databricks", "snowflake", "zilliz", "qdrant", "chroma",
    "pinecone", "weaviate", "milvus", "clickhouse",
    "阿里云", "阿里 pai", "pai.aliyun.com",
    "华为云ModelArts", "modelarts",
    "腾讯云", "tencent cloud", "tencent ai lab",
    "字节AI", "字节火山", "火山引擎", "doubao",
    "百度AI", "文心", "ernie", "飞桨", "paddlepaddle",
    "商汤", "sensecore", "旷视", "megvii",
    "依图", "yitu", "云从", "cloudwalk",
    "第四范式", "寒武纪", "cambricon",
    # 研究 & 技术
    "arxiv", "paper", "论文", "preprint",
    "icml", "neurips", "nips", "iclr", "aaai", "ijcai", "kdd",
    "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl",
    "benchmark", "pre-train", "pretrain", "post-train",
    "scaling", "scaling law", "emergent",
    "hallucination", "幻觉", "可解释性", "interpretability",
    "tool use", "tool learning", "chain-of-thought",
    "context length", "context window", "上下文窗口", "百万token",
    "inference optimization", "推理优化", "kv cache",
    "speculative decoding", "投点解码",
    "quantization", "量化", "int8", "fp8", "nf4",
    "pruning", "剪枝", "knowledge distillation", "蒸馏",
    "mixture-of-expert", "moe", "sparse mixture",
    # 开源 & 生态
    "open source", "开源", "开源模型",
    "github", "github trending", "hugging face",
    "lora", "qlora", "lorahub",
    "vllm", "text-generation-inference", "tgi", "llama.cpp",
    "ollama", "localai", "local llm", "本地部署",
    "paged attention", "attention sink",
    # AI 应用 & 场景
    "AI coding", "copilot", "cursor", "devin",
    "AI video", "视频生成", "文生视频",
    "AI voice", "voice cloning", "语音合成",
    "AI图像", "text-to-image", "文生图",
    "AI music", "AI 音乐",
    "AI PPT", "AI presentation",
    "AI gaming", "AI NPC",
    "具身智能", "robotics", "embodied ai",
    "autonomous driving", "自动驾驶",
    "AI medical", "AI 医疗", "AI pharma", "AI 制药",
    "AI security", "AI 安全", "adversarial attack",
}

# ═══════════════════════════════════════════════════════════════════
# 第二层-B：数据基础设施关键词（独立主线）
# ═══════════════════════════════════════════════════════════════════
DATA_KEYWORDS = {
    # 数据库 & 存储引擎
    "snowflake", "databricks", "spark", "apache spark",
    "clickhouse", "starrocks", "doris", "apache doris",
    "kafka", "confluent", "apache kafka",
    "flink", "apache flink",
    "iceberg", "delta lake", "apache iceberg",
    "hudi", "apache hudi",
    "parquet", "apache parquet", "orc file",
    "druid", "apache druid",
    "timescale", "influxdb", "questdb", "tdengine", "taos",
    "mongodb", "postgresql", "postgres", "cockroachdb", "yugabyte",
    "scylladb", "redis", "valkey", "dragonfly",
    "neo4j", "memgraph", "planetscale", "neon",
    "supabase", "turso", "libsql", "sqlite",
    "weaviate", "qdrant", "chroma", "milvus", "pinecone", "lancedb", "marqo",
    # 数据处理 & ETL
    "airflow", "prefect", "mage.ai", "dagster",
    "dbt", "data build tool", "sqlmesh",
    "fivetran", "airbyte", "meltano", "stitch",
    # 数据仓库 & BI
    "bigquery", "redshift", "synapse",
    "data warehouse", "数据仓库", "湖仓一体",
    "tableau", "powerbi", "quicksight", "looker", "hex", "mode analytics", "thoughtspot",
    # 数据可观测性
    "data observability", "data quality", "数据质量",
    "monte carlo", "metaplane", "bigeye", "datafold",
    # 数据集成 & 虚拟化
    "data integration", "etl", "elt", "数据集成",
    "data virtualization", "data fabric", "data mesh",
    # 向量数据库（AI+数据重叠）
    "vector database", "vector store", "向量数据库",
    "embedding", " ANN search", "近似最近邻",
    # MLOps & DataOps
    "mlops", "dataops",
    "feature store", "feature platform",
    "dvc", "mlflow", "clearml", "wandb",
    "ray", "ray distributed", "distributed training",
    "sageMaker", "vertex ai", "azure ml",
    # lakehouse & streaming
    "lakehouse", "data lake",
    "real-time data", "streaming", "流式计算",
    "change data capture", "cdc", "debezium",
    "apache pulsar", "pulsar", "rocketmq",
}

# ═══════════════════════════════════════════════════════════════════
# 第三层：负面关键词 — 明确无关，直接过滤
# ═══════════════════════════════════════════════════════════════════
BLOCKLIST_KEYWORDS = {
    # 社会事件
    "枪击", "shooting", "mass shooting", "shootout",
    "科比", "kobe", "布莱恩特",
    "空难", "坠机", "helicopter crash",
    "地震", "earthquake", "海啸", "tsunami",
    "火山喷发", "volcano erupts",
    "疫情", "COVID", "covid-19", "coronavirus", "新冠",
    "pandemic", "流感",
    "大选", "election", "presidential election",
    "弹劾", "impeach",
    "总统", "prime minister",
    "战争", "war", "invasion", "冲突",
    "加沙", "gaza", "乌克兰", "russia ukraine",
    # 宏观经济
    "CPI", "PCE", "通胀", "inflation", "deflation",
    "美联储", "降息", "加息", "议息会议",
    "黄金", "gold price", "原油", "油价", "石油",
    "天然气",
    "GDP", "非农", "就业率", "失业率",
    "A股", "港股", "加密货币",
    # 体育 & 娱乐
    "世界杯", "欧洲杯", "欧冠", "NBA", "季后赛",
    "贝克汉姆", "明星", "演唱会", "电影首映",
    "票房", "好莱坞",
    # 生活 & 消费
    "海底捞", "星巴克", "瑞幸", "茅台",
    "特斯拉", "比亚迪",
    "房价", "房产税",
    "清明节", "春节", "五一", "国庆",
}

# ═══════════════════════════════════════════════════════════════════
# 综合媒体列表 — 需要更严格的过滤
# ═══════════════════════════════════════════════════════════════════
STRICT_MEDIA_DOMAINS = {
    "36kr.com", "ithome.com", "tmtpost.com", "leiphone.com",
    "woshipm.com", "199it.com",
    "theverge.com", "techcrunch.com", "wired.com",
    "engadget.com", "bbc.com", "cnn.com", "reuters.com",
    "bloomberg.com", "ft.com", "wsj.com",
}


def is_blocked(title: str, summary: str = "") -> bool:
    """Step 1: 负面关键词过滤"""
    text = f"{title} {summary}".lower()
    for kw in BLOCKLIST_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def count_relevant(title: str, summary: str = "") -> tuple:
    """
    统计标题+摘要中命中 AI 关键词 和 数据关键词 的数量。
    返回 (ai_count, data_count)
    """
    text = f"{title} {summary}".lower()
    ai_count = sum(1 for kw in AI_KEYWORDS if kw.lower() in text)
    data_count = sum(1 for kw in DATA_KEYWORDS if kw.lower() in text)
    return ai_count, data_count


def is_high_value(title: str, summary: str = "", url: str = "", source_quality: int = 5) -> bool:
    """
    四步过滤决策：

    Step 1 — 负面过滤（任何源）
    Step 2 — 白名单域名（直接通过）
    Step 3 — 综合媒体需要 >= 2 个相关关键词（AI 或 数据）
              高质量源只需 >= 1 个相关关键词
    """
    # Step 1: 负面关键词
    if is_blocked(title, summary):
        return False

    # Step 2: 白名单域名
    for wl in WHITELIST_DOMAINS:
        if wl in url.lower():
            return True

    # Step 3: 计算关键词命中
    ai_count, data_count = count_relevant(title, summary)
    total = ai_count + data_count

    if any(s in url.lower() for s in STRICT_MEDIA_DOMAINS):
        # 综合媒体——严格，需要 >= 2 个相关关键词
        return total >= 2
    elif source_quality >= 7:
        # 高质量源（论文/官方博客/AI媒体）
        return total >= 1
    else:
        # 其他标准源
        return total >= 1


# ─── 以下为原有 collector.py 的其余代码（不做修改）───

def get_connection():
    from database import get_connection as pg_get_connection
    return pg_get_connection()


def save_paper(paper_data: dict) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO papers (
                id, title, abstract, authors, published_date, updated_date,
                arxiv_id, arxiv_url, pdf_url, categories, comment, doi,
                citation_count, reference_count, source, source_url, raw_metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                abstract = EXCLUDED.abstract,
                authors = EXCLUDED.authors,
                published_date = EXCLUDED.published_date,
                updated_date = EXCLUDED.updated_date,
                citation_count = EXCLUDED.citation_count,
                reference_count = EXCLUDED.reference_count,
                raw_metadata = EXCLUDED.raw_metadata
        """, (
            paper_data.get('id'),
            paper_data.get('title'),
            paper_data.get('abstract'),
            json.dumps(paper_data.get('authors', [])),
            paper_data.get('published_date'),
            paper_data.get('updated_date'),
            paper_data.get('arxiv_id'),
            paper_data.get('arxiv_url'),
            paper_data.get('pdf_url'),
            json.dumps(paper_data.get('categories', [])),
            paper_data.get('comment'),
            paper_data.get('doi'),
            paper_data.get('citation_count', 0),
            paper_data.get('reference_count', 0),
            paper_data.get('source', 'arxiv'),
            paper_data.get('source_url'),
            json.dumps(paper_data.get('raw_metadata', {})),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"保存论文失败: {e}")
        return False
    finally:
        conn.close()


def save_repository(repo_data: dict) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO repositories (
                id, name, full_name, description, stars, forks, watchers, open_issues,
                language, license, topics, owner, owner_url, created_at, updated_at,
                pushed_at, html_url, github_url, issues_url, primary_language, languages,
                source, trending_date, raw_metadata, created_at_ts
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                full_name = EXCLUDED.full_name,
                description = EXCLUDED.description,
                stars = EXCLUDED.stars,
                forks = EXCLUDED.forks,
                watchers = EXCLUDED.watchers,
                open_issues = EXCLUDED.open_issues,
                languages = EXCLUDED.languages,
                raw_metadata = EXCLUDED.raw_metadata
        """, (
            repo_data.get('id'),
            repo_data.get('name'),
            repo_data.get('full_name'),
            repo_data.get('description'),
            repo_data.get('stars', 0),
            repo_data.get('forks', 0),
            repo_data.get('watchers', 0),
            repo_data.get('open_issues', 0),
            repo_data.get('language'),
            repo_data.get('license'),
            json.dumps(repo_data.get('topics', [])),
            repo_data.get('owner'),
            repo_data.get('owner_url'),
            repo_data.get('created_at'),
            repo_data.get('updated_at'),
            repo_data.get('pushed_at'),
            repo_data.get('html_url'),
            repo_data.get('github_url'),
            repo_data.get('issues_url'),
            repo_data.get('primary_language'),
            json.dumps(repo_data.get('languages', {})),
            repo_data.get('source', 'github_trending'),
            repo_data.get('trending_date'),
            json.dumps(repo_data.get('raw_metadata', {})),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"保存仓库失败: {e}")
        return False
    finally:
        conn.close()


def push_task(url: str):
    from database import push_task as db_push_task
    from worker import process_intel_task
    task_id, is_new = db_push_task(url)
    if is_new and task_id:
        process_intel_task.delay(task_id, url)
    return is_new


@dataclass
class IntelItem:
    url: str
    title: str
    summary: str = ""
    source: str = ""
    source_type: str = ""
    published_at: Optional[str] = None
    author: str = ""
    tags: List[str] = field(default_factory=list)
    quality: int = 5
    priority: int = 5
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "url": self.url, "title": self.title, "summary": self.summary,
            "source": self.source, "source_type": self.source_type,
            "published_at": self.published_at, "author": self.author,
            "tags": self.tags, "quality": self.quality, "priority": self.priority,
            "metadata": self.metadata
        }


class BaseCollector(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "Unknown")
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def collect(self) -> List[IntelItem]:
        pass

    def is_high_value(self, title: str, summary: str = "", url: str = "") -> bool:
        return is_high_value(title, summary, url, self.config.get("quality", 5))

    def filter_items(self, items: List[IntelItem]) -> List[IntelItem]:
        min_quality = 3
        filtered = []
        for item in items:
            if item.quality < min_quality:
                continue
            if not self.is_high_value(item.title, item.summary, item.url):
                logger.debug(f"过滤低相关条目: {item.title[:50]}")
                continue
            filtered.append(item)
        return filtered


class RSSCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        url = self.config.get("url", "")
        if not url:
            return []
        logger.info(f"  📡 抓取 RSS: {self.name}")
        DEFAULT_TIMEOUT = (5, 30)
        MAX_RETRIES = 2
        response = None
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0; +http://example.com/bot)"
                })
                if response.status_code in (200, 301, 302, 307):
                    break
                last_error = f"HTTP {response.status_code}"
            except requests.exceptions.SSLError as e:
                if attempt == MAX_RETRIES:
                    logger.warning(f"SSL error for {url}, trying without verify")
                    response = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0; +http://example.com/bot)"
                    }, verify=False)
                    if response.status_code in (200, 301, 302, 307):
                        break
                last_error = str(e)
            except Exception as e:
                last_error = str(e)

            if attempt < MAX_RETRIES:
                import time
                time.sleep(1)

        if response is None or response.status_code not in (200, 301, 302, 307):
            # Fallback: use curl subprocess (handles proxy better)
            import subprocess
            try:
                curl_cmd = [
                    "curl", "-sL", "--max-time", "30",
                    "-x", os.environ.get("HTTP_PROXY", "http://127.0.0.1:7897"),
                    "-A", "Mozilla/5.0 (compatible; AI-Tracker/1.0)",
                    url
                ]
                content_bytes = subprocess.check_output(curl_cmd, stderr=subprocess.DEVNULL)
                from io import BytesIO
                response = type('Response', (), {
                    'status_code': 200,
                    'content': content_bytes,
                    'text': content_bytes.decode('utf-8', errors='replace')
                })()
                logger.info(f"    curl fallback successful for {url}")
            except Exception as curl_err:
                logger.error(f"    FAIL RSS fetch (curl fallback error): {curl_err}")
                return []

        try:
            feed = feedparser.parse(response.content)
            items = []
            for entry in feed.entries:
                item = IntelItem(
                    url=entry.get("link", ""),
                    title=entry.get("title", ""),
                    summary=entry.get("summary", "")[:500],
                    source=self.name,
                    source_type="rss",
                    published_at=entry.get("published", ""),
                    author=entry.get("author", ""),
                    tags=self.config.get("tags", []),
                    quality=self.config.get("quality", 5),
                    priority=self.config.get("priority", 5),
                    metadata={"feed_url": url, "categories": entry.get("tags", [])}
                )
                items.append(item)
            logger.info(f"    ✅ 获取 {len(items)} 条 RSS 条目")
            return self.filter_items(items)
        except Exception as e:
            logger.error(f"    ❌ RSS 解析失败: {e}")
            return []


class ArXivCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        config = self.config.get("config", {})
        categories = config.get("categories", ["cs.CL", "cs.AI", "cs.LG", "cs.CV"])
        max_results = config.get("max_results", 50)
        logger.info(f"  📚 抓取 arXiv: {', '.join(categories)}")
        all_items = []
        for category in categories:
            items = self._collect_category(category, max_results)
            all_items.extend(items)
            time.sleep(0.5)
        logger.info(f"    ✅ arXiv 共获取 {len(all_items)} 篇论文")
        return all_items

    def _collect_category(self, category: str, max_results: int) -> List[IntelItem]:
        items = []
        try:
            params = {
                "search_query": f"cat:{category}",
                "start": 0, "max_results": max_results,
                "sortBy": "submittedDate", "sortOrder": "descending"
            }
            response = requests.get(
                ARXIV_API_URL, params=params, timeout=60,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"}
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            for entry in feed.entries:
                pdf_url = ""
                for link in entry.get("links", []):
                    if link.get("type") == "application/pdf":
                        pdf_url = link.get("href", "")
                        break
                arxiv_id = entry.get("id", "").split("/")[-1]
                authors = [a.get("name", "") for a in entry.get("authors", [])]
                categories = [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")]
                doi = ""
                for attr in entry.get("arxiv_doi", []):
                    doi = attr.get("value", "")
                    break
                paper_data = {
                    "id": f"arxiv:{arxiv_id}",
                    "title": entry.get("title", "").replace("\n", " ").strip(),
                    "abstract": entry.get("summary", "")[:2000],
                    "authors": authors,
                    "published_date": entry.get("published", ""),
                    "updated_date": entry.get("updated", ""),
                    "arxiv_id": arxiv_id,
                    "arxiv_url": entry.get("id", ""),
                    "pdf_url": pdf_url,
                    "categories": categories,
                    "comment": entry.get("arxiv_comment", ""),
                    "doi": doi,
                    "citation_count": 0,
                    "source": "arxiv",
                    "source_url": pdf_url or entry.get("id", ""),
                    "raw_metadata": {"journal_ref": entry.get("arxiv_journal_ref", ""), "doi": doi, "primary_category": category}
                }
                save_paper(paper_data)
                item = IntelItem(
                    url=pdf_url or entry.get("id", ""),
                    title=paper_data["title"],
                    summary=paper_data["abstract"][:500],
                    source=f"arXiv {category}",
                    source_type="paper",
                    published_at=paper_data["published_date"],
                    author=", ".join(authors[:3]) + ("..." if len(authors) > 3 else ""),
                    tags=["论文", "arXiv", category] + categories[:3],
                    quality=5,
                    priority=self.config.get("priority", 9),
                    metadata=paper_data
                )
                items.append(item)
        except Exception as e:
            logger.error(f"    ❌ arXiv API 错误 ({category}): {e}")
        return items


class GitHubTrendingCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        config = self.config.get("config", {})
        languages = config.get("languages", ["python", "typescript", "javascript"])
        logger.info(f"  🐙 抓取 GitHub Trending: {', '.join(languages)}")
        all_items = []
        trending_date = datetime.now(timezone.utc).date().isoformat()
        for language in languages:
            items = self._collect_language(language, trending_date)
            all_items.extend(items)
        logger.info(f"    ✅ GitHub Trending 共获取 {len(all_items)} 个项目")
        return all_items

    def _collect_language(self, language: str, trending_date: str) -> List[IntelItem]:
        items = []
        try:
            url = f"https://github.com/trending/{language}?since=daily"
            response = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)",
                "Accept": "text/html"
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            repo_articles = soup.find_all('article', class_='Box-row')
            for article in repo_articles[:20]:
                try:
                    title_tag = article.select_one('h2 a')
                    if not title_tag:
                        continue
                    full_name = title_tag.get('href', '').lstrip('/')
                    name = full_name.split('/')[-1] if '/' in full_name else full_name
                    desc_tag = article.select_one('p')
                    description = desc_tag.get_text(strip=True) if desc_tag else ""
                    if not self.is_high_value(name, description):
                        continue
                    repo_url = f"https://github.com/{full_name}"
                    stars_tag = article.select_one('a[href$="/stargazers"]')
                    stars_text = stars_tag.get_text(strip=True) if stars_tag else "0"
                    stars = self._parse_number(stars_text)
                    forks_tag = article.select_one('a[href$="/network/members"]')
                    forks_text = forks_tag.get_text(strip=True) if forks_tag else "0"
                    forks = self._parse_number(forks_text)
                    lang_tag = article.select_one('span[itemprop="programmingLanguage"]')
                    primary_language = lang_tag.get_text(strip=True) if lang_tag else None
                    today_stars = 0
                    today_tag = article.select_one('span.d-inline-block.float-sm-right')
                    if today_tag:
                        today_text = today_tag.get_text(strip=True)
                        today_stars = self._parse_number(today_text)
                    repo_data = {
                        "id": f"github:{full_name}", "name": name, "full_name": full_name,
                        "description": description, "stars": stars, "forks": forks,
                        "watchers": 0, "open_issues": 0, "language": primary_language,
                        "license": None, "topics": [],
                        "owner": full_name.split('/')[0] if '/' in full_name else full_name,
                        "owner_url": f"https://github.com/{full_name.split('/')[0] if '/' in full_name else full_name}",
                        "created_at": None, "updated_at": None, "pushed_at": None,
                        "html_url": repo_url, "github_url": repo_url, "issues_url": f"{repo_url}/issues",
                        "primary_language": primary_language, "languages": {},
                        "source": "github_trending", "trending_date": trending_date,
                        "raw_metadata": {"today_stars": today_stars, "description": description}
                    }
                    save_repository(repo_data)
                    item = IntelItem(
                        url=repo_url, title=f"⭐ {stars} | {name}", summary=description[:300],
                        source="GitHub Trending", source_type="repository",
                        published_at=trending_date, author=repo_data["owner"],
                        tags=["开源", "GitHub", "Trending", language] + ([primary_language] if primary_language else []),
                        quality=4, priority=self.config.get("priority", 8), metadata=repo_data
                    )
                    items.append(item)
                except Exception as e:
                    logger.debug(f"    ⚠️ 解析仓库条目失败: {e}")
        except Exception as e:
            logger.error(f"    ❌ GitHub Trending 错误 ({language}): {e}")
        return items

    def _parse_number(self, text: str) -> int:
        text = text.strip().upper()
        if not text:
            return 0
        multipliers = {'K': 1000, 'M': 1000000, 'B': 1000000000}
        try:
            if text[-1] in multipliers:
                return int(float(text[:-1]) * multipliers[text[-1]])
            return int(text.replace(',', ''))
        except (ValueError, IndexError):
            return 0


class HackerNewsCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        config = self.config.get("config", {})
        points_threshold = config.get("points_threshold", 50)
        logger.info(f"  📰 抓取 Hacker News (threshold: {points_threshold})")
        items = []
        try:
            response = requests.get(f"{HACKERNEWS_API}/topstories.json", timeout=30)
            response.raise_for_status()
            story_ids = response.json()[:50]
            for story_id in story_ids[:20]:
                try:
                    story_response = requests.get(
                        f"{HACKERNEWS_API}/item/{story_id}.json", timeout=10
                    )
                    story = story_response.json()
                    if not story or story.get("type") != "story":
                        continue
                    title = story.get("title", "")
                    score = story.get("score", 0)
                    if score < points_threshold:
                        continue
                    if not self.is_high_value(title):
                        continue
                    item = IntelItem(
                        url=story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                        title=title,
                        summary=story.get("text", "")[:300],
                        source="Hacker News",
                        source_type="hn",
                        published_at=datetime.fromtimestamp(story.get("time", 0), tz=timezone.utc).isoformat() if story.get("time") else None,
                        author=story.get("by", ""),
                        tags=["HN", "科技", "创业"],
                        quality=4,
                        priority=self.config.get("priority", 7),
                        metadata={"hn_id": story_id, "score": score, "comments": story.get("descendants", 0)}
                    )
                    items.append(item)
                    time.sleep(0.1)
                except Exception as e:
                    logger.debug(f"    ⚠️ HN story 解析错误: {e}")
            logger.info(f"    ✅ Hacker News: {len(items)} 条高价值条目")
        except Exception as e:
            logger.error(f"    ❌ Hacker News API 错误: {e}")
        return items


class SemanticScholarCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        config = self.config.get("config", {})
        query = config.get("query", "large language model")
        limit = config.get("limit", 20)
        logger.info(f"  📖 抓取 Semantic Scholar: {query}")
        try:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": query, "limit": limit, "sort": "recency",
                "fields": "title,abstract,authors,year,venue,citationCount,openAccessPdf,externalIds"
            }
            response = requests.get(url, params=params, timeout=30, headers={"User-Agent": "AI-Tracker/1.0"})
            response.raise_for_status()
            data = response.json()
            items = []
            for paper in data.get("data", []):
                external_ids = paper.get("externalIds", {})
                arxiv_id = external_ids.get("ArXiv") if external_ids else None
                paper_data = {
                    "id": f"semantic:{paper.get('paperId', '')}",
                    "title": paper.get("title", ""),
                    "abstract": paper.get("abstract", "")[:1000] or "",
                    "authors": [a.get("name", "") for a in paper.get("authors", [])[:5]],
                    "published_date": str(paper.get("year", "")) if paper.get("year") else None,
                    "arxiv_id": arxiv_id,
                    "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                    "pdf_url": paper.get("openAccessPdf", {}).get("url") if paper.get("openAccessPdf") else None,
                    "categories": [query],
                    "citation_count": paper.get("citationCount", 0),
                    "source": "semantic_scholar",
                    "source_url": f"https://www.semanticscholar.org/paper/{paper.get('paperId')}",
                    "raw_metadata": {"venue": paper.get("venue"), "paperId": paper.get("paperId")}
                }
                save_paper(paper_data)
                item = IntelItem(
                    url=paper_data["pdf_url"] or paper_data["source_url"],
                    title=paper_data["title"],
                    summary=paper_data["abstract"][:300],
                    source="Semantic Scholar",
                    source_type="paper",
                    published_at=paper_data["published_date"],
                    author=", ".join(paper_data["authors"][:3]),
                    tags=["论文", "学术", "AI"],
                    quality=5,
                    priority=self.config.get("priority", 8),
                    metadata=paper_data
                )
                items.append(item)
            logger.info(f"    ✅ Semantic Scholar: {len(items)} 篇论文")
            return items
        except Exception as e:
            logger.error(f"    ❌ Semantic Scholar API 错误: {e}")
            return []


class RedditCollector(BaseCollector):
    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []
        config = self.config.get("config", {})
        subreddit = config.get("subreddit", "MachineLearning")
        limit = config.get("limit", 25)
        logger.info(f"  💬 抓取 Reddit r/{subreddit}")
        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.json"
            response = requests.get(url, params={"limit": limit}, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"})
            response.raise_for_status()
            data = response.json()
            items = []
            for post in data.get("data", {}).get("children", []):
                post_data = post.get("data", {})
                if not self.is_high_value(post_data.get("title", "")):
                    continue
                item = IntelItem(
                    url=f"https://reddit.com{post_data.get('permalink')}",
                    title=post_data.get("title", ""),
                    summary=post_data.get("selftext", "")[:300],
                    source=f"Reddit r/{subreddit}",
                    source_type="reddit",
                    published_at=datetime.fromtimestamp(post_data.get("created_utc", 0), tz=timezone.utc).isoformat(),
                    author=post_data.get("author", ""),
                    tags=["社区", "讨论", "Reddit"],
                    quality=4,
                    priority=self.config.get("priority", 7),
                    metadata={"score": post_data.get("score"), "num_comments": post_data.get("num_comments"), "subreddit": subreddit}
                )
                items.append(item)
            logger.info(f"    ✅ Reddit r/{subreddit}: {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"    ❌ Reddit API 错误: {e}")
            return []


COLLECTORS = {
    "rss": RSSCollector, "arxiv_api": ArXivCollector,
    "github_trending": GitHubTrendingCollector, "hackernews": HackerNewsCollector,
    "semantic_scholar": SemanticScholarCollector, "reddit_ai": RedditCollector,
}


class HistoryManager:
    def __init__(self, filepath: Path, max_size: int = 100000):
        self.filepath = filepath
        self.max_size = max_size
        self._history = set()
        self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._history = set(data[-self.max_size:])
            except (json.JSONDecodeError, IOError):
                self._history = set()

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(list(self._history), f, ensure_ascii=False)
        except IOError as e:
            logger.error(f"历史记录保存失败: {e}")

    def add(self, url: str):
        self._history.add(url)

    def __contains__(self, url: str) -> bool:
        return url in self._history

    def __len__(self):
        return len(self._history)


class UnifiedCollector:
    def __init__(self, config_file: Path = FEEDS_UNIFIED_FILE):
        self.config_file = config_file
        self.config = self._load_config()
        self.history = HistoryManager(HISTORY_FILE)
        self._collectors = {}
        self._init_collectors()

    def _load_config(self) -> dict:
        if not self.config_file.exists():
            logger.warning(f"配置文件不存在: {self.config_file}")
            return {}
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            return {}

    def _init_collectors(self):
        sources = self.config.get("sources", {})
        for rss_config in sources.get("rss", {}).get("items", []):
            if rss_config.get("enabled", True):
                collector = RSSCollector(rss_config)
                self._collectors[f"rss_{rss_config['url']}"] = collector
        for api_config in sources.get("api", {}).get("items", []):
            if api_config.get("enabled", True):
                collector_type = api_config.get("type")
                if collector_type in COLLECTORS:
                    collector = COLLECTORS[collector_type](api_config)
                    self._collectors[f"api_{collector_type}"] = collector
        logger.info(f"已初始化 {len(self._collectors)} 个采集器")

    def collect_all(self, source_types: List[str] = None) -> List[IntelItem]:
        all_items = []
        for name, collector in self._collectors.items():
            if source_types:
                collector_type = name.split("_")[0]
                if collector_type not in source_types:
                    continue
            logger.info(f"\n🔍 执行采集: {name}")
            items = collector.collect()
            new_items = []
            for item in items:
                if item.url not in self.history:
                    new_items.append(item)
                    self.history.add(item.url)
            all_items.extend(new_items)
            time.sleep(random.uniform(0.5, 1.5))
        return all_items

    def collect_rss(self) -> List[IntelItem]:
        return self.collect_all(["rss"])

    def collect_api(self) -> List[IntelItem]:
        return self.collect_all(["api"])

    def collect_papers(self) -> List[IntelItem]:
        return self.collect_all(["api"])

    def get_stats(self) -> dict:
        return {
            "total_collectors": len(self._collectors),
            "rss_count": sum(1 for n in self._collectors if n.startswith("rss_")),
            "api_count": sum(1 for n in self._collectors if n.startswith("api_")),
            "history_size": len(self.history)
        }


def get_collector_stats() -> dict:
    collector = UnifiedCollector()
    return collector.get_stats()


def run_collection(source_types: List[str] = None) -> dict:
    collector = UnifiedCollector()
    items = collector.collect_all(source_types)
    return {
        "collected": len(items),
        "items": [item.to_dict() for item in items],
        "stats": collector.get_stats()
    }


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AI Tracker - 统一情报采集器 v2.2 (双主线过滤)")
    print("=" * 60)
    collector = UnifiedCollector()
    stats = collector.get_stats()
    print(f"\n📊 采集器统计:")
    print(f"   - 总采集器数: {stats['total_collectors']}")
    print(f"   - RSS 源: {stats['rss_count']}")
    print(f"   - API 源: {stats['api_count']}")
    print(f"   - 历史记录: {stats['history_size']}")
    print("\n" + "=" * 60)
    print("📡 开始采集...")
    print("=" * 60)
    items = collector.collect_all()
    print("\n" + "=" * 60)
    print(f"✅ 采集完成! 获取 {len(items)} 条新情报")
    print("=" * 60)
    sent_count = 0
    for item in items:
        if item.source_type in ["rss", "hn", "reddit"]:
            if push_task(item.url):
                sent_count += 1
    print(f"📤 已发送 {sent_count} 条到处理队列 (仅 RSS/HN/Reddit)")
