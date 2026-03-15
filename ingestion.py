#!/usr/bin/env python3
"""
AI Tracker System - 网页抓取清洗模块

使用 Jina AI 的 r.jina.ai 服务获取纯净的 Markdown 内容
"""

import requests
import cloudscraper


# 常见的请求头，防止被拦截
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_clean_markdown(url: str) -> str:
    """
    获取纯净的 Markdown 内容
    
    Args:
        url: 目标网页 URL
        
    Returns:
        纯净的 Markdown 文本，失败返回空字符串
    """
    # 确保 URL 是 https:// 开头
    if url.startswith("http://"):
        url = "https://" + url[7:]
    
    # 方法1：尝试使用 r.jina.ai
    try:
        jina_url = f"https://r.jina.ai/{url}"
        
        response = requests.get(
            jina_url,
            headers=DEFAULT_HEADERS,
            timeout=15
        )
        
        if response.status_code == 200:
            content = response.text
            # 检查是否返回了错误信息
            if "error" in content.lower() or "blocked" in content.lower():
                print(f"  ⚠️ r.jina.ai 返回错误，尝试备用方法")
            else:
                print(f"  ✅ r.jina.ai 抓取成功")
                return content
        else:
            print(f"  ⚠️ r.jina.ai 抓取失败，状态码: {response.status_code}")
                
    except Exception as e:
        print(f"  ⚠️ r.jina.ai 方法失败: {e}")
    
    # 方法2：直接抓取
    return fetch_direct(url)


def fetch_direct(url: str) -> str:
    """
    备用方法：直接抓取网页（使用 cloudscraper 突破反爬）
    """
    print(f"  🔄 尝试 cloudscraper 直接抓取...")
    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
        response = scraper.get(url, timeout=20)
        
        if response.status_code == 200:
            # 尝试提取纯文本
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 移除脚本和样式
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # 获取标题
            title = soup.find('title')
            title_text = title.get_text(strip=True) if title else ""
            
            # 获取正文
            text = soup.get_text(separator='\n', strip=True)
            
            # 清理多余空行
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            cleaned_text = '\n'.join(lines)
            
            result = f"# {title_text}\n\n{cleaned_text}" if title_text else cleaned_text
            
            print(f"  ✅ 直接抓取成功，内容长度: {len(result)}")
            return result[:15000]  # 限制长度
            
        else:
            print(f"  ❌ 直接抓取失败，状态码: {response.status_code}")
            return ""
            
    except Exception as e:
        print(f"  ❌ 备用方法失败: {e}")
        return ""


if __name__ == "__main__":
    # 测试
    test_url = "https://baike.baidu.com/item/ChatGPT"
    print(f"🧪 测试抓取: {test_url}")
    result = fetch_clean_markdown(test_url)
    print(f"📄 获取到 {len(result)} 字符")
    if result:
        print("\n前 500 字符预览:")
        print(result[:500])
