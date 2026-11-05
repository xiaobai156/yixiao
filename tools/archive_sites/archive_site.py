"""把 高手网论坛 从 sites.json / recent_10_cache.json 迁到 archived_sites.json。

用户明确要求封存；封存后不抓取、不写正式 TXT、不更新缓存。
写入走同目录临时文件 + os.replace 原子替换，且仅在三个文件前置条件全部满足时执行。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "高手网论坛"
REASON = "用户明确要求封存，不再抓取"


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
    in_archive = [s for s in archive["sites"] if s.get("name") == NAME]

    if len(active) != 1:
        print(f"前置条件失败：sites.json 中 {NAME} 条数={len(active)}", file=sys.stderr)
        return 2
    if len(cached) != 1:
        print(f"前置条件失败：recent_10_cache.json 中 {NAME} 条数={len(cached)}", file=sys.stderr)
        return 2
    if in_archive:
        print(f"前置条件失败：archived_sites.json 已有 {NAME}", file=sys.stderr)
        return 2

    site_entry = dict(active[0])
    site_entry["archived_at"] = datetime.now().astimezone().replace(microsecond=0).isoformat()
    site_entry["archive_reason"] = REASON

    cache_dump = json.loads(json.dumps(cached[0], ensure_ascii=False))

    archives_sites = [s for s in archive["sites"] if s.get("name") != NAME] + [site_entry]
    archive_new = {
        "sites": archives_sites,
        "cache_entries": [c for c in archive["cache_entries"] if c.get("name") != NAME] + [cache_dump],
    }
    sites_new = [s for s in sites if s.get("name") != NAME]
    cache_new = {**cache, "sites": [s for s in cache["sites"] if s.get("name") != NAME]}

    dump_atomic(archive_path, archive_new)
    dump_atomic(sites_path, sites_new)
    dump_atomic(cache_path, cache_new)

    print(json.dumps({
        "archived_at": site_entry["archived_at"],
        "sites_before": len(sites), "sites_after": len(sites_new),
        "cache_before": len(cache["sites"]), "cache_after": len(cache_new["sites"]),
        "archive_sites": len(archive_new["sites"]), "archive_cache": len(archive_new["cache_entries"]),
        "cache_records": [f"{r['period']}:{r['zodiac']}" for r in cache_dump.get("records", [])][:3],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
