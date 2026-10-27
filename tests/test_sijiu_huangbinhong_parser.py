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
HEADERS = "<tr><td>期数</td><td>杀一肖</td><td>杀半波</td><td>杀一尾</td><td>禁一段</td><td>开奖结果</td></tr>"


def _row(period: int, zodiac: str, draw: str = "？00", first_cell: str | None = None) -> str:
    head = first_cell if first_cell is not None else f"{period}期"
    return f"<tr><td>{head}</td><td>{zodiac}</td><td>蓝双</td><td>2尾</td><td>08-14</td><td>{draw}</td></tr>"


def _table(rows: str) -> str:
    return f"<table>{HEADERS}{rows}</table>"


def _content(content_id: int, table: str) -> str:
    return (
        f'<div class="tab_tuku05v3Content{content_id} tab_tuku05v3Content" style="display: none">'
        + table
        + "</div>"
    )


def _title(tab_id: int, text: str) -> str:
    return (
        f'<div class="tab_tuku05v3Title{tab_id} tab_tuku05v3Title" style="display: none">'
        f"<p><strong>{text}</strong></p></div>"
    )


def _nav(tab_id: int, label: str) -> str:
    return (
        f'<div class="item_nr1 item" onclick="toggleItemsV2({tab_id},2,\'tab_tuku05v3a01\',\'#ff0000\',\'#07C160\')"> {label} </div>'
    )


def _page(
    *,
    target_rows: tuple[tuple[int, str, str], ...] = ((300, "猪", "？00"), (299, "鼠", "猴23")),
    with_target_tab: bool = True,
    with_title_marker: bool = True,
    decoy_zodiac: str = "鼠",
    extra_table_in_block: bool = False,
    empty_zodiac_period: int | None = None,
    short_row_period: int | None = None,
    banner_after_period: int | None = None,
    decorate_period: int | None = None,
    duplicate_block: bool = False,
    conflicting_block: bool = False,
) -> str:
    body = ""
    for period, zodiac, draw in target_rows:
        if period == empty_zodiac_period:
            zodiac = ""
        if period == short_row_period:
            body += f"<tr><td>{period}期</td><td>{zodiac}</td><td>蓝双</td><td>2尾</td></tr>"
            continue
        first_cell = f"{period}期已开" if period == decorate_period else None
        body += _row(period, zodiac, draw, first_cell)
        if period == banner_after_period:
            body += '<tr><td colspan="6">【每日更新】数据仅供参考</td></tr>'

    target_table = _table(body)
    if extra_table_in_block:
        target_table = _table(_row(300, "鼠")) + target_table

    marker = "【无敌杀码】" if with_title_marker else "【别的栏目】"
    parts = [
        '<div class="nr_content_tab"><div class="scrollable-content">',
        _nav(111, "绝杀⑤码"),
        _nav(222, "无敌杀码") if with_target_tab else "",
        "</div></div>",
        '<div class="show_area">',
        _title(111, "300期:<span>别人家</span>【绝杀⑤码】example.test"),
        _title(222, f"300期:<span>黄宾虹黄</span>{marker}example.test") if with_target_tab else "",
    ]
    if conflicting_block:
        # 同标签同 id 的另一个块给出不同数据：来源不唯一，必须整页失败。
        parts.extend(
            [
                _nav(222, "无敌杀码"),
                _content(222, _table(_row(300, "马") + _row(299, "羊"))),
            ]
        )
    parts.append(_content(111, _table(_row(300, decoy_zodiac))))
    if with_target_tab:
        parts.append(_content(222, target_table))
        if duplicate_block:
            # 响应式重复渲染：同 id 同数据重复一份，应视为合法重复。
            parts.append(_content(222, target_table))
    parts.append("</div>")
    return "".join(parts)


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
    rows = tuple(
        (period, zodiac, "猴23")
        for period, zodiac in (
            (300, "猪"), (299, "鼠"), (298, "猴"), (297, "兔"), (296, "鸡"),
            (295, "猴"), (294, "龙"), (293, "鸡"), (292, "龙"), (291, "猪"),
        )
    )
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


def test_two_tables_with_same_header_in_one_block_are_rejected() -> None:
    """同块两张同表头的表无法唯一证明来源，必须整块放弃，不能取第一张。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(extra_table_in_block=True))) == ()
    # 同一套解析器在正常页面上仍然出值，避免「整体坏掉也绿」。
    assert len(parser.parse(_site(), _bundle(_page()))) == 2


def test_conflicting_second_block_is_rejected() -> None:
    """同标签另一个块给出不同数据时冲突，不能取先出现的那块。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(conflicting_block=True))) == ()


def test_identical_duplicate_block_is_accepted() -> None:
    """响应式重复渲染出的同一份数据块属合法重复，不应整站失败。"""
    candidates = SijiuHuangbinhongKillZodiacParser().parse(_site(), _bundle(_page(duplicate_block=True)))
    assert {item.period: item.zodiac for item in candidates} == {300: "猪", 299: "鼠"}


def test_empty_zodiac_cell_fails_instead_of_truncating() -> None:
    """期数行的取值格为空时必须失败，不能静默只剩前几期。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(empty_zodiac_period=299))) == ()


def test_short_period_row_fails_instead_of_truncating() -> None:
    """期数行缺列（合并单元格）同样视为列错位，整块失败。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(short_row_period=299))) == ()


def test_banner_row_between_records_fails_instead_of_truncating() -> None:
    """数据行中间插横幅/合并行后若还接着出现期数行，属中途断裂，必须失败。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(banner_after_period=300))) == ()


def test_decorated_period_cell_fails_instead_of_truncating() -> None:
    """期数格被加装饰（如「300期已开」）时不能当成数据区结束。"""
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(), _bundle(_page(decorate_period=299))) == ()


def test_trailing_footer_row_still_parses() -> None:
    """表尾的说明行（后面不再有期数行）不影响取数。"""
    candidates = SijiuHuangbinhongKillZodiacParser().parse(
        _site(), _bundle(_page(banner_after_period=299))
    )
    assert {item.period: item.zodiac for item in candidates} == {300: "猪", 299: "鼠"}


def test_other_site_and_other_endpoint_return_empty() -> None:
    parser = SijiuHuangbinhongKillZodiacParser()
    assert parser.parse(_site(name="别的站"), _bundle(_page())) == ()
    other = SourceDocument(
        _page(), "https://other.test/topic/1.html", DocumentType.BROWSER, 0, "browser-page:other", 0, None
    )
    bundle = SourceBundle((other,), ("browser:200", "scan_complete:1"), scan_complete=True)
    assert parser.parse(_site(), bundle) == ()
