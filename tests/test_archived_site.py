from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_NAME = "幸运尘客"
SITE_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/#/users/218320"


def _read_json(name: str) -> object:
    return json.loads((PROJECT_ROOT / name).read_text(encoding="utf-8"))


def test_lucky_dust_traveler_is_archived_and_absent_from_active_sources() -> None:
    active_sites = _read_json("sites.json")
    active_cache = _read_json("recent_10_cache.json")
    archive = _read_json("archived_sites.json")

    assert isinstance(active_sites, list)
    assert not any(item.get("name") == SITE_NAME for item in active_sites if isinstance(item, dict))

    assert isinstance(active_cache, dict)
    active_cache_sites = active_cache.get("sites")
    assert isinstance(active_cache_sites, list)
    assert not any(item.get("name") == SITE_NAME for item in active_cache_sites if isinstance(item, dict))

    assert isinstance(archive, dict)
    archived_sites = archive.get("sites")
    archived_cache = archive.get("cache_entries")
    assert isinstance(archived_sites, list)
    assert isinstance(archived_cache, list)
    assert [item for item in archived_sites if item.get("name") == SITE_NAME] == [
        {
            "name": SITE_NAME,
            "pick": "top",
            "url": SITE_URL,
            "parser_id": "special.user_forum_post",
            "source_policy": "api_then_http",
            "api_url": "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/api/v1/users/218320/forums?per_page=20",
            "archived_at": "2026-08-15",
            "archive_reason": "用户明确要求封存，不再抓取",
        }
    ]
    assert [item for item in archived_cache if item.get("name") == SITE_NAME] == [
        {
            "name": SITE_NAME,
            "pick": "top",
            "url": SITE_URL,
            "section": "已有站点",
            "error": "用户 218320 的接口未找到指定 226期帖子",
            "records": [],
            "fingerprint": "",
        }
    ]
