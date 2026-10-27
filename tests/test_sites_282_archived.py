from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAMES = {"人间烟火", "满堂规律", "福星高照"}


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_three_sites_282_are_only_in_archive() -> None:
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
        assert entry["archived_at"] == "2026-10-09"
        assert entry["archive_reason"].startswith("用户明确要求封存，不再抓取")
        assert cache_entries[name]["archive_reason"] == entry["archive_reason"]
        assert cache_entries[name]["url"] == entry["url"]
        assert cache_entries[name]["records"]
