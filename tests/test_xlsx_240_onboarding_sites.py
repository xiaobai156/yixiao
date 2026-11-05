from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def test_xlsx_240_sites_are_formal_existing_bottom_sites() -> None:
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8-sig"))
    selected = {site["name"]: site for site in sites if site["name"] in EXPECTED}

    # 这批站后来被封存：允许从配置移出，但必须能在封存档案里找到，
    # 否则就是「站点凭空消失」，仍应报错。
    archive = json.loads((ROOT / "archived_sites.json").read_text(encoding="utf-8-sig"))
    archived = {item.get("name") for item in archive["sites"] if isinstance(item, dict)}
    missing = set(EXPECTED) - set(selected)
    assert missing <= archived, f"期望站点既不在配置也不在封存档案：{sorted(missing - archived)}"
    assert selected, "在册的期望站点为空"
    assert all(site["pick"] == "bottom" for site in selected.values())
    assert all(site["section"] == "已有站点" for site in selected.values())
    assert all(site["parser_id"] == "regex.86a7042b2c5a" for site in selected.values())
    if "三十六计" in selected:
        assert selected["三十六计"]["source_policy"] == "api_then_http"
        assert selected["三十六计"]["api_url"].endswith(
            "/api/proxy/manager-articles/6a1cf5ca0b8d229707caac4c"
        )
