# -*- coding: utf-8 -*-
"""四舅黄宾虹黄肖 专属解析器测试：只认「无敌杀码」标签页的「杀一肖」列。"""
from __future__ import annotations

from pathlib import Path

from zodiac_v2.cli import SOURCE_POLICIES
from zodiac_v2.config import load_sites
from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import SijiuHuangbinhongKillZodiacParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.test/"
PARSER_ID = "special.sijiu_huangbinhong_kill_zodiac"


def _headers() -> str:
    return (
        "<tr><td>期数</td><td>杀一肖</td><td>杀半波</td>"
        "<td>杀一尾</td><td>禁一段</td><td>开奖结果</td></tr>"
    )


def _row(period: int, zodiac: str, draw: str = "？00") -> str:
    return f"<tr><td>{period}期</td><td>{zodiac}</td><td>蓝双</td><td>2尾</td><td>08-14</td><td>{draw}</td></tr>"


def _page(
    *,
    decoy_zodiac: str = "鼠",
    target_rows: tuple[tuple[int, str, str], ...] = ((300, "猪", "？00"), (299, "鼠", "猴23")),
    with_target_tab: bool = True,
    with_title_marker: bool = True,
) -> str:
    nav = (
        '<div class="item_nr1 item item1" onclick="toggleItemsV2(111,1,\'tab_tuku05v3a01\',\'#ff0000\',\'#07C160\')"> 绝杀⑤码 </div>'
    )
    if with_target_tab:
        nav += (
            '<div class="item_nr1 item item2" onclick="toggleItemsV2(222,2,\'tab_tuku05v3a01\',\'#ff0000\',\'#07C160\')"> 无敌杀码 </div>'
        )
    marker = "【无敌杀码】" if with_title_marker else "【别的栏目】"
    decoy = (
        '<div class="tab_tuku05v3Content111 tab_tuku05v3Content" style="display: none">'
        f"<table>{_headers()}{_row(300, decoy_zodiac)}</table></div>"
    )
    target = (
        '<div class="tab_tuku05v3Content222 tab_tuku05v3Content" style="display: none">'
        + "<table>"
        + _headers()
        + "".join(_row(period, zodiac, draw) for period, zodiac, draw in target_rows)
        + "</table></div>"
        if with_target_tab
        else ""
    )
    return (
        '<div class="nr_content_tab"><div class="scrollable-content">'
        + nav
        + "</div></div>"
        + '<div class="show_area">'
        + '<div class="tab_tuku05v3Title111 tab_tuku05v3Title" style="display: none">'
        + "<p><strong>300期:<span>别人家</span>【绝杀⑤码】example.test</strong></p></div>"
        + (
            '<div class="tab_tuku05v3Title222 tab_tuku05v3Title" style="display: none">'
            + f"<p><strong>300期:<span>黄宾虹黄</span>{marker}example.test</strong></p></div>"
            if with_target_tab
            else ""
        )
        + decoy
        + target
        + "</div>"
    )


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(html, URL, DocumentType.BROWSER, 0, f"browser-page:{URL}", 0, None)
    return SourceBundle((document,), ("browser:200", "scan_complete:1"), scan_complete=True)


def _site(name: str = "四舅黄宾虹黄肖", direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(name, URL, direction, SiteSection.NEW, PARSER_ID, "browser")


def test_site_binds_dedicated_parser() -> None:
    registry = build_registry()
    assert PARSER_ID in registry.parser_ids
    sites = load_sites(ROOT / "sites.json", parser_ids=registry.parser_ids, source_policies=SOURCE_POLICIES)
    site = next(item for item in sites if item.name == "四舅黄宾虹黄肖")
    assert site.parser_id == PARSER_ID
    assert site.section is SiteSection.NEW
    assert site.direction is Direction.TOP
    assert site.source_policy == "browser"
    assert site.embedded_max_bytes == 12000000


def test_kill_zodiac_column_of_wudi_tab_only() -> None:
    """同页「绝杀⑤码」也是六列表，但取值必须来自「无敌杀码」块。"""
    candidates = SijiuHuangbinhongKillZodiacParser().parse(_site(), _bundle(_page()))
    assert {item.period: item.zodiac for item in candidates} == {300: "猪", 299: "鼠"}
    first = candidates[0]
    assert "tab-content:222" in first.evidence
    assert "table-columns:期数/杀一肖/杀半波/杀一尾/禁一段/开奖结果" in first.evidence
    assert any(item.startswith("section:300期:黄宾虹黄【无敌杀码】") for item in first.evidence)
    assert "draw-status:pending" in first.evidence
    assert "draw-status:drawn" in candidates[1].evidence


def test_top_direction_uses_first_row() -> None:
    site = _site()
    bundle = _bundle(_page())
    candidates = SijiuHuangbinhongKillZodiacParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 300)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猪"


def test_history_window_via_left_direction() -> None:
    rows = tuple((period, zodiac, "猴23") for period, zodiac in (
        (300, "猪"), (299, "鼠"), (298, "猴"), (297, "兔"), (296, "鸡"),
        (295, "猴"), (294, "龙"), (293, "鸡"), (292, "龙"), (291, "猪"),
    ))
    bundle = _bundle(_page(target_rows=rows))
    site = _site(direction=Direction.LEFT)
    candidates = SijiuHuangbinhongKillZodiacParser().parse(site, bundle)
    values = {
        period: validate_candidates(site, bundle, candidates, period).candidate.zodiac
        for period in range(291, 301)
    }
    assert values == {item[0]: item[1] for item in rows}


def test_missing_tab_or_marker_returns_empty() -> None:
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(with_target_tab=False))) == ()
    assert parser.parse(_site(), _bundle(_page(with_title_marker=False))) == ()


def test_other_site_and_other_endpoint_return_empty() -> None:
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(name="别的站"), _bundle(_page())) == ()
    other = SourceDocument(
        _page(), "https://other.test/topic/1.html", DocumentType.BROWSER, 0, "browser-page:other", 0, None
    )
    bundle = SourceBundle((other,), ("browser:200", "scan_complete:1"), scan_complete=True)
    assert parser.parse(_site(), bundle) == ()
