#!/usr/bin/env python3
"""
Backfill script for AI Tracker System
Collects historical data from arXiv and GitHub Trending for 2026
Usage: python collect_backfill.py [--days N]
"""

import sys
import os
import json
import time
import feedparser
import requests
from datetime import datetime, timedelta
from database import get_connection

# Add project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ARXIV_API_URL = "http://export.arxiv.org/api/query"

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
            datetime.now().isoformat()
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"    Error saving paper: {e}")
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
            repo_data.get('source', 'github'),
            repo_data.get('trending_date'),
            json.dumps(repo_data.get('raw_metadata', {})),
            int(time.time())
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"    Error saving repo: {e}")
        return False
    finally:
        conn.close()

def parse_arxiv_date(date_str: str) -> datetime:
    """解析arXiv日期字符串"""
    try:
        # arXiv dates are like: 2026-03-15T12:00:00Z
        return datetime.strptime(date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    except:
        try:
            return datetime.strptime(date_str[:10], '%Y-%m-%d')
        except:
            return datetime.now()

def backfill_arxiv(days: int = 90):
    """Backfill arXiv papers from the past N days"""
    categories = ["cs.CL", "cs.AI", "cs.LG", "cs.CV"]
    max_results = 50
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    print(f"Backfilling arXiv papers from {start_date.date()} to {end_date.date()}")
    print(f"Initial delay to avoid rate limiting...")
    print(f"Categories: {', '.join(categories)}")

    total_count = 0
    for category in categories:
        print(f"\n  Processing category: {category}")
        time.sleep(5)  # Initial delay before each category

        all_items = []
        start = 0
        batch_size = 50

        while True:
            params = {
                "search_query": f"cat:{category}",
                "start": start,
                "max_results": batch_size,
                "sortBy": "submittedDate",
                "sortOrder": "descending"
            }

            try:
                response = requests.get(
                    ARXIV_API_URL,
                    params=params,
                    timeout=60,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Tracker/1.0)"}
                )
                response.raise_for_status()
                feed = feedparser.parse(response.content)

                if not feed.entries:
                    break

                batch_count = 0
                for entry in feed.entries:
                    published = parse_arxiv_date(entry.get("published", ""))

                    # Stop if we've passed the start date
                    if published < start_date:
                        break

                    # Extract PDF link
                    pdf_url = ""
                    for link in entry.get("links", []):
                        if link.get("type") == "application/pdf":
                            pdf_url = link.get("href", "")
                            break

                    # Extract arXiv ID
                    arxiv_id = entry.get("id", "").split("/")[-1]
                    arxiv_url = entry.get("id", "")

                    # Parse authors
                    authors = [a.get("name", "") for a in entry.get("authors", [])]

                    # Parse tags/categories
                    tags = [tag.get("term", "") for tag in entry.get("tags", [])]

                    # DOI
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
                        "arxiv_url": arxiv_url,
                        "pdf_url": pdf_url,
                        "categories": tags,
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

                    save_paper(paper_data)
                    batch_count += 1
                    total_count += 1

                print(f"    Collected {batch_count} papers (total: {total_count})")

                # If we got less than batch_size or we've passed start_date, we're done with this category
                if len(feed.entries) < batch_size:
                    break

                start += batch_size
                time.sleep(3)  # Be nice to arXiv API - 3 second delay between requests

            except Exception as e:
                print(f"    Error: {e}")
                break

    print(f"\narXiv backfill complete: {total_count} papers")
    return total_count

def backfill_github(days: int = 30):
    """Backfill GitHub Trending from the past N days"""
    from bs4 import BeautifulSoup

    print(f"Backfilling GitHub Trending (monthly)")

    url = "https://github.com/trending"
    try:
        response = requests.get(url, params={"since": "monthly"}, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")
        articles = soup.find_all("article", class_="Box-row")

        count = 0
        for article in articles:
            try:
                # Extract repo name
                a_tag = article.find("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                full_name = href.lstrip("/")

                # Description
                p_tag = article.find("p")
                description = p_tag.get_text(strip=True) if p_tag else ""

                # Language
                lang_span = article.find("span", itemprop="programmingLanguage")
                language = lang_span.get_text(strip=True) if lang_span else ""

                # Stars, Forks
                stars_text = ""
                forks_text = ""

                svg_tags = article.find_all("svg")
                for svg in svg_tags:
                    parent = svg.parent
                    if parent:
                        text = parent.get_text(strip=True)
                        if "star" in text.lower():
                            stars_text = text
                        elif "fork" in text.lower():
                            forks_text = text

                import re
                stars = int(re.sub(r'[^0-9]', '', stars_text)) if stars_text else 0
                forks = int(re.sub(r'[^0-9]', '', forks_text)) if forks_text else 0

                # Topics/Tags
                topics = []
                topic_tags = article.find_all("a", class_="topic-tag")
                for tag in topic_tags:
                    topic = tag.get_text(strip=True)
                    if topic:
                        topics.append(topic)

                # Owner avatar
                img_tag = article.find("img", class_="avatar")
                owner = img_tag.get("alt", "").lstrip("@") if img_tag else ""
                owner_url = f"https://github.com/{owner}" if owner else ""

                repo_data = {
                    "id": f"github:{full_name.replace('/', '_')}",
                    "name": full_name.split("/")[-1] if "/" in full_name else full_name,
                    "full_name": full_name,
                    "description": description,
                    "stars": stars,
                    "forks": forks,
                    "watchers": 0,
                    "open_issues": 0,
                    "language": language,
                    "license": "",
                    "topics": topics,
                    "owner": owner,
                    "owner_url": owner_url,
                    "created_at": "",
                    "updated_at": "",
                    "pushed_at": "",
                    "html_url": f"https://github.com/{full_name}",
                    "github_url": f"https://github.com/{full_name}",
                    "issues_url": f"https://github.com/{full_name}/issues",
                    "primary_language": language,
                    "languages": {},
                    "source": "github",
                    "trending_date": datetime.now().date().isoformat(),
                    "raw_metadata": {}
                }

                save_repository(repo_data)
                count += 1

            except Exception as e:
                print(f"  Error parsing repo: {e}")

        print(f"GitHub Trending backfill complete: {count} repos")
        return count

    except Exception as e:
        print(f"GitHub Trending error: {e}")
        return 0

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backfill AI Tracker data")
    parser.add_argument("--days", type=int, default=90, help="Number of days to backfill (default: 90)")
    parser.add_argument("--arxiv-only", action="store_true", help="Only backfill arXiv")
    parser.add_argument("--github-only", action="store_true", help="Only backfill GitHub")
    args = parser.parse_args()

    total_arxiv = 0
    total_github = 0

    if not args.github_only:
        total_arxiv = backfill_arxiv(args.days)

    if not args.arxiv_only:
        total_github = backfill_github(args.days)

    print(f"\nBackfill summary:")
    print(f"  arXiv papers: {total_arxiv}")
    print(f"  GitHub repos: {total_github}")
    print(f"  Total: {total_arxiv + total_github}")

if __name__ == "__main__":
    main()
