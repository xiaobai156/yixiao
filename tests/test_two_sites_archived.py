from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAMES = {"投怀送抱新", "残阳半夏"}


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_two_sites_are_only_in_archive() -> None:
    active = _read("sites.json")
    cache = _read("recent_10_cache.json")["sites"]
    archive = _read("archived_sites.json")

    assert not NAMES & {item["name"] for item in active}
    assert not NAMES & {item["name"] for item in cache}
    assert {item["name"] for item in archive["sites"] if item["name"] in NAMES} == NAMES
    assert {
        item["name"] for item in archive["cache_entries"] if item["name"] in NAMES
    } == NAMES
