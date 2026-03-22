#!/usr/bin/env python3
"""
AI Tracker System - 自动 RSS 巡航模块 (V2 降噪提纯版)
具备本地记忆去重、硬核 AI 关键词过滤、ArXiv 论文专属捕获能力。
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
import feedparser
import requests

# 配置日志输出带时间戳
import builtins
_original_print = builtins.print

def log(*args, **kwargs):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _original_print(f"[{timestamp}]", *args, **kwargs)
    import sys
    sys.stdout.flush()

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
FEEDS_FILE = CONFIG_DIR / "feeds.json"
HISTORY_FILE = CONFIG_DIR / "feeder_history.json" # 💡 新增：本地记忆数据库
API_URL = "http://127.0.0.1:8000/api/ingest"

# 💡 核心升级：高价值情报过滤网 (只抓这些硬核内容)
AI_KEYWORDS = [
    # 1. 核心大模型 & 基础架构 (Foundation Models)
    "llm", "大模型", "vlm", "多模态", "moe", "混合专家", "slm", "端侧模型", 
    "transformer", "diffusion", "dit", "agi", "aigc", "大语言模型", "具身智能",

    # 2. 顶级 AI 厂商 & 明星产品 (Companies & Products)
    "openai", "chatgpt", "sora", "gpt-4", "o1", "o3",
    "anthropic", "claude", 
    "google", "gemini", "gemma", 
    "meta", "llama", 
    "deepseek", "深度求索",
    "moonshot", "kimi", "月之暗面",
    "minimax", "稀宇科技", 
    "zhipu", "智谱", "qwen", "通义千问", "baichuan", "百川",
    "mistral", "xai", "grok", "midjourney", "perplexity",

    # 3. 数据技术 & 知识工程 (Data Tech & RAG - 核心护城河)
    "data", "数据", "rag", "graphrag", "检索增强", "知识图谱", "knowledge graph",
    "neo4j", "图数据库", "chroma", "milvus", "qdrant", "向量数据库", "vector database",
    "synthetic data", "合成数据", "数据治理", "数据资产", "数据估值", "unstructured data", 
    "非结构化数据", "数据清洗", "etl", "data pipeline",

    # 4. 智能体 & 创新开发范式 (Agents & Frameworks)
    "agent", "智能体", "multi-agent", "多智能体", "ai-native", "ai原生",
    "langchain", "llamaindex", "autogen", "crewai", "dify", "coze", "openclaw",
    "mcp", "model context protocol", "vibe coding", "ai coding", "cursor",

    # 5. 算力基建 & 本地部署 (Compute & Deployment)
    "gpu", "tpu", "npu", "nvidia", "英伟达", "h100", "b200", "gb200", "cuda", "tensorrt", "groq",
    "算力", "数据中心", "液冷", "边缘计算", "edge computing",
    "open source", "开源", "huggingface", "github", "local deployment", "本地部署", "算力集群",

    # 6. 训练与微调技术 (Training & Tuning)
    "parameters", "参数量", "context window", "上下文", 
    "fine-tuning", "微调", "rlhf", "dpo", "lora", "量化", "quantization", "prompt", "提示词"
]

def load_json_file(filepath: Path, default_val: list) -> list:
    if not filepath.exists(): return default_val
    with open(filepath, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return default_val

def save_json_file(filepath: Path, data: list):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_high_value_intel(title: str, summary: str, url: str) -> bool:
    """情报过滤器：判断是否值得动用 V8 引擎解析"""
    # 1. 论文和名门正派的博客，直接放行 (免检白名单)
    if "arxiv.org" in url or "huggingface.co" in url or "openai.com" in url or "anthropic.com" in url:
        return True
        
    # 2. 媒体新闻，必须进行严格的关键词扫描 (双重雷达探测)
    text_to_scan = (title + " " + summary).lower()
    for kw in AI_KEYWORDS:
        if kw in text_to_scan:
            return True
            
    return False

def parse_feed(feed_url: str, history: set) -> list:
    """解析 Feed，过滤已处理和低价值的内容"""
    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries: return []
        
        valid_articles = []
        # 扫描最新的 15 篇文章
        for entry in feed.entries[:15]:
            url = getattr(entry, 'link', '')
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', getattr(entry, 'description', ''))
            
            if not url or url in history:
                continue # 已处理过，跳过
                
            if is_high_value_intel(title, summary, url):
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
    log("🚀 AI Tracker - 战略巡航舰启动 (SNR 过滤模式)")
    log("=" * 60)
    
    feeds = load_json_file(FEEDS_FILE, [])
    if not feeds:
        log("❌ 弹药库 (feeds.json) 为空！")
        return
        
    # 💡 加载本地记忆，防止重复提交
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
            time.sleep(0.5)
            
    # 只保留最近 2000 条记忆，防止文件过大
    if len(new_history) > 2000:
        new_history = new_history[-2000:]
        
    save_json_file(HISTORY_FILE, new_history)
    log("=" * 60)
    log(f"🎉 巡航结束！本次成功向 V8 引擎输送了 {total_pushed} 篇硬核情报。")

if __name__ == "__main__":
    run_auto_feeder()