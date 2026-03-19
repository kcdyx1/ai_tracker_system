#!/usr/bin/env python3
"""
AI Tracker System - 自动 RSS 巡航模块 (V2 降噪提纯版)
具备本地记忆去重、硬核 AI 关键词过滤、ArXiv 论文专属捕获能力。
"""

import json
import os
import time
from pathlib import Path
import feedparser
import requests

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
FEEDS_FILE = CONFIG_DIR / "feeds.json"
HISTORY_FILE = CONFIG_DIR / "feeder_history.json" # 💡 新增：本地记忆数据库
API_URL = "http://127.0.0.1:8000/api/ingest"

# 💡 核心升级：高价值情报过滤网 (只抓这些硬核内容)
AI_KEYWORDS = [
    "llm", "大模型", "agent", "智能体", "transformer", "rag", 
    "openai", "anthropic", "deepseek", "agi", "aigc", "gpu",
    "parameters", "context window", "fine-tuning", "微调",
    "dataset", "开源", "open source", "sora", "claude"
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
                
        print(f"  ✅ 发现 {len(feed.entries)} 篇，提纯出 {len(valid_articles)} 篇极密情报")
        return valid_articles
    except Exception as e:
        print(f"  ❌ 解析失败: {e}")
        return []

def send_to_api(url: str) -> bool:
    try:
        resp = requests.post(API_URL, json={"url": url}, timeout=10)
        if resp.status_code == 200:
            print(f"    🎯 成功发射至后端缓冲队列!")
            return True
        print(f"    ⚠️ API 拒绝接收: {resp.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"    ❌ 通讯阻断: {e}")
        return False

def run_auto_feeder():
    print("=" * 60)
    print("🚀 AI Tracker - 战略巡航舰启动 (SNR 过滤模式)")
    print("=" * 60)
    
    feeds = load_json_file(FEEDS_FILE, [])
    if not feeds:
        print("❌ 弹药库 (feeds.json) 为空！")
        return
        
    # 💡 加载本地记忆，防止重复提交
    history_list = load_json_file(HISTORY_FILE, [])
    history_set = set(history_list)
    
    total_pushed = 0
    new_history = list(history_list)
    
    for feed_url in feeds:
        print(f"\n📡 正在扫描空域: {feed_url}")
        target_urls = parse_feed(feed_url, history_set)
        
        for url in target_urls:
            print(f"    -> 锁定目标: {url}")
            if send_to_api(url):
                new_history.append(url)
                history_set.add(url)
                total_pushed += 1
            time.sleep(0.5)
            
    # 只保留最近 2000 条记忆，防止文件过大
    if len(new_history) > 2000:
        new_history = new_history[-2000:]
        
    save_json_file(HISTORY_FILE, new_history)
    print("=" * 60)
    print(f"🎉 巡航结束！本次成功向 V8 引擎输送了 {total_pushed} 篇硬核情报。")

if __name__ == "__main__":
    run_auto_feeder()