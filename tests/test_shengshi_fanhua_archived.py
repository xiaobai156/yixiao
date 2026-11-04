from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "盛世繁华"


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_shengshi_fanhua_is_only_in_archive() -> None:
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

    assert entry["url"] == "https://z0gcdiww42.669332.shop/bbs/topic.php?id=2072"
    assert entry["pick"] == "bottom"
    assert entry["parser_id"] == "regex.1139adaae11e"
    assert entry["source_policy"] == "http_documents"
    assert entry["archive_reason"] == "用户明确要求封存，不再抓取"
    assert entry["archived_at"].endswith("+08:00")
