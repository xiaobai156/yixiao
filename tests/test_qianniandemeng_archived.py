from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
NAME = "千年的梦"


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_qianniandemeng_is_only_in_archive() -> None:
    active = _read("sites.json")
    cache = _read("recent_10_cache.json")["sites"]
    archive = _read("archived_sites.json")

    assert not any(item.get("name") == NAME for item in active)
    assert not any(item.get("name") == NAME for item in cache)
    assert len([item for item in archive["sites"] if item.get("name") == NAME]) == 1
    assert len([item for item in archive["cache_entries"] if item.get("name") == NAME]) == 1
