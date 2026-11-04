from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "高手网论坛"


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_gaoshou_wang_luntan_is_only_in_archive() -> None:
    active = _json("sites.json")
    cache = _json("recent_10_cache.json")
    archive = _json("archived_sites.json")

    assert not any(item.get("name") == NAME for item in active)
    assert not any(item.get("name") == NAME for item in cache["sites"])
    assert len([item for item in archive["sites"] if item.get("name") == NAME]) == 1
    assert len([item for item in archive["cache_entries"] if item.get("name") == NAME]) == 1


def test_archived_entry_keeps_identity_and_reason() -> None:
    archive = _json("archived_sites.json")
    entry = next(item for item in archive["sites"] if item["name"] == NAME)

    assert entry["url"] == "https://799689.cc/"
    assert entry["pick"] == "top"
    assert entry["parser_id"] == "special.gaoshou_wang_luntan_kill_zodiac"
    assert entry["source_policy"] == "http_documents"
    assert entry["archive_reason"] == "用户明确要求封存，不再抓取"
    assert entry["archived_at"].endswith("+08:00")

    cached = next(item for item in archive["cache_entries"] if item["name"] == NAME)
    assert cached["records"], "封存时须保存最后一次缓存记录以便追溯"
