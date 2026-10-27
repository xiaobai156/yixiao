from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAMES = {
    "决杀一肖", "一尘不染", "多重性格", "发财之道", "白云孤飞", "龙腾虎跃",
    "艳绝千秋", "山川落笔", "百依百顺", "九鹭非香", "怒火中烧",
}


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_eleven_duplicate_sites_are_only_in_archive() -> None:
    active = _read("sites.json")
    cache = _read("recent_10_cache.json")["sites"]
    archive = _read("archived_sites.json")

    assert not NAMES & {item["name"] for item in active}
    assert not NAMES & {item["name"] for item in cache}

    site_entries = {item["name"]: item for item in archive["sites"] if item["name"] in NAMES}
    cache_entries = {item["name"]: item for item in archive["cache_entries"] if item["name"] in NAMES}
    assert set(site_entries) == NAMES
    assert set(cache_entries) == NAMES

    for name in NAMES:
        entry = site_entries[name]
        assert entry["archived_at"] == "2026-10-08"
        assert "封存" in entry["archive_reason"]
        assert cache_entries[name]["archive_reason"] == entry["archive_reason"]
        assert cache_entries[name]["url"] == entry["url"]
        assert len(cache_entries[name]["records"]) == 10
