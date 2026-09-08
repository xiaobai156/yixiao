from __future__ import annotations

from pathlib import Path

from zodiac_v2.cli import SOURCE_POLICIES
from zodiac_v2.config import load_sites
from zodiac_v2.parsers.dedicated import ANCHOR_ALIASES, DIRECTIONAL_CYCLE_REGEX_SITES
from zodiac_v2.parsers.registry import build_registry

ROOT = Path(__file__).parents[1]

NEW_NAMES = {
    "让他一会", "似水年华", "多彩码王", "富贵当头", "烟花寂凉", "大无间道",
    "黑庄杀星", "宏图运彩", "财聚太子", "人间烟火", "楚楚动人", "七彩使者",
    "福如东海", "品料财富", "奇缘小朵", "燕语莺声", "南柯故人", "福星精品",
}
EXISTING_NAMES = {
    "六合飞船", "桑榆暮景", "秘决公司", "千年的梦", "神算天才", "冰肌莹彻",
    "总裁皇帝", "绿草如茵", "翠色欲滴", "实力超群", "福星高照",
    "大放光彩", "汪洋大海", "华夏九州", "四平八稳", "花好月圆", "一出好戏",
    "真心诚意", "水天一色",
}


def test_formal_batch_238_config_is_complete_and_scoped() -> None:
    registry = build_registry()
    sites = load_sites(
        ROOT / "sites.json",
        parser_ids=registry.parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in NEW_NAMES | EXISTING_NAMES}

    assert set(selected) == NEW_NAMES | EXISTING_NAMES
    assert all(site.direction.value == "bottom" for site in selected.values())
    assert all(site.parser_id == "regex.86a7042b2c5a" for site in selected.values())
    assert {site.name for site in selected.values() if site.section.value == "新增的站点"} == NEW_NAMES
    assert {site.name for site in selected.values() if site.section.value == "已有站点"} == EXISTING_NAMES
    assert NEW_NAMES | EXISTING_NAMES <= DIRECTIONAL_CYCLE_REGEX_SITES
    assert ANCHOR_ALIASES["天长地久"] == "天长日久"
    assert ANCHOR_ALIASES["总裁皇帝"] == "总载皇帝"
