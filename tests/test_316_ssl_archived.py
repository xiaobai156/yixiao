from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAMES = ("解报宝彩", "荒野孤狼")
EXPECTED = {
    "解报宝彩": ("https://1214.775486.xyz/bbs/topic.php?id=20202", "regex.6ec114aab94b"),
    "荒野孤狼": ("https://1214.775486.xyz/bbs/topic.php?id=20211", "regex.ed33d8f61942"),
}


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_sites_are_only_in_archive() -> None:
    active = _json("sites.json")
    cache = _json("recent_10_cache.json")
    archive = _json("archived_sites.json")

    for name in NAMES:
        assert not any(item.get("name") == name for item in active)
        assert not any(item.get("name") == name for item in cache["sites"])
        assert len([item for item in archive["sites"] if item.get("name") == name]) == 1
        assert len([item for item in archive["cache_entries"] if item.get("name") == name]) == 1


def test_archived_entries_keep_identity_and_reason() -> None:
    archive = _json("archived_sites.json")

    for name in NAMES:
        entry = next(item for item in archive["sites"] if item["name"] == name)
        url, parser_id = EXPECTED[name]
        assert entry["url"] == url
        assert entry["pick"] == "bottom"
        assert entry["parser_id"] == parser_id
        assert entry["source_policy"] == "http_documents"
        assert entry["archive_reason"].startswith("用户明确要求封存")
        assert entry["archived_at"].endswith("+08:00")


def test_failure_list_no_longer_lists_archived_sites() -> None:
    path = ROOT.parent / "七类数据统一归纳失败" / "316期-肖-失败-新增.txt"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    for name in NAMES:
        assert f"{name} " not in text
