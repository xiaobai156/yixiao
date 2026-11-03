# -*- coding: utf-8 -*-
"""创富千里眼 专属解析器测试：只认「澳门创富『精打细算』」板块的「千里眼杀一肖」。"""
from __future__ import annotations

from pathlib import Path

import pytest

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
from zodiac_v2.parsers.dedicated import ChuangfuQianliyanKillZodiacParser
from zodiac_v2.parsers.registry import ParserRejection, build_registry
from zodiac_v2.validation.conflicts import validate_candidates

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.test/"
PARSER_ID = "special.chuangfu_qianliyan_kill_zodiac"
ROWS = (
    (302, "猴", "0000"),
    (301, "猪", "虎17"),
    (300, "马", "蛇38"),
    (299, "龙", "猴23"),
    (298, "鸡", "猪08"),
    (297, "蛇", "马13"),
    (296, "猴", "猴23"),
    (295, "鼠", "马25"),
    (294, "猪", "兔28"),
    (293, "鼠", "虎05"),
    (292, "龙", "蛇30"),
    (291, "牛", "虎17"),
    (290, "鸡", "兔40"),
)


def _block(period: int, zodiac: str, draw: str = "0000") -> str:
    return (
        "<tr><td>"
        f'<p><strong><span>{period}期精打细算(特开{draw})</span><br>'
        f'<span>千里眼杀一肖：<span>【{zodiac}肖】√</span></span><br>'
        '<span>万花巷杀一行：<span>【土行】√</span></span></strong></p>'
        "</td></tr>"
    )


def _decoy_block(period: int, zodiac: str) -> str:
    return (
        "<tr><td>"
        f'<p><strong><span>{period}期六组三中三</span><br>'
        f'<span>千里眼杀一肖：<span>【{zodiac}肖】√</span></span></strong></p>'
        "</td></tr>"
    )


def _title(label: str = "『精打细算』", brand: str = "澳门创富") -> str:
    return (
        '<div class="dz_title13" style="background: linear-gradient(#40407a,#ff5252);">\n'
        f"  <span>{brand}</span>\n  <span>{label}</span>\n</div>"
    )


def _content(rows: str) -> str:
    return f'<div class="dz_content08 dz_content08abd"><table><tbody>{rows}</tbody></table></div>'


def _page(
    rows: tuple[tuple[int, str, str], ...] = ROWS,
    *,
    with_title: bool = True,
    duplicate_title: bool = False,
    wrong_brand: bool = False,
    decoy_section: bool = True,
    period_without_value: int | None = None,
    orphan_value: bool = False,
) -> str:
    body = ""
    for period, zodiac, draw in rows:
        if period == period_without_value:
            body += (
                "<tr><td>"
                f'<p><strong><span>{period}期精打细算(特开{draw})</span><br>'
                '<span>万花巷杀一行：<span>【土行】√</span></span></strong></p>'
                "</td></tr>"
            )
            continue
        body += _block(period, zodiac, draw)
    if orphan_value:
        body += (
            "<tr><td>"
            "<p><strong><span>千里眼杀一肖：<span>【鼠肖】√</span></span></strong></p>"
            "</td></tr>"
        )
    brand = "别的品牌" if wrong_brand else "澳门创富"
    parts = [
        _title(brand=brand) if with_title else "",
        _title(brand=brand) if duplicate_title else "",
        _content(body),
    ]
    if decoy_section:
        # 别的板块也有同名「千里眼杀一肖」列，必须不被采信。
        parts.extend(
            [
                _title("『六组三中三』"),
                _content(_decoy_block(302, "鼠") + _decoy_block(301, "羊")),
            ]
        )
    return "".join(parts)


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(html, URL, DocumentType.BROWSER, 0, f"browser-page:{URL}", 0, None)
    return SourceBundle((document,), ("browser:200", "scan_complete:1"), scan_complete=True)


def _site(name: str = "创富千里眼", direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(name, URL, direction, SiteSection.NEW, PARSER_ID, "browser")


def _reject(html: str) -> str:
    with pytest.raises(ParserRejection) as info:
        ChuangfuQianliyanKillZodiacParser().parse(_site(), _bundle(html))
    return str(info.value)


def test_site_binds_dedicated_parser() -> None:
    registry = build_registry()
    assert PARSER_ID in registry.parser_ids
    sites = load_sites(
        ROOT / "sites.json",
        parser_ids=registry.parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    site = next(item for item in sites if item.name == "创富千里眼")
    assert site.parser_id == PARSER_ID
    assert site.section is SiteSection.EXISTING
    assert site.direction is Direction.TOP
    assert site.source_policy == "browser"


def test_kill_zodiac_column_of_target_section_only() -> None:
    """同页「六组三中三」板块也有「千里眼杀一肖」，取值必须来自『精打细算』板块。"""
    candidates = ChuangfuQianliyanKillZodiacParser().parse(_site(), _bundle(_page()))
    values = {item.period: item.zodiac for item in candidates}
    assert values == {period: zodiac for period, zodiac, _draw in ROWS}
    first = candidates[0]
    assert first.period == 302 and first.zodiac == "猴"
    assert "section:『精打细算』" in first.evidence
    assert "table-columns:期数/千里眼杀一肖" in first.evidence
    assert "draw-status:pending" in first.evidence
    assert any(item.startswith("anchor-line:") for item in first.evidence)
    assert any(item.startswith("section-range:") for item in first.evidence)


def test_top_direction_takes_current_period() -> None:
    site = _site()
    bundle = _bundle(_page())
    candidates = ChuangfuQianliyanKillZodiacParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猴"


def test_history_window_via_left_direction() -> None:
    rows = tuple(
        (period, zodiac, "猴23")
        for period, zodiac in (
            (302, "猴"), (301, "猪"), (300, "马"), (299, "龙"), (298, "鸡"),
            (297, "蛇"), (296, "猴"), (295, "鼠"), (294, "猪"), (293, "鼠"),
        )
    )
    bundle = _bundle(_page(rows))
    site = _site(direction=Direction.LEFT)
    candidates = ChuangfuQianliyanKillZodiacParser().parse(site, bundle)
    values = {
        period: validate_candidates(site, bundle, candidates, period).candidate.zodiac
        for period in range(293, 303)
    }
    assert values == {item[0]: item[1] for item in rows}


def test_missing_or_ambiguous_title_is_rejected() -> None:
    assert "『精打细算』" in _reject(_page(with_title=False))
    assert "来源不唯一" in _reject(_page(duplicate_title=True))
    assert "澳门创富" in _reject(_page(wrong_brand=True))


def test_period_row_without_value_is_rejected() -> None:
    """期数行后面没有取值行时不能静默跳过，必须整站失败并说明原因。"""
    reason = _reject(_page(period_without_value=298))
    assert "取值" in reason or "取值行" in reason


def test_orphan_value_row_is_rejected() -> None:
    """有取值却没有期数行的错位结构不可信，不能猜它是哪一期。"""
    assert "结构可疑" in _reject(_page(orphan_value=True))


def test_other_site_name_is_ignored() -> None:
    assert ChuangfuQianliyanKillZodiacParser().parse(
        _site(name="别的站"), _bundle(_page())
    ) == ()
