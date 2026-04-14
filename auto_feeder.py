#!/usr/bin/env python3
"""
AI Tracker System - 自动 RSS 巡航模块 (V4 历史全收录版)
解除篇幅与短期时间限制，支持 2023 年 1 月 1 日以来的全量高价值情报应收尽收。
"""

import fcntl
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
import feedparser
import requests
import re
import builtins

# 配置日志输出带时间戳
_original_print = builtins.print
def log(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _original_print(f"[{timestamp}]", *args, **kwargs)
    import sys
    sys.stdout.flush()

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
FEEDS_FILE = CONFIG_DIR / "feeds.json"
FEEDS_V2_FILE = CONFIG_DIR / "feeds_v2.json"
HISTORY_FILE = CONFIG_DIR / "feeder_history.json"
RSS_HEALTH_FILE = CONFIG_DIR / "feed_health.json"

# API URL 可配置，优先使用环境变量
API_URL = os.environ.get("API_INGEST_URL", "http://127.0.0.1:8000/api/ingest")

# 历史记录最大容量（防止内存膨胀）
MAX_HISTORY_SIZE = int(os.environ.get("FEEDER_HISTORY_MAX_SIZE", "100000"))

# ═══════════════════════════════════════════════════════════════
# AI 关键词（中英文，双主线：AI + 数据基础设施）
# ═══════════════════════════════════════════════════════════════
AI_KEYWORDS = {
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
    "yi", "零一", "01ai", "step", "step-2", "step-3",
    "jina", "bge", "bce", "bge embeddings", "m3e",
    "rwkv",
    "openai", "anthropic", "deepmind", "mistral ai", "cohere",
    "stability ai", "midjourney", "runway", "runwayml",
    "huggingface", "langchain", "llamaindex", "dify", "coze",
    "nvidia", "英伟达", "amd", "intel ai", "tpu", "gpu",
    "databricks", "snowflake", "zilliz", "qdrant", "chroma",
    "pinecone", "weaviate", "milvus", "clickhouse",
    "阿里云", "华为云ModelArts", "modelarts",
    "腾讯云", "tencent cloud", "tencent ai lab",
    "字节AI", "字节火山", "火山引擎", "doubao",
    "百度AI", "文心", "ernie", "飞桨", "paddlepaddle",
    "商汤", "sensecore", "旷视", "megvii",
    "依图", "yitu", "云从", "cloudwalk",
    "第四范式", "寒武纪", "cambricon",
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
    "open source", "开源", "开源模型",
    "github", "github trending", "hugging face",
    "lora", "qlora", "lorahub",
    "vllm", "text-generation-inference", "tgi", "llama.cpp",
    "ollama", "localai", "local llm", "本地部署",
    "paged attention", "attention sink",
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

DATA_KEYWORDS = {
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
    "airflow", "prefect", "mage.ai", "dagster",
    "dbt", "data build tool", "sqlmesh",
    "fivetran", "airbyte", "meltano", "stitch",
    "bigquery", "redshift", "synapse",
    "data warehouse", "数据仓库", "湖仓一体",
    "tableau", "powerbi", "quicksight", "looker", "hex", "mode analytics", "thoughtspot",
    "data observability", "data quality", "数据质量",
    "monte carlo", "metaplane", "bigeye", "datafold",
    "data integration", "etl", "elt", "数据集成",
    "vector database", "vector store", "向量数据库",
    "embedding", " ANN search", "近似最近邻",
    "mlops", "dataops",
    "feature store", "feature platform",
    "dvc", "mlflow", "clearml", "wandb",
    "ray", "ray distributed", "distributed training",
    "sageMaker", "vertex ai", "azure ml",
    "lakehouse", "data lake",
    "real-time data", "streaming", "流式计算",
    "change data capture", "cdc", "debezium",
    "apache pulsar", "pulsar", "rocketmq",
}

BLOCKLIST_KEYWORDS = {
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
    "CPI", "PCE", "通胀", "inflation", "deflation",
    "美联储", "降息", "加息", "议息会议",
    "黄金", "gold price", "原油", "油价", "石油",
    "天然气",
    "GDP", "非农", "就业率", "失业率",
    "A股", "港股", "加密货币",
    "世界杯", "欧洲杯", "欧冠", "NBA", "季后赛",
    "贝克汉姆", "明星", "演唱会", "电影首映",
    "票房", "好莱坞",
    "海底捞", "星巴克", "瑞幸", "茅台",
    "特斯拉", "比亚迪",
    "房价", "房产税",
    "清明节", "春节", "五一", "国庆",
}

STRICT_MEDIA_DOMAINS = {
    "36kr.com", "ithome.com", "tmtpost.com", "leiphone.com",
    "woshipm.com", "199it.com",
    "theverge.com", "techcrunch.com", "wired.com",
    "engadget.com", "bbc.com", "cnn.com", "reuters.com",
    "bloomberg.com", "ft.com", "wsj.com",
}

# ═══════════════════════════════════════════════════════════════
# 白名单域名（高质量 AI + 数据来源，直接通过）
# ═══════════════════════════════════════════════════════════════
WHITELIST_DOMAINS = {
    "arxiv.org", "openai.com", "anthropic.com", "deepmind.google",
    "ai.google", "blog.google", "developers.google.com",
    "huggingface.co", "huggingface.com", "meta.ai",
    "blogs.nvidia.com", "developer.nvidia.com", "nvidia.com",
    "aws.amazon.com", "azure.microsoft.com",
    "microsoft.com/research", "blogs.microsoft.com",
    "bai.com", "baidu.com", "qianwen.aliyun.com", "tongyi.aliyun.com",
    "tencent.com", "weixin.qq.com", "qq.com",
    "bytedance.com", "douyin.com", "feishu.cn", "larkoffice.com",
    "x.ai", "mistral.ai", "cohere.com", "stability.ai",
    "midjourney.com", "runwayml.com", "replicate.com",
    "together.ai", "groq.com", "perplexity.ai",
    "wandb.ai", "weights.gg", "clearml.ai", "mlflow.org",
    "modal.com", "anyscale.com", "beam.cloud", "fal.ai",
    "snowflake.com", "snowflakedb.com",
    "databricks.com", "databricks.io", "spark.apache.org",
    "confluent.io", "kafka.apache.org",
    "flink.apache.org",
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
    "singlestore.com",
    "rockset.com", "Elastic", "elasticsearch.com",
    "weaviate.io", "Qdrant", "qdrant.tech",
    "chroma.ai", "Milvus", "milvus.io", "Zilliz", "zilliz.com",
    "pinecone.io", "LanceDB", "lancedb.com", "Marqo", "marqo.ai",
    "opensearch.org",
    "timescale.com", "influxdata.com",
    "questdb.com", "Tdengine", "taosdata.com",
    "apache-druid", "imply.io",
    "langchain.dev", "langchain.com", "dify.ai", "coze.com", "coze.cn",
    "llamaindex.ai", "llamaindex.com", "llama.cpp",
    "ollama.ai", "ollama.com", "localai.io", "localai.gg",
    "vllm.ai", "pytorch.org", "jax.ai", "chainer.org",
    "Papers With Code", "paperswithcode.com",
    "zhipuai.cn", "zhipuai.com", "chatglm.cn", "chatglm.com",
    "minimax.io", "minimaxi.com",
    "kimi.moonshot.cn", "moshi.moonshot.cn",
    "xunfei.cn", "xfyun.cn", "iflytek.com",
    "sensetime.com", "megvii.com", "yitu.com", "deepglint.com",
    "horizon.ai", "cambricon.com", "bitmain.com",
    "alibaba.com", "aliyun.com",
    "huawei.com", "huaweicloud.com",
    "iqiyi.com", "bilibili.com",
    "xiaomi.com", "mi.com",
    "jd.com",
    "360.cn", "360.com", "360ai.com",
    "mit.edu", "stanford.edu", "berkeley.edu", "cmu.edu",
    "ox.ac.uk", "cam.ac.uk", "ic.ac.uk", "ucl.ac.uk",
    "mila.quebec", "mila.ca", "vectorinstitute.ai",
    "allenai.org", "allenai-oai.github.io",
    "bair.berkeley.edu", "crfm.stanford.edu",
    "msra.cn", "msra.com",
    "jiqizhixin.com", "机器之心.com", "qbitai.com", "量子位.com",
    "leiphone.com", "ithome.com", "tmtpost.com",
    "aibase.com", "aigc.com", "woshipm.com",
    "36kr.com", "199it.com",
    "garymarcus.substack.com", "importai.substack.com",
    "substack.com", "buttondown.email",
    "theinformation.com",
    "news.ycombinator.com", "reddit.com/r/MachineLearning",
    "github.com", "gitlab.com", "bitbucket.org",
}


class HistoryManager:
    """内存高效的历史记录管理器，使用 deque 限制内存使用"""

    def __init__(self, filepath: Path, max_size: int = MAX_HISTORY_SIZE):
        self.filepath = filepath
        self.max_size = max_size
        # 使用 deque 自动丢弃旧条目，控制内存使用
        self._history = deque(maxlen=max_size)
        self._load()

    def _load(self):
        """加载历史记录"""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 重建 deque（会自动截断超出的部分）
                    self._history = deque(data, maxlen=self.max_size)
            except (json.JSONDecodeError, IOError) as e:
                log(f"⚠️ 历史记录加载失败: {e}，将创建新的历史记录")
                self._history = deque(maxlen=self.max_size)

    def save(self):
        """保存历史记录到磁盘"""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(list(self._history), f, ensure_ascii=False, indent=2)
        except IOError as e:
            log(f"⚠️ 历史记录保存失败: {e}")

    def add(self, url: str):
        """添加 URL 到历史记录"""
        if url not in self._history:
            self._history.append(url)

    def __contains__(self, url: str) -> bool:
        """O(1) 查找"""
        return url in self._history

    def __len__(self) -> int:
        return len(self._history)


def load_feeds():
    """加载feed配置，支持feeds_v2.json的分层结构"""
    # 优先使用feeds_v2.json
    if FEEDS_V2_FILE.exists():
        with open(FEEDS_V2_FILE, "r", encoding="utf-8") as f:
            try:
                v2_data = json.load(f)
                feeds = []
                tiers = v2_data.get("tiers", {})
                # 按优先级收集所有feed：core > standard > extended > local
                tier_order = ["core", "standard", "extended", "aggregated", "local"]
                for tier_name in tier_order:
                    tier = tiers.get(tier_name, {})
                    tier_feeds = tier.get("feeds", [])
                    for feed in tier_feeds:
                        url = feed.get("url")
                        if url and url not in feeds:
                            feeds.append(url)
                            log(f"  📦 [{tier_name}] {feed.get('name', url)} - priority:{feed.get('priority', 'N/A')}")
                if feeds:
                    log(f"  ✅ 从feeds_v2.json加载了 {len(feeds)} 个源")
                    return feeds
            except Exception as e:
                log(f"  ⚠️ feeds_v2.json解析失败: {e}")
    # 回退到feeds.json
    if FEEDS_FILE.exists():
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            try:
                feeds = json.load(f)
                if feeds:
                    log(f"  ✅ 从feeds.json加载了 {len(feeds)} 个源")
                    return feeds
            except Exception:
                pass
    return []


def load_json_file(filepath: Path, default_val: list) -> list:
    if not filepath.exists():
        return default_val
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return default_val


def save_json_file(filepath: Path, data: list):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_feed_metadata() -> dict:
    """加载每个feed的最后抓取时间"""
    metadata_file = HISTORY_FILE.with_name("feeder_metadata.json")
    if not metadata_file.exists():
        return {}
    with open(metadata_file, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_feed_metadata(metadata: dict):
    """保存每个feed的最后抓取时间"""
    metadata_file = HISTORY_FILE.with_name("feeder_metadata.json")
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def is_newer_than_last_crawl(entry, last_crawl: str) -> bool:
    """检查entry是否比上次抓取时间更新（统一使用UTC避免时区问题）"""
    if not last_crawl:
        return True  # 从未抓取过，放行全量
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        # feedparser 的 published_parsed 是 UTC 时间struct，转换为 UTC datetime
        pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
        # last_crawl 统一存储为 UTC 时间
        last_crawl_dt = datetime.fromisoformat(last_crawl)
        # 如果 last_crawl 是 naive datetime（旧数据），视为 UTC 处理
        if last_crawl_dt.tzinfo is None:
            last_crawl_dt = last_crawl_dt.replace(tzinfo=timezone.utc)
        return pub_time > last_crawl_dt
    return True  # 无法判断时放行


def is_after_2023(entry) -> bool:
    """时间闸门：绝对放行 2023 年 1 月及之后的所有情报（UTC）"""
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
        if pub_time < datetime(2023, 1, 1, tzinfo=timezone.utc):
            return False
    return True


def _is_blocked(title, summary, content):
    """负面关键词过滤"""
    text = (title + " " + summary + " " + content).lower()
    for kw in BLOCKLIST_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def _count_relevant(title, summary, content):
    """统计命中数量"""
    text = (title + " " + summary + " " + content).lower()
    ai_count = sum(1 for kw in AI_KEYWORDS if kw.lower() in text)
    data_count = sum(1 for kw in DATA_KEYWORDS if kw.lower() in text)
    return ai_count, data_count


def is_high_value_intel(title, summary, content, url, source_quality=5):
    """
    统一过滤逻辑（与 collector.py 一致）：
    Step 1: 负面过滤
    Step 2: 白名单域名直接通过
    Step 3: 综合媒体>=2关键词，其他>=1关键词
    """
    if _is_blocked(title, summary, content):
        return False

    # 白名单域名
    for wl in WHITELIST_DOMAINS:
        if wl in url.lower():
            return True

    ai_count, data_count = _count_relevant(title, summary, content)
    total = ai_count + data_count

    if any(s in url.lower() for s in STRICT_MEDIA_DOMAINS):
        return total >= 2
    elif source_quality >= 7:
        return total >= 1
    else:
        return total >= 1



def _load_rss_health() -> dict:
    """加载 RSS 健康状态（失败追踪）"""
    if not RSS_HEALTH_FILE.exists():
        return {"consecutive_failures": {}}
    with open(RSS_HEALTH_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {"consecutive_failures": {}}

def _save_rss_health(health: dict):
    """保存 RSS 健康状态"""
    with open(RSS_HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)

def record_rss_failure(feed_url: str, error: str):
    """记录 RSS 抓取失败"""
    health = _load_rss_health()
    failures = health.get("consecutive_failures", {})
    failures[feed_url] = {"count": failures.get(feed_url, {}).get("count", 0) + 1, "last_error": error}
    health["consecutive_failures"] = failures
    _save_rss_health(health)

def clear_rss_failures(feed_url: str):
    """清除 RSS 失败记录（成功时调用）"""
    health = _load_rss_health()
    failures = health.get("consecutive_failures", {})
    if feed_url in failures:
        del failures[feed_url]
        health["consecutive_failures"] = failures
        _save_rss_health(health)



def _strip_html(text: str) -> str:
    """Remove HTML tags from text for use as RSS fallback content"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_feed(feed_url: str, history: HistoryManager, last_crawl: str = None) -> list:
    try:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            record_rss_failure(feed_url, str(e))
            return []
            clear_rss_failures(feed_url)  # 成功解析但无条目也算成功
        if not feed.entries:
            return []

        valid_articles = []
        for entry in feed.entries:
            url = getattr(entry, 'link', '')
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', getattr(entry, 'description', ''))

            content = ''
            if hasattr(entry, 'content') and len(entry.content) > 0:
                content = entry.content[0].value

            if not url or url in history:
                continue

            # 白名单域名跳过时间过滤（arxiv等来源的published_parsed是论文投稿时间，
            # 而非RSS发布时间，需要信任这些高质量来源）
            in_whitelist = any(domain in url for domain in WHITELIST_DOMAINS)

            if not in_whitelist:
                # 增量更新：跳过上次抓取时间之前的旧内容（非白名单来源）
                if not is_newer_than_last_crawl(entry, last_crawl):
                    continue

            # 严格执行 2023 年时间线底线，并过滤硬核内容
            if is_after_2023(entry) and is_high_value_intel(title, summary, content, url):
                rss_text = content if content else summary
                valid_articles.append({"url": url, "title": title, "rss_summary": _strip_html(rss_text)})

        log(f"  ✅ 发现 {len(feed.entries)} 篇，提纯出 {len(valid_articles)} 篇极密情报")
        return valid_articles
    except Exception as e:
        log(f"  ❌ 解析失败: {e}")
        return []


def send_to_api(url: str, rss_summary: str = "") -> bool:
    try:
        payload = {"url": url}
        if rss_summary:
            payload["rss_summary"] = rss_summary
        resp = requests.post(API_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            log(f"    🎯 成功发射至后端缓冲队列!")
            return True
        log(f"    ⚠️ API 拒绝接收: {resp.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        log(f"    ❌ 通讯阻断: {e}")
        return False


def run_auto_feeder():
    log("=" * 60)
    log("🚀 AI Tracker - 战略巡航舰启动 (V4 历史全收录模式, Base: 2023-01-01)")
    log(f"   API URL: {API_URL}")
    log(f"   历史记录上限: {MAX_HISTORY_SIZE}")
    log("=" * 60)

    log("📡 加载情报源...")
    feeds = load_feeds()
    if not feeds:
        log("❌ 弹药库 (feeds.json 和 feeds_v2.json) 都为空！")
        return

    # 使用内存高效的历史记录管理器
    history = HistoryManager(HISTORY_FILE, max_size=MAX_HISTORY_SIZE)
    log(f"   📜 已加载 {len(history)} 条历史记录")

    total_pushed = 0

    # 增量更新：加载每个feed的最后抓取时间
    feed_metadata = load_feed_metadata()
    new_metadata = dict(feed_metadata)  # 复制一份用于更新

    for feed_url in feeds:
        log(f"\n📡 正在扫描空域: {feed_url}")
        last_crawl = feed_metadata.get(feed_url)
        if last_crawl:
            log(f"   ⏰ 上次抓取: {last_crawl}，增量模式")
        else:
            log(f"   🆕 首次抓取，全量模式")

        target_urls = parse_feed(feed_url, history, feed_metadata.get(feed_url))

        for item in target_urls:
            url = item["url"]
            rss_summary = item.get("rss_summary", "")
            log(f"    -> 锁定目标: {url}")
            if send_to_api(url, rss_summary):
                history.add(url)
                total_pushed += 1
            time.sleep(0.5)  # 控制并发避免打挂后端

        # 修复：在所有URL处理完成后再更新时间戳
        # 避免解析耗时导致"未来"的文章被错误过滤
        new_metadata[feed_url] = datetime.now(timezone.utc).isoformat()

    # 保存URL历史和元数据
    history.save()
    save_feed_metadata(new_metadata)

    log("=" * 60)
    log(f"🎉 巡航结束！本次成功向 V8 引擎输送了 {total_pushed} 篇情报。")
    log(f"   当前历史记录总数: {len(history)}")


if __name__ == "__main__":
    # ── 并发防护：确保同一时刻只有一个实例运行 ──────────────────────
    LOCK_FILE = Path(__file__).parent / ".auto_feeder.lock"
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"⚠️ 检测到 another auto_feeder instance is running, exiting.")
        sys.exit(0)

    try:
        run_auto_feeder()
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        # 清理锁文件（可选）
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass