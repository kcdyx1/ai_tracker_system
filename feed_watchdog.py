#!/usr/bin/env python3
"""
feed_watchdog.py - RSS Feed 健康监控与告警系统

功能：
- 监控所有 RSS 源的最新更新时间
- 当源超过阈值未更新时自动告警
- 通过飞书 Webhook 推送告警
- 追踪连续失败次数
"""

import json
import os
import sys
import fcntl
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ── 路径配置 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
FEEDS_V2_FILE = CONFIG_DIR / "feeds_v2.json"
METADATA_FILE = CONFIG_DIR / "feeder_metadata.json"
HEALTH_FILE = CONFIG_DIR / "feed_health.json"      # 连续失败追踪
LOCK_FILE = ROOT / ".feed_watchdog.lock"

# ── 加载 .env ────────────────────────────────────────────────────────────────
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

# ── 告警阈值配置 ────────────────────────────────────────────────────────────
STALE_WARNING_DAYS = int(os.getenv("WATCHDOG_WARNING_DAYS", "7"))   # 7天未更新 → warning
STALE_CRITICAL_DAYS = int(os.getenv("WATCHDOG_CRITICAL_DAYS", "14"))  # 14天 → critical
SKIP_NEW_FEED_DAYS = int(os.getenv("WATCHDOG_SKIP_NEW_DAYS", "3"))   # 新增源3天内不告警

# ── 日志 ─────────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [watchdog] {msg}", flush=True)


# ── 工具函数 ────────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_feeds():
    """从 feeds_v2.json 加载所有 feed 元数据"""
    data = load_json(FEEDS_V2_FILE, {})
    feeds = {}
    tier_order = ["core", "standard", "extended", "wechat", "local"]
    for tier in tier_order:
        tier_data = data.get("tiers", {}).get(tier, {})
        for feed in tier_data.get("feeds", []):
            url = feed.get("url", "")
            if url:
                feeds[url] = {
                    "name": feed.get("name", url),
                    "tier": tier,
                    "priority": feed.get("priority", 5),
                    "quality": feed.get("quality", 3),
                    "tags": feed.get("tags", []),
                }
    return feeds


def load_metadata():
    """加载 feed 最后抓取时间"""
    return load_json(METADATA_FILE, {})


def load_health():
    """加载 feed 健康状态（连续失败次数）"""
    return load_json(HEALTH_FILE, {"consecutive_failures": {}})


def save_health(health):
    """保存 feed 健康状态"""
    save_json(HEALTH_FILE, health)


def calc_days_since(timestamp_str: str) -> float:
    """计算距离现在多少天（UTC）"""
    if not timestamp_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 86400
    except Exception:
        return float("inf")


def get_feed_age_days(feed_url: str, metadata: dict) -> float:
    """获取 feed 最新文章的年龄（天）"""
    last_crawl = metadata.get(feed_url, "")
    if not last_crawl:
        return float("inf")
    return calc_days_since(last_crawl)


