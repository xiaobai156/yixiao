from __future__ import annotations

import json

import pytest

from zodiac_v2.cache import (
    _CacheWriteData,
    backfill_recent_cache_records,
    replace_site_direction,
    write_recent_cache_backfill,
)
from zodiac_v2.contracts import CacheRecord, Direction, SiteSection, WritePermit


def test_backfill_cache_write_keeps_newer_global_period(tmp_path) -> None:
    path = tmp_path / "recent_10_cache.json"
    data = _CacheWriteData(
        {
            "window_back_periods": 10,
            "latest_period": 225,
            "sites": [],
            "quarantined_sites": [],
        }
    )

    write_recent_cache_backfill(path, data, WritePermit.formal_single(224))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["latest_period"] == 225
    assert saved["sites"] == []


def test_replace_site_direction_preserves_history_and_identity_fields() -> None:
    data = {
        "window_back_periods": 10,
        "latest_period": 228,
        "sites": [
            {
                "name": "福禄寿喜财",
                "pick": "top",
                "url": "https://example.test/#/users/154933",
                "section": "新增的站点",
                "error": "旧方向失败",
                "records": [{"period": 227, "zodiac": "马"}],
                "fingerprint": "马",
                "record_provenance": {
                    "227": {
                        "validation_status": "validated",
                        "source_id": "html:test",
                        "source_url": "https://example.test/#/users/154933",
                        "evidence_sha256": "a" * 64,
                    }
                },
            }
        ],
        "quarantined_sites": [],
    }

    updated = replace_site_direction(
        data,
        name="福禄寿喜财",
        url="https://example.test/#/users/154933",
        section=SiteSection.NEW,
        direction=Direction.BOTTOM,
        permit=WritePermit.formal_single(228),
    )

    entry = updated["sites"][0]
    assert entry["pick"] == "bottom"
    assert entry["records"] == [{"period": 227, "zodiac": "马"}]
    assert entry["record_provenance"]["227"]["evidence_sha256"] == "a" * 64
    assert entry["error"] == "旧方向失败"


def test_backfill_old_period_preserves_newer_global_period() -> None:
    data = {
        "window_back_periods": 10,
        "latest_period": 241,
        "sites": [
            {
                "name": "回填站",
                "pick": "top",
                "url": "https://example.test/topic/1.html",
                "section": "已有站点",
                "error": "",
                "records": [{"period": 241, "zodiac": "虎"}],
                "fingerprint": "虎",
                "record_provenance": {
                    "241": {
                        "validation_status": "validated",
                        "source_id": "html:test",
                        "source_url": "https://example.test/topic/1.html",
                        "evidence_sha256": "b" * 64,
                    }
                },
                "onboarding_exception": {
                    "validated_periods": [241],
                    "missing_periods": [240],
                },
            }
        ],
        "quarantined_sites": [],
    }
    record = CacheRecord(
        "回填站",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        240,
        "蛇",
        "html:test",
        "https://example.test/topic/1.html",
        "a" * 64,
        "1",
    )

    updated = backfill_recent_cache_records(
        data,
        (record,),
        permit=WritePermit.formal_single(240),
    )

    assert updated["latest_period"] == 241
    assert updated["sites"][0]["records"] == [
        {"period": 241, "zodiac": "虎"},
        {"period": 240, "zodiac": "蛇"},
    ]
    assert updated["sites"][0]["record_provenance"]["240"]["record_id"] == "1"
    assert updated["sites"][0]["onboarding_exception"] == {
        "validated_periods": [241, 240],
        "missing_periods": [],
    }


def test_backfill_rejects_conflicting_existing_period() -> None:
    data = {
        "window_back_periods": 10,
        "latest_period": 241,
        "sites": [
            {
                "name": "回填站",
                "pick": "top",
                "url": "https://example.test/topic/1.html",
                "section": "已有站点",
                "error": "",
                "records": [{"period": 240, "zodiac": "虎"}],
                "fingerprint": "虎",
                "record_provenance": {
                    "240": {
                        "validation_status": "validated",
                        "source_id": "html:test",
                        "source_url": "https://example.test/topic/1.html",
                        "evidence_sha256": "b" * 64,
                    }
                },
            }
        ],
        "quarantined_sites": [],
    }
    record = CacheRecord(
        "回填站",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        240,
        "蛇",
        "html:test",
        "https://example.test/topic/1.html",
        "a" * 64,
        "1",
    )

    with pytest.raises(ValueError, match="缓存同期冲突"):
        backfill_recent_cache_records(
            data,
            (record,),
            permit=WritePermit.formal_single(240),
        )
