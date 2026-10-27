# -*- coding: utf-8 -*-
"""鞠躬尽瘁 专属解析器测试：《综合杀料》里「杀X」取该生肖。"""
from __future__ import annotations

from pathlib import Path

from zodiac_v2.cli import SOURCE_POLICIES
from zodiac_v2.config import load_sites
from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import JugongJincuiKillZodiacParser
from zodiac_v2.parsers.registry import build_registry

ROOT = Path(__file__).resolve().parents[1]


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(
        html,
        "https://example.test/topic/1.html",
        DocumentType.HTML,
        0,
        "html:test",
        0,
        None,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def _site():
    registry = build_registry()
    sites = load_sites(
        ROOT / "sites.json",
        parser_ids=registry.parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    return next(site for site in sites if site.name == "鞠躬尽瘁")


def _renamed(site, name: str):
    values = {field: getattr(site, field) for field in site.__slots__}
    values["name"] = name
    return type(site)(**values)


def test_site_binds_dedicated_parser() -> None:
    registry = build_registry()
    assert "special.jugong_jincui_kill_zodiac" in registry.parser_ids
    site = _site()
    assert site.parser_id == "special.jugong_jincui_kill_zodiac"
    assert site.section == "新增的站点"


def test_kill_zodiac_takes_zodiac_after_kill() -> None:
    """【杀猪-3尾-绿单】取「猪」，横线后的尾数/颜色不参与取值。"""
    html = """
    <div>294期：【综合杀料】鞠躬尽瘁</div>
    <div>294期:《综合杀料》【杀猪-3尾-绿单】开0000准</div>
    <div>293期:《综合杀料》【杀羊-8尾-绿双】开虎05准</div>
    <div>292期:《综合杀料》【杀马-3尾-红双】开羊36准</div>
    """
    candidates = JugongJincuiKillZodiacParser().parse(_site(), _bundle(html))
    assert {c.period: c.zodiac for c in candidates} == {294: "猪", 293: "羊", 292: "马"}
    assert any("draw-status:pending" in c.evidence for c in candidates if c.period == 294)
    # 标题行锚点必须落到真实行号，不能是 none
    assert all(
        any(item.startswith("author-line:") and not item.endswith("none") for item in c.evidence)
        for c in candidates
    )


def test_wrong_section_format_not_matched() -> None:
    """没有《综合杀料》栏目、或不是「杀X-…」格式时不输出。"""
    html = """
    <div>294期：【综合杀料】鞠躬尽瘁</div>
    <div>294期:绝杀一肖【猪】开0000准</div>
    """
    assert JugongJincuiKillZodiacParser().parse(_site(), _bundle(html)) == ()


def test_other_site_returns_empty() -> None:
    parser = JugongJincuiKillZodiacParser()
    html = "<div>294期:《综合杀料》【杀猪-3尾-绿单】开0000准</div>"
    assert parser.parse(_renamed(_site(), "别的站"), _bundle(html)) == ()
