#!/usr/bin/env python3
"""
backfill.py - 历史数据回填引擎
独立于日常跟踪，按需触发，批量导入 2019-01-01 以来的重要事件
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timezone, timedelta
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

# ── 进度管理 ─────────────────────────────────────────────────────────────
def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed_sources": [], "last_url": None, "pushed_count": 0}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ── 任务推送 ──────────────────────────────────────────────────────────────
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
    """Write to SQLite and dispatch to Celery with lowest priority (9)"""  
    sys.path.insert(0, str(ROOT))
    from database import get_connection
    from worker import process_intel_task

    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, status FROM task_queue WHERE url = ?", (url,))
        row = c.fetchone()
        if row is None:
            from datetime import datetime as dt
            now = dt.now(timezone.utc).isoformat()
            c.execute(
                "INSERT INTO task_queue (url, status, created_at) VALUES (?, 'pending', ?)",
                (url, now)
            )
            conn.commit()
            task_id = c.lastrowid
            # Priority 9 = lowest, does not compete with daily tasks
            process_intel_task.apply_async(args=[task_id, url], priority=9)
            return True
        elif row[1] in ('failed', 'completed'):
            from datetime import datetime as dt
            now = dt.now(timezone.utc).isoformat()
            c.execute(
                "UPDATE task_queue SET status = 'pending', error_message = NULL, created_at = ? WHERE url = ?",
                (now, url)
            )
            conn.commit()
            process_intel_task.apply_async(args=[row[0], url], priority=9)
            return True
        else:
            return False
    finally:
        conn.close()


# ── 数据源基类 ─────────────────────────────────────────────────────────────
class Source:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    def get_urls(self) -> List[str]:
        raise NotImplementedError


# ── Wikipedia On-This-Day ──────────────────────────────────────────────────
class WikipediaOnThisDay(Source):
    def get_urls(self) -> List[str]:
        urls = []
        start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        current = start
        while current <= now:
            url = "https://en.wikipedia.org/wiki/" + current.strftime("%B_%d")
            urls.append(url)
            # 下一天
            if current.month == 12 and current.day == 31:
                current = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                current = current + timedelta(days=1)
        log.info("[Wikipedia] 生成 %d 个日期页面", len(urls))
        return urls


# ── arXiv ─────────────────────────────────────────────────────────────────
class ArxivSource(Source):
    def __init__(self, category: str):
        self.category = category
        super().__init__("arXiv " + category, "arXiv " + category + " papers")

    def get_urls(self) -> List[str]:
        urls = []
        start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        current = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
        while current <= now:
            year = current.year
            month = current.month
            url = (
                "https://export.arxiv.org/api/query?"
                "search_query=cat:" + self.category + "+AND+submittedDate:[" + str(year) + "%02d01+TO+" + str(year) + "%02d31]&sort_by=submittedDate&sort_order=descending&max_results=50"
            )
            urls.append(url)
            if month == 12:
                current = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                current = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        log.info("[arXiv %s] 生成 %d 个月度查询URL", self.category, len(urls))
        return urls


# ── Tech Blog ─────────────────────────────────────────────────────────────
class TechBlogSource(Source):
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


# ── Tech Media ──────────────────────────────────────────────────────────
class TechMediaSource(Source):
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


# ── 数据源清单 ───────────────────────────────────────────────────────────
def get_all_sources() -> List[Source]:
    return [
        WikipediaOnThisDay("Wikipedia On-This-Day", "Wikipedia 历史今日事件 2019-至今"),
        ArxivSource("cs.AI"),
        ArxivSource("cs.LG"),
        ArxivSource("cs.CL"),
        TechBlogSource(),
        TechMediaSource(),
    ]


# ── 回填单个数据源 ─────────────────────────────────────────────────────
def backfill_source(source: Source, force: bool = False):
    progress = load_progress()
    if source.name in progress.get("completed_sources", []) and not force:
        log.info("[%s] 已完成，跳过 (用 --force 强制重跑)", source.name)
        return

    log.info("[%s] 开始: %s", source.name, source.description)
    urls = source.get_urls()
    total = len(urls)
    log.info("[%s] 共 %d 个 URL", source.name, total)

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
            log.info("[%s] %d/%d 推送, %d 跳过", source.name, pushed, total, skipped)
            batch = []
            time.sleep(DELAY_BETWEEN_BATCHES)

    for u in batch:
        push_task(u)
        time.sleep(0.3)
    pushed += len(batch)

    if batch:
        time.sleep(DELAY_BETWEEN_BATCHES)

    log.info("[%s] 完成: %d 推送, %d 跳过", source.name, pushed, skipped)

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
            log.error("未知数据源: %s", sources)
            log.info("可用: %s", [s.name for s in all_sources])
            return
    else:
        targets = all_sources

    log.info("=" * 60)
    log.info("历史回填启动")
    log.info("数据源: %s", [s.name for s in targets])
    log.info("日期门槛: 2019-01-01")
    log.info("=" * 60)

    for source in targets:
        try:
            backfill_source(source, force=force)
        except KeyboardInterrupt:
            log.warning("中断信号，保存进度")
            break
        except Exception as e:
            log.error("[%s] 错误: %s", source.name, e, exc_info=True)
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
