from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "水天一色"


def _json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_shuitian_yise_is_only_in_archive() -> None:
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

    assert entry["url"] == "https://0130190827.657954.xyz/bbs/topic.php?id=20197"
    assert entry["pick"] == "bottom"
    assert entry["parser_id"] == "regex.86a7042b2c5a"
    assert entry["source_policy"] == "http_documents"
    assert entry["archive_reason"].startswith("用户明确要求封存")
    assert entry["archived_at"].endswith("+08:00")


def test_failure_lists_no_longer_list_archived_site() -> None:
    fail_dir = ROOT.parent / "七类数据统一归纳失败"
    for name in ("316期-肖-失败.txt", "316期-肖-失败-新增.txt"):
        path = fail_dir / name
        if not path.exists():
            continue
        assert f"{NAME} " not in path.read_text(encoding="utf-8")
