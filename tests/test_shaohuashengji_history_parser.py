# -*- coding: utf-8 -*-
"""韶华胜极 专属解析器：只取正文真实历史区，忽略顶部未来期模板区。"""
from __future__ import annotations

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import ShaohuashengjiHistoryParser
from zodiac_v2.parsers.registry import build_registry


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(
        html,
        "https://example.test/topic/1.html",
        DocumentType.BROWSER,
        0,
        "browser-page:test",
        0,
        None,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def _site():
    registry = build_registry()
    assert "special.shaohuashengji_history" in registry.parser_ids
    from pathlib import Path

    from zodiac_v2.cli import SOURCE_POLICIES
    from zodiac_v2.config import load_sites

    root = Path(__file__).resolve().parents[1]
    sites = load_sites(root / "sites.json", parser_ids=registry.parser_ids, source_policies=SOURCE_POLICIES)
    return next(site for site in sites if site.name == "韶华胜极")


def test_site_binds_dedicated_parser() -> None:
    assert _site().parser_id == "special.shaohuashengji_history"


def test_ignores_future_template_block() -> None:
    """顶部模板区期数倒序且含未来期；只应取到正文区，目标期不冲突。"""
    html = """
    <div>294期:韶华胜极【绝杀一肖】已公开</div>
    <div>作者:韶华胜极</div>
    <div>294期：绝杀一肖【虎】开鼠18准</div>
    <div>295期：绝杀一肖【马】开牛05准</div>
    <div>296期：绝杀一肖【猪】开猴22准</div>
    <div>293期：绝杀一肖【兔】开虎05准</div>
    <div>294期：绝杀一肖【猪】开？00准</div>
    """
    candidates = ShaohuashengjiHistoryParser().parse(_site(), _bundle(html))
    target = [c for c in candidates if c.period == 294]
    assert len(target) == 1
    assert target[0].zodiac == "猪"
    # 未来期 295/296 属模板区，不应进入候选
    assert not [c for c in candidates if c.period in (295, 296)]


def test_other_site_returns_empty() -> None:
    site = _site()
    values = {field: getattr(site, field) for field in site.__slots__}
    values["name"] = "别的站"
    other = type(site)(**values)
    assert ShaohuashengjiHistoryParser().parse(other, _bundle("<div>294期：绝杀一肖【猪】</div>")) == ()
