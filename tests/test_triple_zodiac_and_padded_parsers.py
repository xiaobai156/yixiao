# -*- coding: utf-8 -*-
"""鳞次栉比/万川境身（三字重复生肖）与 忠不可兼（补零期号）专属解析器测试。

万川境身已因与「忧心如梦」重复被封存，故用合成 SiteConfig，不依赖 sites.json。
"""
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
from zodiac_v2.parsers.dedicated import TripleZodiacBlockParser, ZhongBukejianPaddedParser
from zodiac_v2.parsers.registry import build_registry

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.test/topic/1.html"


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(
        html,
        URL,
        DocumentType.HTML,
        0,
        "html:test",
        0,
        None,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def _synthetic(name: str) -> SiteConfig:
    return SiteConfig(
        name=name,
        url=URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.triple_zodiac_block",
        source_policy="http_documents",
    )


def _site(name: str):
    """优先从 sites.json 取真实配置；已封存的站退回合成配置。"""
    registry = build_registry()
    sites = load_sites(
        ROOT / "sites.json",
        parser_ids=registry.parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    found = next((site for site in sites if site.name == name), None)
    return found if found is not None else _synthetic(name)


def test_parsers_registered_and_bound() -> None:
    registry = build_registry()
    assert "special.triple_zodiac_block" in registry.parser_ids
    assert "special.zhong_bukejian_padded" in registry.parser_ids
    assert _site("鳞次栉比").parser_id == "special.triple_zodiac_block"
    assert _site("忠不可兼").parser_id == "special.zhong_bukejian_padded"


def test_triple_zodiac_keeps_pending_block_only() -> None:
    """三字重复生肖可解析；模板块当期已填开奖号，被占位判据排除。"""
    html = """
    <div>万川境身 发表于 05月21日 09:28:41</div>
    <div>294期【绝杀一肖】【鸡鸡鸡】开0000准</div>
    <div>293期【绝杀一肖】【兔兔兔】开虎05准</div>
    <div>292期【绝杀一肖】【蛇蛇蛇】开羊36准</div>
    <div>295期【绝杀一肖】【兔兔兔】开牛05准</div>
    <div>294期【绝杀一肖】【蛇蛇蛇】开鼠18准</div>
    <div>293期【绝杀一肖】【虎虎虎】开羊47准</div>
    """
    candidates = TripleZodiacBlockParser().parse(_site("万川境身"), _bundle(html))
    periods = {c.period: c.zodiac for c in candidates}
    assert periods[294] == "鸡"
    assert 295 not in periods
    assert all(c.zodiac == periods[c.period] for c in candidates)
    assert any("draw-status:pending" in c.evidence for c in candidates if c.period == 294)


def test_triple_zodiac_single_char_also_matches() -> None:
    html = """
    <div>鳞次栉比 发表于 10月21日 01:05:51</div>
    <div>294期【绝杀一肖】【狗】开0000准</div>
    <div>293期【绝杀一肖】【鼠】开虎05准</div>
    """
    candidates = TripleZodiacBlockParser().parse(_site("鳞次栉比"), _bundle(html))
    assert {c.period: c.zodiac for c in candidates} == {294: "狗", 293: "鼠"}


def test_triple_zodiac_other_site_returns_empty() -> None:
    parser = TripleZodiacBlockParser()
    html = "<div>294期【绝杀一肖】【鸡鸡鸡】开0000准</div>"
    assert parser.parse(_synthetic("别的站"), _bundle(html)) == ()


def test_zhong_bukejian_padded_period_parsed() -> None:
    """期号补零（024期）+ 行尾准/错 可解析。"""
    html = """
    <div>作者:忠不可兼</div>
    <div>024期：绝杀1肖【猪】 开虎28准</div>
    <div>025期：绝杀1肖【马】 开蛇37准</div>
    <div>294期：绝杀1肖【羊】 开？00准</div>
    """
    candidates = ZhongBukejianPaddedParser().parse(_site("忠不可兼"), _bundle(html))
    periods = {c.period: c.zodiac for c in candidates}
    assert periods == {24: "猪", 25: "马", 294: "羊"}
    assert any("draw-status:pending" in c.evidence for c in candidates if c.period == 294)


def test_zhong_bukejian_other_site_returns_empty() -> None:
    parser = ZhongBukejianPaddedParser()
    html = "<div>294期：绝杀1肖【羊】 开？00准</div>"
    assert parser.parse(_synthetic("别的站"), _bundle(html)) == ()
