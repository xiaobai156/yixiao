"""检查 JSON 重新序列化是否与原文逐字节一致（避免归档改写引入无关 diff）。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for name in ("sites.json", "archived_sites.json", "recent_10_cache.json"):
    p = ROOT / name
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    out = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    print(name, "roundtrip 一致" if out == raw else "不一致", len(raw), len(out))
