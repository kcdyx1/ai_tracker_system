#!/usr/bin/env python3
"""
AI Tracker System - 自动 RSS 巡航模块

读取 config/feeds.json，解析最新文章并推送到任务队列
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
API_URL = "http://127.0.0.1:8000/api/ingest"


def load_feeds() -> list:
    """加载 RSS 订阅列表"""
    if not FEEDS_FILE.exists():
        print(f"❌ 配置文件不存在: {FEEDS_FILE}")
        return []
    
    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_feed(feed_url: str) -> list:
    """
    解析 RSS Feed，返回最新文章链接列表
    
    Args:
        feed_url: RSS 订阅地址
        
    Returns:
        文章链接列表
    """
    try:
        feed = feedparser.parse(feed_url)
        
        if not feed.entries:
            print(f"  ⚠️ Feed 无内容: {feed_url}")
            return []
        
        # 获取最新 3 篇文章
        articles = []
        for entry in feed.entries[:3]:
            if hasattr(entry, 'link'):
                articles.append(entry.link)
        
        print(f"  ✅ 解析到 {len(articles)} 篇文章")
        return articles
        
    except Exception as e:
        print(f"  ❌ 解析失败: {e}")
        return []


def send_to_api(url: str) -> bool:
    """
    发送 URL 到 API
    
    Args:
        url: 文章链接
        
    Returns:
        是否成功
    """
    try:
        response = requests.post(
            API_URL,
            json={"url": url},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"    ✅ 已推送: {data.get('message')}")
            return True
        else:
            print(f"    ❌ API 错误: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"    ❌ 请求失败: {e}")
        return False


def run_auto_feeder():
    """运行自动巡航"""
    print("=" * 50)
    print("🚀 AI Tracker 自动巡航启动")
    print("=" * 50)
    
    # 加载 feeds
    feeds = load_feeds()
    
    if not feeds:
        print("❌ 没有可用的 RSS 源")
        return
    
    print(f"\n📡 发现 {len(feeds)} 个 RSS 源:\n")
    
    total_articles = 0
    
    for feed_url in feeds:
        print(f"🔄 正在处理: {feed_url}")
        
        # 解析 feed
        articles = parse_feed(feed_url)
        
        # 推送每篇文章
        for article_url in articles:
            send_to_api(article_url)
            time.sleep(0.5)  # 避免请求过快
        
        total_articles += len(articles)
    
    print(f"\n🎉 完成! 共推送 {total_articles} 篇文章")


if __name__ == "__main__":
    run_auto_feeder()
