#!/usr/bin/env python3
"""
AI Tracker System - 统一情报采集器 (Universal Intelligence Collector)
支持 RSS/API/关键词监控 等多种数据源

采集类型:
- RSS: 标准 RSS/Atom 订阅源
- API: arXiv, GitHub Trending, HackerNews, Semantic Scholar
- Keywords: 基于关键词的搜索引擎/新闻监控
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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置路径
CONFIG_DIR = Path(__file__).parent / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
FEEDS_V2_FILE = CONFIG_DIR / "feeds_v2.json"
FEEDS_UNIFIED_FILE = CONFIG_DIR / "feeds_unified.json"
HISTORY_FILE = CONFIG_DIR / "collector_history.json"
METADATA_FILE = CONFIG_DIR / "collector_metadata.json"
DB_PATH = Path(__file__).parent / "ai_tracker.db"

# API 配置
ARXIV_API_URL = "http://export.arxiv.org/api/query"
GITHUB_API_URL = "https://api.github.com"
HACKERNEWS_API = "https://hacker-news.firebaseio.com/v0"

# 高价值 AI 关键词过滤网
AI_KEYWORDS = {
    "llm", "大模型", "vlm", "多模态", "moe", "混合专家", "slm", "端侧模型",
    "transformer", "diffusion", "dit", "agi", "aigc", "大语言模型", "具身智能",
    "openai", "chatgpt", "sora", "gpt-4", "o1", "o3", "anthropic", "claude",
    "google", "gemini", "gemma", "meta", "llama", "deepseek", "深度求索",
    "moonshot", "kimi", "月之暗面", "minimax", "稀宇科技", "zhipu", "智谱",
    "qwen", "通义千问", "baichuan", "百川", "mistral", "xai", "grok",
    "rag", "graphrag", "检索增强", "知识图谱", "knowledge graph",
    "neo4j", "图数据库", "chroma", "milvus", "qdrant", "向量数据库",
    "agent", "智能体", "multi-agent", "多智能体", "ai-native", "ai原生",
    "langchain", "llamaindex", "autogen", "crewai", "dify", "coze",
    "gpu", "tpu", "npu", "nvidia", "英伟达", "h100", "b200", "gb200", "cuda",
    "startup", "funding", "series a", "series b", "acquisition", "ipo",
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    "open source", "开源", "huggingface", "github", "local deployment"
}

# 白名单域名 (高质量源，直接通过)
WHITELIST_DOMAINS = {
    "arxiv.org", "openai.com", "anthropic.com", "deepmind.google", "ai.google",
    "huggingface.co", "meta.ai", "blogs.nvidia.com", "aws.amazon.com",
    "azure.microsoft.com", "microsoft.com/research", "bai.com", "baidu.com",
    "tencent.com", "alibaba.com", "bytedance.com", "x.ai", "mistral.ai",
    "cohere.com", "stability.ai", "midjourney.com", "runwayml.com",
    "databricks.com", "snowflake.com", "zilliz.com", "qdrant.tech",
    "weaviate.io", "pinecone.io", "chroma.ai", "llamaindex.ai", "langchain.dev"
}


# ============================================================
# 数据库操作
# ============================================================

def get_connection():
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def save_paper(paper_data: dict) -> bool:
    """保存论文到数据库"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO papers (
                id, title, abstract, authors, published_date, updated_date,
                arxiv_id, arxiv_url, pdf_url, categories, comment, doi,
                citation_count, reference_count, source, source_url, raw_metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    """保存 GitHub 仓库到数据库"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO repositories (
                id, name, full_name, description, stars, forks, watchers, open_issues,
                language, license, topics, owner, owner_url, created_at, updated_at,
                pushed_at, html_url, github_url, issues_url, primary_language, languages,
                source, trending_date, raw_metadata, created_at_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def push_task(url: str) -> bool:
    """推送 URL 到任务队列"""
    from database import push_task as db_push_task
    return db_push_task(url)


# ============================================================
# 情报条目数据模型
# ============================================================

@dataclass
class IntelItem:
    """情报条目"""
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
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "source_type": self.source_type,
            "published_at": self.published_at,
            "author": self.author,
            "tags": self.tags,
            "quality": self.quality,
            "priority": self.priority,
            "metadata": self.metadata
        }


# ============================================================
# 采集器基类
# ============================================================

class BaseCollector(ABC):
    """采集器基类"""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "Unknown")
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def collect(self) -> List[IntelItem]:
        """执行采集"""
        pass

    def is_high_value(self, title: str, summary: str = "", url: str = "") -> bool:
        """判断是否为高价值情报"""
        text = f"{title} {summary}".lower()

        for domain in WHITELIST_DOMAINS:
            if domain in url.lower():
                return True

        for kw in AI_KEYWORDS:
            if kw.lower() in text:
                return True

        return False

    def filter_items(self, items: List[IntelItem]) -> List[IntelItem]:
        """过滤低质量条目"""
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


# ============================================================
# RSS 采集器
# ============================================================

class RSSCollector(BaseCollector):
    """RSS 订阅源采集器"""

    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []

        url = self.config.get("url", "")
        if not url:
            return []

        logger.info(f"  📡 抓取 RSS: {self.name}")

        try:
            response = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"
            })
            response.raise_for_status()

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
                    metadata={
                        "feed_url": url,
                        "categories": entry.get("tags", [])
                    }
                )
                items.append(item)

            logger.info(f"    ✅ 获取 {len(items)} 条 RSS 条目")
            return self.filter_items(items)

        except Exception as e:
            logger.error(f"    ❌ RSS 抓取失败: {e}")
            return []


# ============================================================
# arXiv API 采集器 (完善版)
# ============================================================

class ArXivCollector(BaseCollector):
    """arXiv API 采集器 - 获取完整论文元数据"""

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
            time.sleep(0.5)  # 避免请求过快

        logger.info(f"    ✅ arXiv 共获取 {len(all_items)} 篇论文")
        return all_items

    def _collect_category(self, category: str, max_results: int) -> List[IntelItem]:
        """采集单个类别的论文"""
        items = []

        try:
            params = {
                "search_query": f"cat:{category}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending"
            }

            response = requests.get(
                ARXIV_API_URL,
                params=params,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"}
            )
            response.raise_for_status()

            feed = feedparser.parse(response.content)

            for entry in feed.entries:
                # 提取 PDF 链接
                pdf_url = ""
                for link in entry.get("links", []):
                    if link.get("type") == "application/pdf":
                        pdf_url = link.get("href", "")
                        break

                # arXiv ID 提取
                arxiv_id = entry.get("id", "").split("/")[-1]
                arxiv_url = entry.get("id", "")

                # 解析作者
                authors = [a.get("name", "") for a in entry.get("authors", [])]

                # 解析分类
                categories = []
                for tag in entry.get("tags", []):
                    term = tag.get("term", "")
                    if term:
                        categories.append(term)

                # DOI
                doi = ""
                for attr in entry.get("arxiv_doi", []):
                    doi = attr.get("value", "")
                    break

                # 论文数据
                paper_data = {
                    "id": f"arxiv:{arxiv_id}",
                    "title": entry.get("title", "").replace("\n", " ").strip(),
                    "abstract": entry.get("summary", "")[:2000],
                    "authors": authors,
                    "published_date": entry.get("published", ""),
                    "updated_date": entry.get("updated", ""),
                    "arxiv_id": arxiv_id,
                    "arxiv_url": arxiv_url,
                    "pdf_url": pdf_url,
                    "categories": categories,
                    "comment": entry.get("arxiv_comment", ""),
                    "doi": doi,
                    "citation_count": 0,
                    "source": "arxiv",
                    "source_url": pdf_url or arxiv_url,
                    "raw_metadata": {
                        "journal_ref": entry.get("arxiv_journal_ref", ""),
                        "doi": doi,
                        "primary_category": category
                    }
                }

                # 保存到数据库
                save_paper(paper_data)

                # 创建 IntelItem
                item = IntelItem(
                    url=pdf_url or arxiv_url,
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


# ============================================================
# GitHub Trending 采集器 (完善版)
# ============================================================

class GitHubTrendingCollector(BaseCollector):
    """GitHub Trending 采集器 - 完善 HTML 解析"""

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
        """采集单个语言的 Trending"""
        items = []

        try:
            # 使用 GitHub Trending 页面
            url = f"https://github.com/trending/{language}?since=daily"

            response = requests.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)",
                    "Accept": "text/html"
                }
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 解析每个仓库条目
            repo_articles = soup.find_all('article', class_='Box-row')

            for article in repo_articles[:20]:  # 取前20个
                try:
                    # 提取仓库名
                    title_tag = article.select_one('h2 a')
                    if not title_tag:
                        continue

                    full_name = title_tag.get('href', '').lstrip('/')
                    name = full_name.split('/')[-1] if '/' in full_name else full_name

                    # 提取描述
                    desc_tag = article.select_one('p')
                    description = desc_tag.get_text(strip=True) if desc_tag else ""

                    # 过滤非 AI 相关
                    if not self.is_high_value(name, description):
                        continue

                    # 提取 URL
                    repo_url = f"https://github.com/{full_name}"

                    # 提取 Stars
                    stars_tag = article.select_one('a[href$="/stargazers"]')
                    stars_text = stars_tag.get_text(strip=True) if stars_tag else "0"
                    stars = self._parse_number(stars_text)

                    # 提取 Forks
                    forks_tag = article.select_one('a[href$="/network/members"]')
                    forks_text = forks_tag.get_text(strip=True) if forks_tag else "0"
                    forks = self._parse_number(forks_text)

                    # 提取语言
                    lang_tag = article.select_one('span[itemprop="programmingLanguage"]')
                    primary_language = lang_tag.get_text(strip=True) if lang_tag else None

                    # 提取今日星数
                    today_stars = 0
                    today_tag = article.select_one('span.d-inline-block.float-sm-right')
                    if today_tag:
                        today_text = today_tag.get_text(strip=True)
                        today_stars = self._parse_number(today_text)

                    # 仓库数据
                    repo_data = {
                        "id": f"github:{full_name}",
                        "name": name,
                        "full_name": full_name,
                        "description": description,
                        "stars": stars,
                        "forks": forks,
                        "watchers": 0,
                        "open_issues": 0,
                        "language": primary_language,
                        "license": None,
                        "topics": [],
                        "owner": full_name.split('/')[0] if '/' in full_name else full_name,
                        "owner_url": f"https://github.com/{full_name.split('/')[0] if '/' in full_name else full_name}",
                        "created_at": None,
                        "updated_at": None,
                        "pushed_at": None,
                        "html_url": repo_url,
                        "github_url": repo_url,
                        "issues_url": f"{repo_url}/issues",
                        "primary_language": primary_language,
                        "languages": {},
                        "source": "github_trending",
                        "trending_date": trending_date,
                        "raw_metadata": {
                            "today_stars": today_stars,
                            "description": description
                        }
                    }

                    # 保存到数据库
                    save_repository(repo_data)

                    # 创建 IntelItem
                    item = IntelItem(
                        url=repo_url,
                        title=f"⭐ {stars} | {name}",
                        summary=description[:300],
                        source="GitHub Trending",
                        source_type="repository",
                        published_at=trending_date,
                        author=repo_data["owner"],
                        tags=["开源", "GitHub", "Trending", language] + ([primary_language] if primary_language else []),
                        quality=4,
                        priority=self.config.get("priority", 8),
                        metadata=repo_data
                    )
                    items.append(item)

                except Exception as e:
                    logger.debug(f"    ⚠️ 解析仓库条目失败: {e}")

        except Exception as e:
            logger.error(f"    ❌ GitHub Trending 错误 ({language}): {e}")

        return items

    def _parse_number(self, text: str) -> int:
        """解析数字 (如 1.2k, 3.4M)"""
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


# ============================================================
# HackerNews 采集器
# ============================================================

class HackerNewsCollector(BaseCollector):
    """Hacker News 采集器"""

    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []

        config = self.config.get("config", {})
        points_threshold = config.get("points_threshold", 50)

        logger.info(f"  📰 抓取 Hacker News (threshold: {points_threshold})")

        items = []

        try:
            response = requests.get(
                f"{HACKERNEWS_API}/topstories.json",
                timeout=30
            )
            response.raise_for_status()
            story_ids = response.json()[:50]

            for story_id in story_ids[:20]:
                try:
                    story_response = requests.get(
                        f"{HACKERNEWS_API}/item/{story_id}.json",
                        timeout=10
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
                        metadata={
                            "hn_id": story_id,
                            "score": score,
                            "comments": story.get("descendants", 0)
                        }
                    )
                    items.append(item)

                    time.sleep(0.1)

                except Exception as e:
                    logger.debug(f"    ⚠️ HN story 解析错误: {e}")

            logger.info(f"    ✅ Hacker News: {len(items)} 条高价值条目")

        except Exception as e:
            logger.error(f"    ❌ Hacker News API 错误: {e}")

        return items


# ============================================================
# Semantic Scholar 采集器
# ============================================================

class SemanticScholarCollector(BaseCollector):
    """Semantic Scholar 学术论文采集器"""

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
                "query": query,
                "limit": limit,
                "sort": "recency",
                "fields": "title,abstract,authors,year,venue,citationCount,openAccessPdf,externalIds"
            }

            response = requests.get(
                url,
                params=params,
                timeout=30,
                headers={"User-Agent": "AI-Tracker/1.0"}
            )
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
                    "raw_metadata": {
                        "venue": paper.get("venue"),
                        "paperId": paper.get("paperId")
                    }
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


# ============================================================
# Reddit 采集器
# ============================================================

class RedditCollector(BaseCollector):
    """Reddit 社区采集器"""

    def collect(self) -> List[IntelItem]:
        if not self.enabled:
            return []

        config = self.config.get("config", {})
        subreddit = config.get("subreddit", "MachineLearning")
        limit = config.get("limit", 25)

        logger.info(f"  💬 抓取 Reddit r/{subreddit}")

        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.json"
            params = {"limit": limit}

            response = requests.get(
                url,
                params=params,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"}
            )
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
                    metadata={
                        "score": post_data.get("score"),
                        "num_comments": post_data.get("num_comments"),
                        "subreddit": subreddit
                    }
                )
                items.append(item)

            logger.info(f"    ✅ Reddit r/{subreddit}: {len(items)} 条")
            return items

        except Exception as e:
            logger.error(f"    ❌ Reddit API 错误: {e}")
            return []


# ============================================================
# 采集器注册表
# ============================================================

COLLECTORS = {
    "rss": RSSCollector,
    "arxiv_api": ArXivCollector,
    "github_trending": GitHubTrendingCollector,
    "hackernews": HackerNewsCollector,
    "semantic_scholar": SemanticScholarCollector,
    "reddit_ai": RedditCollector,
}


# ============================================================
# 历史记录管理器
# ============================================================

class HistoryManager:
    """历史记录管理器"""

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


# ============================================================
# 统一采集器
# ============================================================

class UnifiedCollector:
    """统一采集器 - 管理所有数据源"""

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
        """初始化所有采集器"""
        sources = self.config.get("sources", {})

        # RSS 采集器
        for rss_config in sources.get("rss", {}).get("items", []):
            if rss_config.get("enabled", True):
                collector = RSSCollector(rss_config)
                self._collectors[f"rss_{rss_config['url']}"] = collector

        # API 采集器
        for api_config in sources.get("api", {}).get("items", []):
            if api_config.get("enabled", True):
                collector_type = api_config.get("type")
                if collector_type in COLLECTORS:
                    collector = COLLECTORS[collector_type](api_config)
                    self._collectors[f"api_{collector_type}"] = collector

        logger.info(f"已初始化 {len(self._collectors)} 个采集器")

    def collect_all(self, source_types: List[str] = None) -> List[IntelItem]:
        """执行全量采集"""
        all_items = []

        for name, collector in self._collectors.items():
            if source_types:
                collector_type = name.split("_")[0]
                if collector_type not in source_types:
                    continue

            logger.info(f"\n🔍 执行采集: {name}")
            items = collector.collect()

            # 去重
            new_items = []
            for item in items:
                if item.url not in self.history:
                    new_items.append(item)
                    self.history.add(item.url)

            all_items.extend(new_items)

            # 随机延迟
            time.sleep(random.uniform(0.5, 1.5))

        return all_items

    def collect_rss(self) -> List[IntelItem]:
        """只采集 RSS 源"""
        return self.collect_all(["rss"])

    def collect_api(self) -> List[IntelItem]:
        """只采集 API 源"""
        return self.collect_all(["api"])

    def collect_papers(self) -> List[IntelItem]:
        """只采集论文 (arXiv + Semantic Scholar)"""
        return self.collect_all(["api"])

    def get_stats(self) -> dict:
        """获取采集统计"""
        stats = {
            "total_collectors": len(self._collectors),
            "rss_count": sum(1 for n in self._collectors if n.startswith("rss_")),
            "api_count": sum(1 for n in self._collectors if n.startswith("api_")),
            "history_size": len(self.history)
        }
        return stats


# ============================================================
# API 端点
# ============================================================

def get_collector_stats() -> dict:
    """获取采集器统计"""
    collector = UnifiedCollector()
    return collector.get_stats()


def run_collection(source_types: List[str] = None) -> dict:
    """执行采集并返回结果"""
    collector = UnifiedCollector()
    items = collector.collect_all(source_types)

    return {
        "collected": len(items),
        "items": [item.to_dict() for item in items],
        "stats": collector.get_stats()
    }


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AI Tracker - 统一情报采集器 v2.0")
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

    # 采集所有
    items = collector.collect_all()

    print("\n" + "=" * 60)
    print(f"✅ 采集完成! 获取 {len(items)} 条新情报")
    print("=" * 60)

    # 发送到后端
    sent_count = 0
    for item in items:
        if item.source_type in ["rss", "hn", "reddit"]:
            if push_task(item.url):
                sent_count += 1

    print(f"📤 已发送 {sent_count} 条到处理队列 (仅 RSS/HN/Reddit)")
