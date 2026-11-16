"""把 捡料糊口的曾白温 从 sites.json / recent_10_cache.json 迁到 archived_sites.json。

用户 2026-11-16 明确要求「捡料糊口的曾白温 封存」。
该站为用户论坛帖站（special.user_forum_post + api_then_http），
接口 https://zcphjs.ce83x-ms2rz-orwude.work:12277/api/v1/users/176592/forums?per_page=20
最新帖 draw=319（id 16399951，2026-11-14 21:37:19），320 期尚未发布，
缓存 error 即「用户 176592 的接口未找到指定 320期帖子」。

封存后不抓取、不写正式 TXT、不更新缓存；同时清掉失败清单里该站条目
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
NAME = "捡料糊口的曾白温"
REASON = "用户明确要求封存，不再抓取（320 期未发布，接口最新仍为 319 期）"
FAILURE_FILES = [
    FAIL_DIR / "320期-肖-失败.txt",
    FAIL_DIR / "320期-肖-失败-新增.txt",
]


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
    deleted = []
    for failure_file in FAILURE_FILES:
        if not failure_file.exists():
            continue
        text = output._read_output_text(failure_file)
        rows = output._failure_rows(text)
        kept = [row for row in rows if output._failure_name_key(row) != NAME]
        hit = len(rows) - len(kept)
        if not hit:
            continue
        removed += hit
        new_text = output._format_failure_rows(kept)
        atomic_batch_write({failure_file: new_text.encode("utf-8") if new_text is not None else None})
        if new_text is None:
            deleted.append(failure_file.name)

    print(json.dumps({
        "archived_at": stamp,
        "sites_after": len(sites) - 1,
        "cache_after": len(cache["sites"]) - 1,
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
