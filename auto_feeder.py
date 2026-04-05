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

# API URL 可配置，优先使用环境变量
API_URL = os.environ.get("API_INGEST_URL", "http://127.0.0.1:8000/api/ingest")

# 历史记录最大容量（防止内存膨胀）
MAX_HISTORY_SIZE = int(os.environ.get("FEEDER_HISTORY_MAX_SIZE", "100000"))

# 高价值情报过滤网 (维持强力配置)
AI_KEYWORDS = [
    "llm", "大模型", "vlm", "多模态", "moe", "混合专家", "slm", "端侧模型",
    "transformer", "diffusion", "dit", "agi", "aigc", "大语言模型", "具身智能",
    "openai", "chatgpt", "sora", "gpt-4", "o1", "o3", "anthropic", "claude",
    "google", "gemini", "gemma", "meta", "llama", "deepseek", "深度求索",
    "moonshot", "kimi", "月之暗面", "minimax", "稀宇科技", "zhipu", "智谱",
    "qwen", "通义千问", "baichuan", "百川", "mistral", "xai", "grok", "midjourney", "perplexity",
    "data", "数据", "rag", "graphrag", "检索增强", "知识图谱", "knowledge graph",
    "neo4j", "图数据库", "chroma", "milvus", "qdrant", "向量数据库", "vector database",
    "synthetic data", "合成数据", "数据治理", "数据资产", "数据估值", "unstructured data",
    "非结构化数据", "数据清洗", "etl", "data pipeline",
    "agent", "智能体", "multi-agent", "多智能体", "ai-native", "ai原生",
    "langchain", "llamaindex", "autogen", "crewai", "dify", "coze", "openclaw",
    "mcp", "model context protocol", "vibe coding", "ai coding", "cursor",
    "gpu", "tpu", "npu", "nvidia", "英伟达", "h100", "b200", "gb200", "cuda", "tensorrt", "groq",
    "算力", "数据中心", "液冷", "边缘计算", "edge computing",
    "open source", "开源", "huggingface", "github", "local deployment", "本地部署", "算力集群",
    "parameters", "参数量", "context window", "上下文",
    "fine-tuning", "微调", "rlhf", "dpo", "lora", "量化", "quantization", "prompt", "提示词", "数据集", "数据"
]

# 现代数据栈与前沿基建白名单
WHITELIST_DOMAINS = [
    "arxiv.org", "huggingface.co", "openai.com", "anthropic.com", "research.google",
    "databricks.com", "snowflake.com", "zilliz.com", "qdrant.tech", "weaviate.io",
    "langchain.dev", "llamaindex.ai", "buttondown.email/ainews", "importai.substack.com"
]


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
                tier_order = ["core", "standard", "extended", "wechat", "local"]
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


def is_high_value_intel(title: str, summary: str, content: str, url: str) -> bool:
    """情报过滤器：判断是否包含核心行业价值"""
    if any(domain in url for domain in WHITELIST_DOMAINS):
        return True

    text_to_scan = (title + " " + summary + " " + content).lower()
    for kw in AI_KEYWORDS:
        if kw in text_to_scan:
            return True

    return False


def parse_feed(feed_url: str, history: HistoryManager, last_crawl: str = None) -> list:
    try:
        feed = feedparser.parse(feed_url)
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
                valid_articles.append(url)

        log(f"  ✅ 发现 {len(feed.entries)} 篇，提纯出 {len(valid_articles)} 篇极密情报")
        return valid_articles
    except Exception as e:
        log(f"  ❌ 解析失败: {e}")
        return []


def send_to_api(url: str) -> bool:
    try:
        resp = requests.post(API_URL, json={"url": url}, timeout=10)
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

        for url in target_urls:
            log(f"    -> 锁定目标: {url}")
            if send_to_api(url):
                history.add(url)
                total_pushed += 1
            time.sleep(0.5)  # 控制并发避免打挂后端

        # 修复：在所有URL处理完成后再更新时间戳
        # 避免解析耗时导致"未来"的文章被错误过滤
        new_metadata[feed_url] = datetime.utcnow().isoformat()

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
