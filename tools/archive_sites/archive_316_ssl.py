"""把 解报宝彩 / 荒野孤狼 从 sites.json / recent_10_cache.json 迁到 archived_sites.json。

用户 2026-11-12 明确要求「解报宝彩 荒野孤狼 封存」；两站 https 均为
TLSV1_UNRECOGNIZED_NAME（requests、curl、Playwright 三种方式都握手失败），
313 期时 1214.775486.xyz 还正常，属源站证书/SNI 失效，按用户指令封存。

封存后不抓取、不写正式 TXT、不更新缓存；同时把 316 期失败清单里的两站条目清掉
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

SUCCESS_DIR = ROOT.parent / "七类数据统一归纳"
FAIL_DIR = ROOT.parent / "七类数据统一归纳失败"
NAMES = ("解报宝彩", "荒野孤狼")
REASON = "用户明确要求封存，不再抓取（源站 https TLSV1_UNRECOGNIZED_NAME 无法取源）"
FAILURE_FILE = FAIL_DIR / "316期-肖-失败-新增.txt"


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

    for name in NAMES:
        active = [s for s in sites if s.get("name") == name]
        cached = [s for s in cache["sites"] if s.get("name") == name]
        if len(active) != 1 or len(cached) != 1:
            print(f"前置条件失败：{name} sites={len(active)} cache={len(cached)}", file=sys.stderr)
            return 2
        if any(s.get("name") == name for s in archive["sites"]):
            print(f"前置条件失败：档案中已有 {name}", file=sys.stderr)
            return 2

    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    site_entries = []
    cache_entries = []
    for name in NAMES:
        entry = dict(next(s for s in sites if s.get("name") == name))
        entry["archived_at"] = stamp
        entry["archive_reason"] = REASON
        site_entries.append(entry)
        cache_entries.append(json.loads(json.dumps(next(s for s in cache["sites"] if s.get("name") == name), ensure_ascii=False)))

    dump_atomic(archive_path, {
        "sites": archive["sites"] + site_entries,
        "cache_entries": archive["cache_entries"] + cache_entries,
    })
    dump_atomic(sites_path, [s for s in sites if s.get("name") not in NAMES])
    dump_atomic(cache_path, {**cache, "sites": [s for s in cache["sites"] if s.get("name") not in NAMES]})

    removed = 0
    payload = None
    if FAILURE_FILE.exists():
        text = output._read_output_text(FAILURE_FILE)
        rows = output._failure_rows(text)
        kept = [row for row in rows if output._failure_name_key(row) not in NAMES]
        removed = len(rows) - len(kept)
        if removed:
            new_text = output._format_failure_rows(kept)
            payload = new_text.encode("utf-8") if new_text is not None else None
            atomic_batch_write({FAILURE_FILE: payload})

    print(json.dumps({
        "archived_at": stamp,
        "sites_after": len(sites) - len(NAMES),
        "cache_after": len(cache["sites"]) - len(NAMES),
        "archive_sites": len(archive["sites"]) + len(NAMES),
        "failure_rows_removed": removed,
        "failure_file_left": None if payload is None else len(payload),
        "last_records": {
            entry["name"]: [f"{r['period']}:{r['zodiac']}" for r in entry.get("records", [])][:3]
            for entry in cache_entries
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
