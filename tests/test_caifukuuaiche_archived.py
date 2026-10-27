from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "财富快车"
URL = "https://pegpvuw.e92s8-981z5-icstds.work:17488/"


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_caifukuuaiche_is_only_in_archive() -> None:
    active = _read("sites.json")
    cache = _read("recent_10_cache.json")["sites"]
    archive = _read("archived_sites.json")

    assert not any(item["name"] == NAME for item in active)
    assert not any(item["name"] == NAME for item in cache)

    site_entries = [item for item in archive["sites"] if item["name"] == NAME]
    cache_entries = [item for item in archive["cache_entries"] if item["name"] == NAME]
    assert len(site_entries) == 1
    assert len(cache_entries) == 1

    entry = site_entries[0]
    assert entry["url"] == URL
    assert entry["pick"] == "top"
    assert entry["section"] == "已有站点"
    assert entry["parser_id"] == "family.anchored_section"
    assert entry["source_policy"] == "http_documents"
    assert entry["archived_at"] == "2026-10-15"
    assert "封存" in entry["archive_reason"]
    assert cache_entries[0]["url"] == URL
    assert cache_entries[0]["archive_reason"] == entry["archive_reason"]
    assert any(record["period"] == 287 for record in cache_entries[0]["records"])
    assert len(cache_entries[0]["records"]) == 10
