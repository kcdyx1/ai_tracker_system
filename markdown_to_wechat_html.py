# -*- coding: utf-8 -*-
"""
Markdown → 微信公众号富文本 HTML 转换器
处理微信公众号支持的 HTML 子集（不支持复杂 Markdown）
"""

import re


def markdown_to_wechat_html(markdown_text: str) -> str:
    """
    将 Markdown 转换为微信公众号支持的 HTML。
    微信公众号支持的标签：p, br, strong, em, a, img, blockquote, ul, ol, li, h1-h6, table, thead, tbody, tr, th, td
    不支持：class, id, style（内联除外）
    """
    html = markdown_text

    # 1. 处理标题（## 标题 → <h3>标题</h3>）
    for level in range(3, 0, -1):
        hashes = "#" * level
        html = re.sub(rf'\n{hashes}\s+(.+?)\n', lambda m: f'\n<h{level+2}>{m.group(1)}</h{level+2}>\n', html)

    # 2. 处理加粗 **text** → <strong>text</strong>
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

    # 3. 处理斜体 *text* → <em>text</em>（注意不要误匹配 **）
    html = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', html)

    # 4. 处理链接 [text](url) → <a href="url">text</a>
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)

    # 5. 处理引用块 > text → <blockquote><p>text</p></blockquote>
    html = re.sub(r'^&gt;\s*(.+?)$', r'<blockquote><p>\1</p></blockquote>', html, flags=re.MULTILINE)

    # 6. 处理图片 ![alt](url) → <p><img src="url" alt="alt"/></p>
    def img_replace(m):
        alt = m.group(1) or ""
        url = m.group(2)
        return f'<p><img src="{url}" alt="{alt}"/></p>'
    html = re.sub(r'!\[(.*?)\]\((.+?)\)', img_replace, html)

    # 7. 处理分割线 --- → <hr/>
    html = re.sub(r'^---$', '<hr/>', html, flags=re.MULTILINE)

    # 8. 处理无序列表 - item → <p>• item</p>（微信不支持 ul 渲染优化为段落）
    # 先把连续的列表项合并成 ul 结构
    list_pattern = re.compile(r'^-\s+(.+?)$', re.MULTILINE)
    html = list_pattern.sub(r'<li>\1</li>', html)

    # 合并连续的 <li> 为 <ul>
    html = re.sub(r'(<li>.*?</li>\n?)+', lambda m: f'<ul>{m.group(0)}</ul>', html)

    # 9. 处理段落（双换行分割）
    paragraphs = re.split(r'\n{2,}', html)
    result_paras = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 如果已经是块级标签则保持
        if re.match(r'^(<h[1-6]|<blockquote|<ul|<ol|<li|<p|<img|<hr)', para):
            result_paras.append(para)
        else:
            # 普通段落加 p 标签，多重换行转为 br
            para = para.replace('\n', '<br/>')
            result_paras.append(f'<p>{para}</p>')

    return '\n'.join(result_paras)


def wrap_wechat_article(title: str, author: str, content_html: str) -> dict:
    """
    构造微信草稿 API 的 HTML 内容。
    返回 dict，包含 thumb_media_id（需先上传封面图）等字段。
    """
    html_body = f"""
<h1>{title}</h1>
<p><strong>作者：{author}</strong></p>
<hr/>
{content_html}
"""
    return {
        "title": title,
        "author": author,
        "content": html_body,
        "digest": content_html[:120],
        "content_source_url": "",
    }


if __name__ == "__main__":
    test_md = """**📌 今日战略动向**

这是一段测试内容。

> 这是引用文字

- 列表项一
- 列表项二
"""
    print(markdown_to_wechat_html(test_md))