# ── 飞书告警 ────────────────────────────────────────────────────────────────
def send_feishu_alert(alert_title: str, alert_body: str, alert_level: str = "warning"):
    """发送飞书卡片告警"""
    if not FEISHU_WEBHOOK_URL:
        log("⚠️ 未配置 FEISHU_WEBHOOK_URL，跳过告警")
        return

    template_map = {
        "warning": "orange",
        "critical": "red",
        "recovered": "green",
        "info": "blue",
    }
    template = template_map.get(alert_level, "orange")

    icon_map = {
        "warning": "🔶",
        "critical": "🔴",
        "recovered": "✅",
        "info": "ℹ️",
    }
    icon = icon_map.get(alert_level, "🔶")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": template,
                "title": {
                    "content": f"{icon} [AI-Tracker Watchdog] {alert_title}",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {"tag": "markdown", "content": alert_body},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": f"⏰ {now_str} UTC | 监控节点: AI-Tracker Watchdog"}]}
            ]
        }
    }

    try:
        import requests
        resp = requests.post(
            FEISHU_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()
        code = result.get("code") or result.get("StatusCode")
        if code == 0:
            log(f"✅ 飞书告警推送成功: {alert_title}")
        else:
            log(f"⚠️ 飞书响应异常: {result}")
    except Exception as e:
        log(f"❌ 飞书告警推送失败: {e}")


# ── 健康检查 ────────────────────────────────────────────────────────────────
def check_feed_health(feeds: dict, metadata: dict, health: dict) -> dict:
    """
    检查所有 feed 的健康状态
    返回 {url: {"status": "ok"|"warning"|"critical"|"new", "days": float, "name": str, ...}}
    """
    now = datetime.now(timezone.utc)
    results = {}
    consecutive = health.get("consecutive_failures", {})

    for url, info in feeds.items():
        last_crawl = metadata.get(url, "")
        days = get_feed_age_days(url, metadata)

        # 新增 feed（未抓取过）→ 标记为 new
        if not last_crawl:
            results[url] = {
                **info,
                "status": "new",
                "days": 0.0,
                "last_crawl": None,
                "consecutive_failures": consecutive.get(url, 0),
            }
            continue

        # 判断状态
        if days >= STALE_CRITICAL_DAYS:
            status = "critical"
        elif days >= STALE_WARNING_DAYS:
            status = "warning"
        else:
            status = "ok"
            # 恢复 → 重置连续失败计数
            if consecutive.get(url, 0) > 0:
                consecutive[url] = 0

        results[url] = {
            **info,
            "status": status,
            "days": round(days, 1),
            "last_crawl": last_crawl,
            "consecutive_failures": consecutive.get(url, 0),
        }

    return results


# ── 生成告警报告 ────────────────────────────────────────────────────────────
def build_alert_report(results: dict, feed_url_to_name: dict) -> tuple:
    """
    从检查结果中提取需要告警的 feed，生成飞书 markdown 报告
    返回 (warning_list, critical_list, recovered_list)
    """
    warning_feeds = []
    critical_feeds = []
    recovered_feeds = []

    for url, info in results.items():
        status = info["status"]
        name = info["name"]
        days = info["days"]
        last_crawl = info.get("last_crawl") or "从未抓取"

        if status == "critical":
            critical_feeds.append((name, url, days, last_crawl))
        elif status == "warning":
            warning_feeds.append((name, url, days, last_crawl))
        elif status == "recovered":
            recovered_feeds.append((name, url))

    return warning_feeds, critical_feeds, recovered_feeds


def format_alert_markdown(warning_feeds, critical_feeds, recovered_feeds, all_results: dict) -> str:
    """生成飞书告警卡片的 markdown 内容"""
    lines = []

    if critical_feeds:
        lines.append("### 🔴 严重失联 (≥14天未更新)")
        lines.append("")
        lines.append("| 名称 | 上次抓取 | 失联天数 |")
        lines.append("|------|----------|----------|")
        for name, url, days, last_crawl in critical_feeds:
            last_str = last_crawl[:16] if last_crawl and last_crawl != "从未抓取" else "从未抓取"
            lines.append(f"| [{name}]({url}) | {last_str} | **{days:.0f}天** |")
        lines.append("")

    if warning_feeds:
        lines.append("### 🔶 轻度失联 (≥7天未更新)")
        lines.append("")
        lines.append("| 名称 | 上次抓取 | 失联天数 |")
        lines.append("|------|----------|----------|")
        for name, url, days, last_crawl in warning_feeds:
            last_str = last_crawl[:16] if last_crawl and last_crawl != "从未抓取" else "从未抓取"
            lines.append(f"| [{name}]({url}) | {last_str} | {days:.0f}天 |")
        lines.append("")

    if recovered_feeds:
        lines.append("### ✅ 已恢复")
        lines.append("")
        for name, url in recovered_feeds:
            lines.append(f"- [{name}]({url})")
        lines.append("")

    # 健康统计
    total = len(all_results)
    ok_count = sum(1 for r in all_results.values() if r["status"] == "ok")
    new_count = sum(1 for r in all_results.values() if r["status"] == "new")
    lines.append("---")
    lines.append("")
    lines.append(f"**📊 健康统计**: 正常 {ok_count}/{total} | 新增源 {new_count}/{total} | 告警 {len(warning_feeds)} | 严重 {len(critical_feeds)}")

    return "\n".join(lines)


def format_summary_text(results: dict) -> str:
    """生成简洁的摘要文本"""
    warning = sum(1 for r in results.values() if r["status"] == "warning")
    critical = sum(1 for r in results.values() if r["status"] == "critical")
    recovered = sum(1 for r in results.values() if r["status"] == "recovered")
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    new = sum(1 for r in results.values() if r["status"] == "new")

    parts = []
    if critical > 0:
        parts.append(f"🔴 严重失联 {critical} 个源")
    if warning > 0:
        parts.append(f"🔶 轻度失联 {warning} 个源")
    if recovered > 0:
        parts.append(f"✅ 已恢复 {recovered} 个源")
    if ok > 0:
        parts.append(f"✅ 正常 {ok} 个源")
    if new > 0:
        parts.append(f"🆕 新增 {new} 个源")

    return " | ".join(parts) if parts else "无异常"


# ── 主检查流程 ───────────────────────────────────────────────────────────────
def run_watchdog(check_only: bool = False):
    """
    执行一次完整的健康检查

    Args:
        check_only: True 则只检查不发送告警（用于 dry-run）
    """
    log("=" * 60)
    log("🔍 Watchdog 健康检查启动")
    log(f"   阈值: warning={STALE_WARNING_DAYS}天, critical={STALE_CRITICAL_DAYS}天")
    log("=" * 60)

    feeds = load_feeds()
    metadata = load_metadata()
    health = load_health()

    if not feeds:
        log("⚠️ 未找到任何 feed 配置")
        return

    log(f"📡 正在监控 {len(feeds)} 个 RSS 源...")

    # 执行健康检查
    results = check_feed_health(feeds, metadata, health)

    # 分类汇总
    warning_feeds = [(url, info) for url, info in results.items() if info["status"] == "warning"]
    critical_feeds = [(url, info) for url, info in results.items() if info["status"] == "critical"]
    recovered_feeds = [(url, info) for url, info in results.items() if info["status"] == "recovered"]

    # 打印检查结果摘要
    summary = format_summary_text(results)
    log(f"📊 检查结果: {summary}")

    # 详细打印告警源
    if warning_feeds:
        log(f"\n🔶 轻度失联 ({len(warning_feeds)} 个):")
        for url, info in warning_feeds:
            log(f"   {info['name']}: {info['days']:.1f}天未更新")

    if critical_feeds:
        log(f"\n🔴 严重失联 ({len(critical_feeds)} 个):")
        for url, info in critical_feeds:
            log(f"   {info['name']}: {info['days']:.1f}天未更新")

    if recovered_feeds:
        log(f"\n✅ 已恢复 ({len(recovered_feeds)} 个):")
        for url, info in recovered_feeds:
            log(f"   {info['name']}")

    # 只有存在告警时才发送飞书通知
    has_alerts = len(warning_feeds) > 0 or len(critical_feeds) > 0 or len(recovered_feeds) > 0

    if has_alerts and not check_only:
        # 转换为 build_alert_report 需要的格式
        warn_list = [(info["name"], url, info["days"], info.get("last_crawl") or "从未抓取")
                     for url, info in warning_feeds]
        crit_list = [(info["name"], url, info["days"], info.get("last_crawl") or "从未抓取")
                     for url, info in critical_feeds]
        rec_list = [(info["name"], url) for url, info in recovered_feeds]

        alert_body = format_alert_markdown(warn_list, crit_list, rec_list, results)

        # 决定告警标题
        if critical_feeds:
            alert_title = f"🔴 严重失联 {len(critical_feeds)} 个RSS源!"
        elif warning_feeds:
            alert_title = f"🔶 轻度失联 {len(warning_feeds)} 个RSS源"
        else:
            alert_title = f"✅ {len(recovered_feeds)} 个RSS源已恢复"

        send_feishu_alert(alert_title, alert_body,
                         alert_level="critical" if critical_feeds else ("recovered" if recovered_feeds else "warning"))
    elif not has_alerts:
        log("✅ 所有 RSS 源运行正常，无需告警")
    else:
        log("ℹ️ check_only=True，跳过飞书告警推送")

    # 保存健康状态（更新连续失败计数）
    health["last_check"] = datetime.now(timezone.utc).isoformat()
    health["consecutive_failures"] = {
        url: info["consecutive_failures"]
        for url, info in results.items()
        if info["status"] in ("warning", "critical")
    }
    save_health(health)

    # P2-3: 检查关系失联
    try:
        stale = _check_stale_relationships()
        if stale:
            log("🕰️ 发现 " + str(len(stale)) + " 个关系超过" + str(STALE_RELATIONSHIP_DAYS) + "天无新事件")
            if not check_only:
                _send_stale_relationship_alert(stale)
        else:
            log("🕰️ 关系活跃度正常")
    except Exception as e:
        log("🕰️ 关系活跃度检查异常: " + str(e))

    log("✅ 本次检查完成")


# ── CLI ─────────────────────────────────────────────────────────────────────
# ── P2-3: 关键变更告警 ────────────────────────────────────────────────────────
STALE_RELATIONSHIP_DAYS = 30


def _check_stale_relationships() -> list:
    """检查超过30天无新事件的实体关系"""
    from database_pg import get_connection
    from datetime import datetime, timezone, timedelta

    conn = get_connection()
    cur = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_RELATIONSHIP_DAYS)).strftime("%Y-%m-%d")

    cur.execute("""
        SELECT r.source_id, r.target_id, r.relation_type, r.last_event_date,
               e1.name as source_name, e2.name as target_name
        FROM relationships r
        LEFT JOIN entities e1 ON r.source_id = e1.id
        LEFT JOIN entities e2 ON r.target_id = e2.id
        WHERE r.last_event_date IS NULL OR r.last_event_date < %s
        ORDER BY r.last_event_date NULLS FIRST
        LIMIT 30
    """, (cutoff,))

    stale = []
    for row in cur.fetchall():
        last_date = row["last_event_date"]
        if last_date:
            try:
                dt_last = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - dt_last).days
            except:
                days_since = 999
        else:
            days_since = 999

        stale.append({
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation_type": row["relation_type"],
            "source_name": row["source_name"] or row["source_id"],
            "target_name": row["target_name"] or row["target_id"],
            "last_event_date": last_date,
            "days": days_since,
        })

    conn.close()
    return stale


