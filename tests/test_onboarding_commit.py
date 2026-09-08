from __future__ import annotations

import json

import pytest

from zodiac_v2.cache import (
    _CacheWriteData,
    append_onboarding_records,
    cache_records,
    write_recent_cache_backfill,
)
from zodiac_v2.config import ConfigError, append_site_configs, load_sites
from zodiac_v2.contracts import CacheRecord, Direction, SiteConfig, SiteSection, WritePermit


def _site() -> SiteConfig:
    return SiteConfig(
        "批量站点",
        "https://4.48kk49.com:1888/Article/ar_content/id/999/tid/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        "special.ar_content_period_article",
        "http_documents",
        article_keyword="批量站点",
    )


def _record(period: int, zodiac: str) -> CacheRecord:
    site = _site()
    return CacheRecord(
        site.name,
        site.url,
        site.direction,
        site.section,
        period,
        zodiac,
        f"html:{site.url}",
        site.url,
        f"{period:064x}",
        "999",
    )


def test_append_site_configs_writes_existing_section_atomically(tmp_path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "已有",
                    "pick": "top",
                    "url": "https://example.com/1",
                    "section": "已有站点",
                    "parser_id": "special.ar_content_period_article",
                    "source_policy": "http_documents",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    append_site_configs(path, (_site(),), permit=WritePermit.formal_single(225))

    loaded = load_sites(
        path,
        parser_ids={"special.ar_content_period_article"},
        source_policies={"http_documents"},
    )
    assert loaded[-1] == _site()


def test_append_site_configs_rejects_same_topic_with_cosmetic_url_difference(tmp_path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "已有",
                    "pick": "top",
                    "url": "https://4.48kk49.com:1888/Article/ar_content/id/999/tid/1.html?old=1",
                    "section": "已有站点",
                    "parser_id": "special.ar_content_period_article",
                    "source_policy": "http_documents",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="URL/topic 重复"):
        append_site_configs(path, (_site(),), permit=WritePermit.formal_single(225))


def test_append_onboarding_records_signs_common_history(tmp_path) -> None:
    path = tmp_path / "recent_10_cache.json"
    data = _CacheWriteData(
        {"window_back_periods": 10, "latest_period": 225, "sites": [], "quarantined_sites": []}
    )
    records = (_record(225, "兔"), _record(224, "牛"))
    identity = _site().identity
    signed = append_onboarding_records(
        data,
        records,
        current_period=225,
        permit=WritePermit.formal_single(225),
        metadata={identity: {"target_period": 225, "missing_periods": [223]}},
    )

    write_recent_cache_backfill(path, signed, WritePermit.formal_single(225))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["sites"][0]["onboarding_exception"]["missing_periods"] == [223]
    assert [(record.period, record.zodiac) for record in cache_records(saved)] == [
        (225, "兔"),
        (224, "牛"),
    ]
