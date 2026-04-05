#!/usr/bin/env python3
"""
backfill.py - 历史数据回填引擎
独立于日常跟踪，按需触发，批量导入 2019-01-01 以来的重要事件

用法:
  python backfill.py                    # 回填全部数据源
  python backfill.py -s wikipedia      # 只回填指定数据源
  python backfill.py --reset           # 重置进度
"""
import os
import sys
import time
import json
import signal
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# ── 配置 ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
PROGRESS_FILE = ROOT / ".backfill_progress.json"
BATCH_SIZE = 20
DELAY_BETWEEN_BATCHES = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "backfill.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("backfill")

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "sk-xv7avxH7fcB3pN3INjuSHsvfIzzYDB6itaz60IsMP404QtKx")
MINIMAX_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "http://114.132.200.116:3888/")


# ── 进度管理 ─────────────────────────────────────────────────────────────
def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed_sources": [], "last_url": None, "pushed_count": 0}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ── URL 去重检查 ──────────────────────────────────────────────────────────
def task_exists(url: str) -> bool:
    sys.path.insert(0, str(ROOT))
    from database import get_connection
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM task_queue WHERE url = ? LIMIT 1", (url,))
        return c.fetchone() is not None
    finally:
        conn.close()


def push_task(url: str) -> bool:
    sys.path.insert(0, str(ROOT))
    from database import push_task
    return push_task(url)


# ── 数据源基类 ─────────────────────────────────────────────────────────────
class Source:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    def get_urls(self) -> List[str]:
        raise NotImplementedError


# ── Wikipedia On-This-Day ──────────────────────────────────────────────────
class WikipediaOnThisDay(Source):
    """
    Wikipedia On-This-Day: 每天的历史事件
    生成 2019-01-01 以来的每月每日 URL
    """

    def get_urls(self) -> List[str]:
        urls = []
        start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        current = start
        while current <= now:
            month = current.strftime("%m")
            day = current.strftime("%d")
            # Wikipedia On-This-Day 事件页面
            url = f"https://en.wikipedia.org/wiki/{current.strftime('%B_%d')}"
            urls.append(url)
            # 下一天
            if current.month == 12 and current.day == 31:
                current = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                day_of_year = current.timetuple().tm_yday
                if day_of_year >= 365 and current.month == 12:
                    current = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    from datetime import timedelta
                    current = current + timedelta(days=1)

        log.info(f"[Wikipedia] 生成 {len(urls)} 个日期页面")
        return urls


# ── Wikipedia Featured Articles (历史上的今天) ─────────────────────────────
class WikipediaFeaturedArticles(Source):
    """
    Wikipedia Featured articles for each day going back 5 years
    """

    def get_urls(self) -> List[str]:
        urls = []
        now = datetime.now(timezone.utc)

        # 生成过去5年每月1日的"历史上的今天"页面
        for year in range(2019, now.year + 1):
            for month in range(1, 13):
                if year == now.year and month > now.month:
                    break
                dt = datetime(year, month, 1, tzinfo=timezone.utc)
                url = f"https://en.wikipedia.org/wiki/{dt.strftime('%B_%Y')}"
                urls.append(url)

        log.info(f"[Wikipedia Featured] 生成 {len(urls)} 个页面")
        return urls


# ── arXiv ─────────────────────────────────────────────────────────────────
class ArxivSource(Source):
    """
    arXiv cs.AI/cs.LG/cs.CL 论文
    使用 Atom Feed 格式，按月抓取
    """

    def __init__(self, category: str):
        self.category = category
        super().__init__(f"arXiv {category}", f"arXiv {category} papers")

    def get_urls(self) -> List[str]:
        urls = []
        categories_map = {
            "cs.AI": "cs.AI",
            "cs.LG": "cs.LG",
            "cs.CL": "cs.CL",
        }
        cat = categories_map.get(self.category, self.category)

        # 按月生成
        start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        current = datetime(start.year, start.month, 1, tzinfo=timezone.utc)

        while current <= now:
            year = current.year
            month = current.month
            url = (
                f"https://export.arxiv.org/api/query?"
                f"search_query=cat:{cat}+AND+submittedDate:[{year}{month:02d}01+TO+{year}{month:02d}31]"
                f"&sort_by=submittedDate&sort_order=descending&max_results=50"
            )
            urls.append(url)

            if month == 12:
                current = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                current = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        log.info(f"[arXiv {cat}] 生成 {len(urls)} 个月度查询URL")
        return urls


