#!/usr/bin/env python3
"""Paper/Repo collector runner - called by systemd timer"""
import sys
sys.path.insert(0, "/home/kangchen/.openclaw/workspace/ai_tracker_system")
from collector import run_collection

result = run_collection(["api"])
total = result.get("stats", {}).get("total_items", 0)
print("Collected {} items from API sources".format(total))
