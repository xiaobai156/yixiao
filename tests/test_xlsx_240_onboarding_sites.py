from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUCCESS = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳\240期-肖.txt")
FAILURE = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败\240期-肖-失败.txt")
EXPECTED = {
    "军师彩报": "鸡",
    "天长日久": "鼠",
    "未曾忘你": "羊",
    "精品福星": "猴",
    "绝杀一合": "鼠",
    "三十六计": "虎",
    "深藏若虚": "鼠",
    "凛冬沐雪": "猪",
    "东彩破庄": "羊",
    "福禄双全": "兔",
}
SPECIAL = {"绝杀一合", "三十六计", "深藏若虚", "凛冬沐雪", "东彩破庄", "福禄双全"}


def test_xlsx_240_sites_are_formal_existing_bottom_sites() -> None:
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8-sig"))
    selected = {site["name"]: site for site in sites if site["name"] in EXPECTED}

    assert set(selected) == set(EXPECTED)
    assert all(site["pick"] == "bottom" for site in selected.values())
    assert all(site["section"] == "已有站点" for site in selected.values())
    assert all(site["parser_id"] == "regex.86a7042b2c5a" for site in selected.values())
    assert selected["三十六计"]["source_policy"] == "api_then_http"
    assert selected["三十六计"]["api_url"].endswith(
        "/api/proxy/manager-articles/6a1cf5ca0b8d229707caac4c"
    )


def test_xlsx_240_sites_have_complete_cache_and_authorized_exceptions() -> None:
    cache = json.loads((ROOT / "recent_10_cache.json").read_text(encoding="utf-8-sig"))
    selected = {site["name"]: site for site in cache["sites"] if site["name"] in EXPECTED}

    assert set(selected) == set(EXPECTED)
    for name, site in selected.items():
        assert site["section"] == "已有站点"
        assert [record["period"] for record in site["records"]] == list(range(240, 230, -1))
        assert site["records"][0]["zodiac"] == EXPECTED[name]
        if name in SPECIAL:
            assert site["onboarding_exception"] == {
                "target_period": 240,
                "exception": "用户批准连续3至5期疑似重复特例",
                "validated_periods": list(range(240, 230, -1)),
            }


def test_xlsx_240_sites_are_merged_into_existing_success_only() -> None:
    success = SUCCESS.read_text(encoding="utf-8")
    failure = FAILURE.read_text(encoding="utf-8")

    for name, zodiac in EXPECTED.items():
        assert f"{zodiac} {name}" in success
        assert name not in failure