# ── 重要 AI 公司官方博客 ─────────────────────────────────────────────────
class TechBlogSource(Source):
    """主要 AI 公司官方博客列表页"""

    def __init__(self):
        super().__init__("Tech Blogs", "AI company official blogs")

    def get_urls(self) -> List[str]:
        return [
            "https://openai.com/blog/",
            "https://www.anthropic.com/news",
            "https://www.anthropic.com/research",
            "https://blog.google/technology/ai/",
            "https://deepmind.google/discover/blog/",
            "https://ai.meta.com/blog/",
            "https://blogs.microsoft.com/ai/",
            "https://blogs.nvidia.com/blog/category/deep-learning/",
            "https://huggingface.co/blog",
            "https://stability.ai/news",
            "https://mistral.ai/news/",
            "https://cohere.com/blog",
            "https://x.ai/blog",
            "https://www.deepmind.com/blog",
            "https://ai.google/research",
        ]


# ── 权威科技媒体 ──────────────────────────────────────────────────────────
class TechMediaSource(Source):
    """科技媒体 AI 相关页面"""

    def __init__(self):
        super().__init__("Tech Media", "Technology media AI coverage")

    def get_urls(self) -> List[str]:
        return [
            "https://www.theverge.com/ai-artificial-intelligence",
            "https://techcrunch.com/category/artificial-intelligence/",
            "https://www.wired.com/tag/artificial-intelligence/",
            "https://venturebeat.com/category/ai/",
            "https://www.sciencemag.org/news/physics",
        ]


# ── 全部数据源清单 ────────────────────────────────────────────────────────
def get_all_sources() -> List[Source]:
    return [
        WikipediaOnThisDay("Wikipedia On-This-Day", "Wikipedia 历史今日事件 2019-至今"),
        ArxivSource("cs.AI"),
        ArxivSource("cs.LG"),
        ArxivSource("cs.CL"),
        TechBlogSource(),
        TechMediaSource(),
    ]


# ── 回填单个数据源 ───────────────────────────────────────────────────────
def backfill_source(source: Source, force: bool = False):
    progress = load_progress()

    if source.name in progress.get("completed_sources", []) and not force:
        log.info(f"[{source.name}] 已完成，跳过 (用 --force 强制重跑)")
        return

    log.info(f"[{source.name}] 开始: {source.description}")
    urls = source.get_urls()
    total = len(urls)
    log.info(f"[{source.name}] 共 {total} 个 URL")

    pushed = skipped = 0
    batch = []

    for i, url in enumerate(urls):
        if task_exists(url):
            skipped += 1
            continue

        batch.append(url)

        if len(batch) >= BATCH_SIZE:
            for u in batch:
                push_task(u)
                time.sleep(0.3)
            pushed += len(batch)
            log.info(f"[{source.name}] {pushed}/{total} 推送, {skipped} 跳过")
            batch = []
            time.sleep(DELAY_BETWEEN_BATCHES)

    for u in batch:
        push_task(u)
        time.sleep(0.3)
    pushed += len(batch)

    if batch:
        time.sleep(DELAY_BETWEEN_BATCHES)

    log.info(f"[{source.name}] 完成: {pushed} 推送, {skipped} 跳过")

    progress = load_progress()
    completed = progress.get("completed_sources", [])
    if source.name not in completed:
        completed.append(source.name)
    progress["completed_sources"] = completed
    progress["pushed_count"] = progress.get("pushed_count", 0) + pushed
    save_progress(progress)


# ── 主程序 ─────────────────────────────────────────────────────────────
def run(sources=None, force=False, reset=False):
    if reset and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        log.info("进度已重置")

    all_sources = get_all_sources()

    if sources:
        targets = [s for s in all_sources if s.name in sources]
        if not targets:
            log.error(f"未知数据源: {sources}")
            log.info(f"可用: {[s.name for s in all_sources]}")
            return
    else:
        targets = all_sources

    log.info("=" * 60)
    log.info(f"历史回填启动")
    log.info(f"数据源: {[s.name for s in targets]}")
    log.info(f"日期门槛: 2019-01-01")
    log.info("=" * 60)

    for source in targets:
        try:
            backfill_source(source, force=force)
        except KeyboardInterrupt:
            log.warning("中断信号，保存进度")
            break
        except Exception as e:
            log.error(f"[{source.name}] 错误: {e}", exc_info=True)
            continue

    log.info("回填完成!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="历史数据回填")
    parser.add_argument("-s", "--sources", nargs="+", help="指定数据源名称")
    parser.add_argument("-f", "--force", action="store_true", help="强制重跑已完成的数据源")
    parser.add_argument("--reset", action="store_true", help="重置进度")
    args = parser.parse_args()
    run(sources=args.sources, force=args.force, reset=args.reset)
