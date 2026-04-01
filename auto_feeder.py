#!/usr/bin/env python3
"""
AI Tracker System - 自动 RSS 巡航模块 (V4 历史全收录版)
解除篇幅与短期时间限制，支持 2023 年 1 月 1 日以来的全量高价值情报应收尽收。
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime
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
FEEDS_FILE = CONFIG_DIR / "feeds.json"
HISTORY_FILE = CONFIG_DIR / "feeder_history.json"
API_URL = "http://127.0.0.1:8000/api/ingest"

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

def load_json_file(filepath: Path, default_val: list) -> list:
    if not filepath.exists(): return default_val
    with open(filepath, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return default_val

def save_json_file(filepath: Path, data: list):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_after_2023(entry) -> bool:
    """时间闸门：绝对放行 2023 年 1 月 1 日及之后的所有情报"""
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
        if pub_time < datetime(2023, 1, 1):
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

def parse_feed(feed_url: str, history: set) -> list:
    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries: return []
        
        valid_articles = []
        # 💡 解除 [:100] 的限制，直接遍历 RSS 源能提供的所有历史数据
        for entry in feed.entries:
            url = getattr(entry, 'link', '')
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', getattr(entry, 'description', ''))
            
            content = ''
            if hasattr(entry, 'content') and len(entry.content) > 0:
                content = entry.content[0].value
                
            if not url or url in history:
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
    log("=" * 60)
    
    feeds = load_json_file(FEEDS_FILE, [])
    if not feeds:
        log("❌ 弹药库 (feeds.json) 为空！")
        return
        
    history_list = load_json_file(HISTORY_FILE, [])
    history_set = set(history_list)
    
    total_pushed = 0
    new_history = list(history_list)
    
    for feed_url in feeds:
        log(f"\n📡 正在扫描空域: {feed_url}")
        target_urls = parse_feed(feed_url, history_set)
        
        for url in target_urls:
            log(f"    -> 锁定目标: {url}")
            if send_to_api(url):
                new_history.append(url)
                history_set.add(url)
                total_pushed += 1
            time.sleep(0.5) # 控制并发避免打挂后端
            
    # 💡 极其重要：放宽历史去重记忆池至 100,000 条，防止因为抓取量暴增导致旧数据被错误遗忘和重复抓取
    if len(new_history) > 100000:
        new_history = new_history[-100000:]
        
    save_json_file(HISTORY_FILE, new_history)
    log("=" * 60)
    log(f"🎉 巡航结束！本次成功向 V8 引擎输送了 {total_pushed} 篇历史深层情报。")

if __name__ == "__main__":
    run_auto_feeder()