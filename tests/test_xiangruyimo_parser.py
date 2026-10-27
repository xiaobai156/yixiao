# -*- coding: utf-8 -*-
"""相濡以沫 专属解析器：只取「当期未开奖」的真实发布记录，排除提前填开奖号的模板序列。

该站已因与「老奇人第一版」重复被封存，故测试用合成 SiteConfig，不依赖 sites.json。
"""
from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import XiangruyimoDrawVerifiedParser

URL = "https://example.test/topic/349687.html"


def _site(name: str = "相濡以沫") -> SiteConfig:
    return SiteConfig(
        name=name,
        url=URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.xiangruyimo_draw_verified",
        source_policy="browser",
    )


def _bundle(html: str) -> SourceBundle:
    document = SourceDocument(
        html,
        URL,
        DocumentType.BROWSER,
        0,
        "browser-page:test",
        0,
        None,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def test_only_pending_record_is_kept() -> None:
    """模板序列给当期就填了开奖号，真实序列当期是占位；只保留占位那条。"""
    html = """
    <div>294期:相濡以沫【精杀一肖】杀料专区</div>
    <div>相濡以沫 发表于 10月21日 09:26:46</div>
    <div>294期:【精杀一肖】【鸡】開：0000准</div>
    <div>293期:【精杀一肖】【蛇】開：虎05准</div>
    <div>295期:【精杀一肖】【兔】開：牛05准</div>
    <div>294期:【精杀一肖】【龙】開：鼠18准</div>
    <div>293期:【精杀一肖】【虎】開：羊47准</div>
    """
    candidates = XiangruyimoDrawVerifiedParser().parse(_site(), _bundle(html))
    assert len(candidates) == 1
    assert candidates[0].period == 294
    assert candidates[0].zodiac == "鸡"
    assert "draw-status:pending" in candidates[0].evidence


def test_two_pending_records_rejected() -> None:
    """占位记录不唯一时拒绝输出，禁止猜值。"""
    html = """
    <div>相濡以沫 发表于 10月21日 09:26:46</div>
    <div>294期:【精杀一肖】【鸡】開：0000准</div>
    <div>294期:【精杀一肖】【龙】開：0000准</div>
    """
    assert XiangruyimoDrawVerifiedParser().parse(_site(), _bundle(html)) == ()


def test_no_pending_record_rejected() -> None:
    """没有占位记录（都已开奖）时不输出。"""
    html = """
    <div>相濡以沫 发表于 10月21日 09:26:46</div>
    <div>294期:【精杀一肖】【龙】開：鼠18准</div>
    """
    assert XiangruyimoDrawVerifiedParser().parse(_site(), _bundle(html)) == ()


def test_other_site_returns_empty() -> None:
    parser = XiangruyimoDrawVerifiedParser()
    html = "<div>294期:【精杀一肖】【鸡】開：0000准</div>"
    assert parser.parse(_site("别的站"), _bundle(html)) == ()


def test_fullwidth_placeholder_also_accepted() -> None:
    """全角问号占位（？00）同样视为未开奖。"""
    html = """
    <div>相濡以沫 发表于 10月21日 09:26:46</div>
    <div>294期:【精杀一肖】【鸡】開：？00准</div>
    """
    candidates = XiangruyimoDrawVerifiedParser().parse(_site(), _bundle(html))
    assert len(candidates) == 1
    assert candidates[0].zodiac == "鸡"
