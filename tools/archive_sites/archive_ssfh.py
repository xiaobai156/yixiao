"""把 盛世繁华 从 sites.json / recent_10_cache.json 迁到 archived_sites.json，并清掉失败清单条目。

用户明确要求封存；封存后不抓取、不写正式 TXT、不更新缓存。
写入走同目录临时文件 + os.replace 原子替换，前置条件不满足则不执行。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUCCESS_DIR = ROOT.parent / "七类数据统一归纳"
FAIL_DIR = ROOT.parent / "七类数据统一归纳失败"
NAME = "盛世繁华"
REASON = "用户明确要求封存，不再抓取"
FAILURE_FILE = FAIL_DIR / "308期-肖-失败-新增.txt"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_atomic(path: Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".zodiac-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main() -> int:
    sites_path = ROOT / "sites.json"
    cache_path = ROOT / "recent_10_cache.json"
    archive_path = ROOT / "archived_sites.json"

    sites = load(sites_path)
    cache = load(cache_path)
    archive = load(archive_path)

    active = [s for s in sites if s.get("name") == NAME]
    cached = [s for s in cache["sites"] if s.get("name") == NAME]
    if len(active) != 1 or len(cached) != 1:
        print(f"前置条件失败：sites={len(active)} cache={len(cached)}", file=sys.stderr)
        return 2
    if any(s.get("name") == NAME for s in archive["sites"]):
        print("前置条件失败：档案中已存在", file=sys.stderr)
        return 2

    site_entry = dict(active[0])
    site_entry["archived_at"] = datetime.now().astimezone().replace(microsecond=0).isoformat()
    site_entry["archive_reason"] = REASON
    cache_dump = json.loads(json.dumps(cached[0], ensure_ascii=False))

    dump_atomic(archive_path, {
        "sites": archive["sites"] + [site_entry],
        "cache_entries": archive["cache_entries"] + [cache_dump],
    })
    dump_atomic(sites_path, [s for s in sites if s.get("name") != NAME])
    dump_atomic(cache_path, {**cache, "sites": [s for s in cache["sites"] if s.get("name") != NAME]})

    removed = 0
    if FAILURE_FILE.exists():
        lines = FAILURE_FILE.read_text(encoding="utf-8").splitlines()
        kept = [ln for ln in lines if not ln.startswith(NAME + " ")]
        removed = len(lines) - len(kept)
        if removed:
            rest = [ln for ln in kept if ln.strip()]
            if rest:
                FAILURE_FILE.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8", newline="\n")
            else:
                FAILURE_FILE.unlink()

    print(json.dumps({
        "archived_at": site_entry["archived_at"],
        "sites_after": len(sites) - 1,
        "cache_after": len(cache["sites"]) - 1,
        "archive_sites": len(archive["sites"]) + 1,
        "failure_lines_removed": removed,
        "last_records": [f"{r['period']}:{r['zodiac']}" for r in cache_dump.get("records", [])][:3],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
