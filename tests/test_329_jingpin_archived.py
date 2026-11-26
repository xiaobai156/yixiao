from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "精品福星"
URL = "https://88888020827.885536.xyz/bbs/topic.php?id=19452"


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_site_is_only_in_archive() -> None:
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
    assert entry["url"] == URL
    assert entry["pick"] == "bottom"
    assert entry["parser_id"] == "regex.86a7042b2c5a"
    assert entry["source_policy"] == "http_documents"
    assert entry["section"] == "已有站点"
    assert "封存" in entry["archive_reason"]
    assert entry["archived_at"].endswith("+08:00")

    cache_entry = next(item for item in archive["cache_entries"] if item["name"] == NAME)
    records = [f"{row['period']}:{row['zodiac']}" for row in cache_entry["records"]]
    assert records[:3] == ["328:牛", "327:狗", "326:龙"]


def test_failure_list_no_longer_lists_archived_site() -> None:
    failure_dir = ROOT.parent / "七类数据统一归纳失败"
    for name in ("329期-肖-失败.txt", "329期-肖-失败-新增.txt"):
        path = failure_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert f"{NAME} " not in text
