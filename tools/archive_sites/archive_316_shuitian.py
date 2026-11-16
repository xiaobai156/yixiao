"""把 水天一色 从 sites.json / recent_10_cache.json 迁到 archived_sites.json。

用户 2026-11-12 明确要求「水天一色 封存」。该站 https://0130190827.657954.xyz 与
解报宝彩/荒野孤狼 同一批源站，requests / curl / Playwright 三路都是
TLSV1_UNRECOGNIZED_NAME（证书 SNI 不匹配），无法取源，按用户指令封存。

封存后不抓取、不写正式 TXT、不更新缓存；同时把 316 期已有失败清单里的条目清掉
（用项目自带 _failure_rows/_format_failure_rows 重排，避免统计块残留旧计数）。
写入走同目录临时文件 + os.replace 原子替换，前置条件不满足则不执行。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from zodiac_v2 import output  # noqa: E402
from zodiac_v2.storage import atomic_batch_write  # noqa: E402

FAIL_DIR = ROOT.parent / "七类数据统一归纳失败"
NAME = "水天一色"
REASON = "用户明确要求封存，不再抓取（源站 https TLSV1_UNRECOGNIZED_NAME 无法取源）"
FAILURE_FILE = FAIL_DIR / "316期-肖-失败.txt"


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
        print(f"前置条件失败：{NAME} sites={len(active)} cache={len(cached)}", file=sys.stderr)
        return 2
    if any(s.get("name") == NAME for s in archive["sites"]):
        print(f"前置条件失败：档案中已有 {NAME}", file=sys.stderr)
        return 2

    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    site_entry = dict(active[0])
    site_entry["archived_at"] = stamp
    site_entry["archive_reason"] = REASON
    cache_entry = json.loads(json.dumps(cached[0], ensure_ascii=False))

    dump_atomic(archive_path, {
        "sites": archive["sites"] + [site_entry],
        "cache_entries": archive["cache_entries"] + [cache_entry],
    })
    dump_atomic(sites_path, [s for s in sites if s.get("name") != NAME])
    dump_atomic(cache_path, {**cache, "sites": [s for s in cache["sites"] if s.get("name") != NAME]})

    removed = 0
    deleted = False
    if FAILURE_FILE.exists():
        text = output._read_output_text(FAILURE_FILE)
        rows = output._failure_rows(text)
        kept = [row for row in rows if output._failure_name_key(row) != NAME]
        removed = len(rows) - len(kept)
        if removed:
            if kept:
                new_text = output._format_failure_rows(kept)
                atomic_batch_write({FAILURE_FILE: new_text.encode("utf-8") if new_text is not None else None})
            else:
                atomic_batch_write({FAILURE_FILE: None})
                deleted = True

    cache_after = len(cache["sites"]) - 1

    print(json.dumps({
        "archived_at": stamp,
        "sites_after": len(sites) - 1,
        "cache_after": cache_after,
        "archive_sites": len(archive["sites"]) + 1,
        "failure_rows_removed": removed,
        "failure_file_deleted": deleted,
        "url": site_entry.get("url"),
        "parser_id": site_entry.get("parser_id"),
        "last_records": [f"{r['period']}:{r['zodiac']}" for r in cache_entry.get("records", [])][:3],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
