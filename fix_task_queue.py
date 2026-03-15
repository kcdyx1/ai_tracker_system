import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ai_tracker.db"

def fix():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE task_queue ADD COLUMN error_message TEXT")
        conn.commit()
        print("✅ 成功添加 error_message 字段")
    except Exception as e:
        print(f"⚠️ 字段可能已存在或出错: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix()
