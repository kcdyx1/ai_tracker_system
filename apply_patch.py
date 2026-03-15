import re
from pathlib import Path

def patch_feishu_webhook():
    fpath = Path("reporter.py")
    content = fpath.read_text(encoding="utf-8")

    # 匹配旧的 send_feishu_webhook 函数
    old_func_pattern = r'def send_feishu_webhook\(markdown_content: str, webhook_url: str\) -> bool:.*?return False'

    # 全新的多模块解析推送逻辑
    new_func = '''def send_feishu_webhook(markdown_content: str, webhook_url: str) -> bool:
    """
    发送飞书 Webhook 推送 (精美排版版)
    """
    import requests
    try:
        elements = []
        current_text = []
        
        # 逐行解析 Markdown，转化为飞书原生卡片组件
        for line in markdown_content.split('\\n'):
            line_stripped = line.strip()
            
            if line_stripped.startswith('# '):
                # 一级标题：作为开篇引言
                current_text.append(f"**🔥 {line_stripped[2:].strip()}**\\n")
                
            elif line_stripped.startswith('## '):
                # 二级标题：切断当前文本块，插入原生分割线，并作为新区块的 Header
                if current_text and any(t.strip() for t in current_text):
                    elements.append({"tag": "markdown", "content": "\\n".join(current_text).strip()})
                    current_text = []
                    
                elements.append({"tag": "hr"})
                elements.append({"tag": "markdown", "content": f"**📌 {line_stripped[3:].strip()}**"})
                
            elif line_stripped.startswith('### '):
                # 三级标题：转换为带小蓝点的加粗文本
                current_text.append(f"\\n**🔹 {line_stripped[4:].strip()}**")
                
            elif line_stripped.startswith('#### '):
                current_text.append(f"**{line_stripped[5:].strip()}**")
                
            elif line_stripped == '---':
                # 忽略原生的 Markdown 分割线，因为我们用了飞书原生 hr
                pass
                
            else:
                current_text.append(line)
        
        # 收尾最后一个文本块
        if current_text and any(t.strip() for t in current_text):
            elements.append({"tag": "markdown", "content": "\\n".join(current_text).strip()})

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True  # 开启宽屏模式，更适合阅读长报告
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "📡 AI 产业情报雷达"
                    },
                    "template": "blue"
                },
                # 飞书限制 elements 最多 50 个，截断保护
                "elements": elements[:50]
            }
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print("✅ 飞书精美卡片推送成功")
            return True
        else:
            print(f"❌ 飞书推送失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 飞书推送异常: {e}")
        return False'''

    if re.search(old_func_pattern, content, flags=re.DOTALL):
        new_content = re.sub(old_func_pattern, new_func, content, flags=re.DOTALL)
        fpath.write_text(new_content, encoding="utf-8")
        print("✅ reporter.py 飞书推送 UI 美化升级完成！")
    else:
        print("⚠️ 未找到匹配的旧函数，请检查 reporter.py。")

if __name__ == '__main__':
    patch_feishu_webhook()