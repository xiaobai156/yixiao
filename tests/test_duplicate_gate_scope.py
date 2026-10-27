# -*- coding: utf-8 -*-
"""判重取值口径必须与统一校验器一致：多循环页面按方向挑组，不能混取。"""
from __future__ import annotations

from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceDocument,
)
from zodiac_v2.services.duplicate_gate import _candidate_records


def _site(direction: Direction) -> SiteConfig:
    return SiteConfig(
        name="多循环站",
        url="https://example.test/multi",
        direction=direction,
        section=SiteSection.EXISTING,
        parser_id="test",
        source_policy="http_documents",
    )


def _doc() -> SourceDocument:
    return SourceDocument(
        "<div>x</div>",
        "https://example.test/multi",
        DocumentType.HTML,
        0,
        "html:multi",
        0,
        None,
    )


def _cand(period: int, zodiac: str, page_order: int, cycle: str) -> Candidate:
    return Candidate(
        period=period,
        zodiac=zodiac,
        raw_line=f"{period}期 {zodiac}",
        document_id="html:multi",
        page_order=page_order,
        evidence=(f"record-cycle:{cycle}", "field:绝杀一肖"),
    )


class _Parser:
    """模拟页面里有两套循环：A 组与 B 组，同期生肖不同。"""

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, site, bundle):
        self.calls += 1
        return (
            _cand(294, "鸡", 10, "A"),
            _cand(293, "蛇", 11, "A"),
            _cand(292, "马", 12, "A"),
            _cand(294, "虎", 20, "B"),
            _cand(293, "牛", 21, "B"),
            _cand(292, "鼠", 22, "B"),
        )


class _Result:
    def __init__(self, site):
        self.site = site
        self.documents = (_doc(),)


def test_top_direction_picks_first_cycle() -> None:
    site = _site(Direction.TOP)
    records = _candidate_records(_Result(site), _Parser())
    values = {r.period: r.zodiac for r in records}
    assert values == {294: "鸡", 293: "蛇", 292: "马"}


def test_bottom_direction_picks_last_cycle() -> None:
    """尾部方向必须取最后一组，不能取第一组（这正是此前的口径缺陷）。"""
    site = _site(Direction.BOTTOM)
    records = _candidate_records(_Result(site), _Parser())
    values = {r.period: r.zodiac for r in records}
    assert values == {294: "虎", 293: "牛", 292: "鼠"}


def test_single_cycle_unaffected() -> None:
    class OneCycle:
        def parse(self, site, bundle):
            return (_cand(294, "鸡", 1, "A"), _cand(293, "蛇", 2, "A"))

    site = _site(Direction.BOTTOM)
    records = _candidate_records(_Result(site), OneCycle())
    assert {r.period: r.zodiac for r in records} == {294: "鸡", 293: "蛇"}


def test_no_cycle_evidence_keeps_all() -> None:
    """解析器没给 record-cycle 证据时，_active_candidates 原样返回，不做筛选。"""

    class NoCycle:
        def parse(self, site, bundle):
            return (
                Candidate(
                    period=294,
                    zodiac="鸡",
                    raw_line="294期 鸡",
                    document_id="html:multi",
                    page_order=1,
                    evidence=("field:绝杀一肖",),
                ),
                Candidate(
                    period=293,
                    zodiac="蛇",
                    raw_line="293期 蛇",
                    document_id="html:multi",
                    page_order=2,
                    evidence=("field:绝杀一肖",),
                ),
            )

    site = _site(Direction.TOP)
    records = _candidate_records(_Result(site), NoCycle())
    assert {r.period: r.zodiac for r in records} == {294: "鸡", 293: "蛇"}
