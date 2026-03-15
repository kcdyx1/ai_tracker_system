import os
from pathlib import Path

def patch_files():
    # 1. 创建 .env
    env_file = Path(".env")
    if not env_file.exists():
        env_file.write_text("MINIMAX_API_KEY=your_api_key_here\nFEISHU_WEBHOOK_URL=your_webhook_here\n")
        print("✅ .env 文件已创建")

    # 2. 更新 requirements.txt
    req_file = Path("requirements.txt")
    if req_file.exists():
        req_content = req_file.read_text()
        if "python-dotenv" not in req_content:
            req_file.write_text(req_content.strip() + "\npython-dotenv\n")
            print("✅ python-dotenv 已加入 requirements.txt")

    # 3. 注入 dotenv
    target_files = ["server.py", "extractor.py", "reporter.py", "rag.py", "app.py"]
    inject_code = "from dotenv import load_dotenv\nload_dotenv()\n"

    for fname in target_files:
        fpath = Path(fname)
        if fpath.exists():
            content = fpath.read_text()
            if "load_dotenv" not in content:
                # 寻找合适的注入点
                if "import os" in content:
                    content = content.replace("import os", "import os\n" + inject_code, 1)
                elif "import streamlit as st" in content:
                    content = content.replace("import streamlit as st", "import streamlit as st\n" + inject_code, 1)
                else:
                    content = inject_code + "\n" + content
                fpath.write_text(content)
                print(f"✅ 成功为 {fname} 注入环境变量加载代码")

    # 4. 注入缓存装饰器到 app.py
    app_file = Path("app.py")
    if app_file.exists():
        app_content = app_file.read_text()
        funcs_to_cache = [
            "def get_summary_stats():",
            "def get_all_entities():",
            "def get_latest_events(limit: int = 20):"
        ]
        for func in funcs_to_cache:
            target = f"@st.cache_data(ttl=60)\n{func}"
            if func in app_content and target not in app_content:
                app_content = app_content.replace(func, target)
        app_file.write_text(app_content)
        print("✅ 成功为 app.py 添加缓存装饰器")

if __name__ == '__main__':
    patch_files()