def _send_stale_relationship_alert(stale_list: list):
    """发送关系失联告警到飞书"""
    if not stale_list or not FEISHU_WEBHOOK_URL:
        return

    nl = chr(10)  # literal newline
    lines = []
    lines.append(nl + "**关系失联告警**（实体超过30天无新事件）" + nl)
    lines.append("| 实体 | 关系 | 另一方 | 最后事件 | 失联天数 |")
    lines.append("|---|---|---|---|---|")

    for item in stale_list[:15]:
        last = item["last_event_date"] or "从未记录"
        lines.append(
            "| " + item["source_name"] + " | " + item["relation_type"] + " "
            "| " + item["target_name"] + " | " + last + " | " + str(item["days"]) + "天 |"
        )

    body = nl.join(lines)
    alert_level = "warning" if len(stale_list) < 10 else "critical"
    send_feishu_alert(
        "⚠️ " + str(len(stale_list)) + " 个关系超过30天无新动态",
        body,
        alert_level=alert_level
    )



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI-Tracker RSS Feed Watchdog")
    parser.add_argument("--check", action="store_true", help="仅检查不发送告警（dry-run）")
    args = parser.parse_args()

    # 并发防护
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("⚠️ 检测到另一个 watchdog 实例正在运行，退出。")
        sys.exit(0)

    try:
        run_watchdog(check_only=args.check)
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
