# -*- coding: utf-8 -*-
"""
微信公众号草稿箱 API 接入模块
将报告文本写入微信公众号草稿箱，等待人工确认发布
"""

import os
import json
import time
import requests
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from pathlib import Path

# 从 markdown_to_wechat_html 导入
try:
    from markdown_to_wechat_html import markdown_to_wechat_html, wrap_wechat_article
except ImportError:
    # 本地导入
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from markdown_to_wechat_html import markdown_to_wechat_html, wrap_wechat_article

# Token 缓存文件
_TOKEN_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "wechat_token_cache.json")


def _load_token() -> tuple[str, int]:
    """加载缓存的 access_token 及过期时间"""
    cache_file = Path(_TOKEN_CACHE_FILE)
    if not cache_file.exists():
        return "", 0
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
        return data.get("access_token", ""), data.get("expires_at", 0)
    except Exception:
        return "", 0


def _save_token(access_token: str, expires_in: int):
    """缓存 access_token"""
    expires_at = int(time.time()) + expires_in - 300  # 提前5分钟过期
    cache_file = Path(_TOKEN_CACHE_FILE)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump({"access_token": access_token, "expires_at": expires_at}, f)


def get_access_token() -> str:
    """
    获取微信 access_token，带缓存（有效期2小时）。
    环境变量：WECHAT_APPID, WECHAT_APPSECRET
    """
    appid = os.getenv("WECHAT_APPID")
    appsecret = os.getenv("WECHAT_APPSECRET")
    if not appid or not appsecret:
        raise ValueError("未配置 WECHAT_APPID / WECHAT_APPSECRET 环境变量")

    # 检查缓存
    cached_token, expires_at = _load_token()
    if cached_token and time.time() < expires_at:
        return cached_token

    # 重新获取
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={appsecret}"
    resp = requests.get(url, timeout=10)
    data = resp.json()

    if "access_token" not in data:
        raise Exception(f"获取 access_token 失败: {data}")

    token = data["access_token"]
    expires_in = data.get("expires_in", 7200)
    _save_token(token, expires_in)
    return token


def upload_thumb_media(access_token: str, image_path: str) -> str:
    """
    上传封面图片永久素材，返回 media_id。
    微信草稿需要 thumb_media_id。
    """
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    with open(image_path, "rb") as f:
        files = {"media": (os.path.basename(image_path), f, "image/png")}
        resp = requests.post(url, files=files, timeout=30)
    data = resp.json()
    if "media_id" not in data:
        raise Exception(f"上传封面图失败: {data}")
    return data["media_id"]


def create_draft(access_token: str, title: str, author: str, markdown_content: str, thumb_media_id: str = None) -> dict:
    """
    将 Markdown 报告写入微信草稿箱。

    参数：
    - access_token: 微信 access_token
    - title: 文章标题
    - author: 作者
    - markdown_content: Markdown 格式的报告正文
    - thumb_media_id: 封面图 media_id（可选）

    返回：微信 API 响应 dict
    """
    # 1. Markdown → HTML
    content_html = markdown_to_wechat_html(markdown_content)

    # 2. 构造文章结构
    articles = [{
        "title": title,
        "author": author,
        "digest": content_html[:120].replace("<", "&lt;").replace(">", "&gt;"),
        "content": content_html,
        "content_source_url": "",
        "thumb_media_id": thumb_media_id or "",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }]

    payload = {"articles": articles}

    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    resp = requests.post(url, json=payload, timeout=15)
    result = resp.json()

    if result.get("errcode", 0) != 0:
        raise Exception(f"创建草稿失败: {result}")

    return result


def send_to_draft(title: str, author: str, markdown_content: str, cover_image_path: str = None) -> dict:
    """
    完整流程：获取 token → 上传封面图（如有）→ 创建草稿。
    返回创建结果。
    """
    token = get_access_token()

    thumb_media_id = None
    if cover_image_path and os.path.exists(cover_image_path):
        thumb_media_id = upload_thumb_media(token, cover_image_path)

    result = create_draft(token, title, author, markdown_content, thumb_media_id)
    return result


if __name__ == "__main__":
    # 测试用，仅验证 token 获取
    try:
        token = get_access_token()
        print(f"Token 获取成功: {token[:20]}...")
    except Exception as e:
        print(f"Token 获取失败（检查 WECHAT_APPID/APPSECRET）: {e}")
