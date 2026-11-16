from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "妮最可爱"
URL = "https://zcphjs.ce83x-ms2rz-orwude.work:12277/#/users/231014"
API_URL = "https://zcphjs.ce83x-ms2rz-orwude.work:12277/api/v1/users/231014/forums?per_page=20"


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
    assert entry["pick"] == "top"
    assert entry["parser_id"] == "special.user_forum_post"
    assert entry["source_policy"] == "api_then_http"
    assert entry["api_url"] == API_URL
    assert entry["section"] == "新增的站点"
    assert entry["archive_reason"].startswith("用户明确要求封存")
    assert entry["archived_at"].endswith("+08:00")

    cache_entry = next(item for item in archive["cache_entries"] if item["name"] == NAME)
    records = [f"{row['period']}:{row['zodiac']}" for row in cache_entry["records"]]
    assert records[:3] == ["317:鼠", "316:鼠", "315:鼠"]


def test_failure_list_no_longer_lists_archived_site() -> None:
    path = ROOT.parent / "七类数据统一归纳失败" / "318期-肖-失败-新增.txt"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    assert f"{NAME} " not in text
