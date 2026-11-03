# -*- coding: utf-8 -*-
"""高手网论坛：专属解析器（『绝杀1肖1尾』表取杀一肖）与配置用例。"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.registry import ParserRejection, build_registry
from zodiac_v2.validation.conflicts import validate_candidates

ROOT = Path(__file__).resolve().parents[1]

URL = "https://799689.cc/"
PARSER_ID = "special.gaoshou_wang_luntan_kill_zodiac"
WINDOW = tuple(range(293, 303))

ROWS = (
    (302, "虎", 9, "888"),
    (301, "牛", 7, "鸡10"),
    (300, "鼠", 6, "鸡22"),
    (299, "蛇", 8, "狗09"),
    (298, "猪", 9, "蛇26"),
    (297, "猪", 7, "兔16"),
    (296, "鸡", 5, "猴47"),
    (295, "牛", 8, "蛇26"),
    (294, "羊", 2, "虎41"),
    (293, "龙", 5, "羊12"),
)
WINDOW_TEXT = "龙羊牛鸡猪猪蛇鼠牛虎"

HEAD = (
    '<div class="a1">\n<table width="100%" id="table1" cellspacing="0" cellpadding="0"><tbody>\n'
    '<tr><td style="text-align:center" height="60">\n'
    '<table border="1" width="100%"><tbody><tr><td bgcolor="#0000FF"><p align="center">\n'
    '<b><font color="#FFFF00">799689.com</font><font color="#FFFFFF">『绝杀1肖1尾』</font></b>'
    "</p></td></tr></tbody></table>\n"
    "    </td></tr>\n"
)
ROW = (
    '    <tr><td height="40" bgcolor="#FFFFFF" align="left">\n'
    '<p align="center"><font face="微软雅黑"><b>\n'
    "<font color=\"{}\" size=\"3\">{}期</font>"
    "<font color=\"#FF0000\">【{}+{}尾】</font>"
    "<font color=\"#000000\" size=\"3\">开</font>\n  "
    "<font size=\"3\">{}准</font><font color=\"#FF0000\" size=\"5\">√</font></b></font></p></td>\n"
    "    </tr>\n"
)
TAIL = "  </tbody>\n</table>\n </div>\n\n<div class=\"a1\"></div>\n"


def _html(rows=ROWS, head: str = HEAD, tail: str = TAIL) -> str:
    body = "".join(ROW.format("#000000", period, zodiac, tail_, draw) for period, zodiac, tail_, draw in rows)
    return head + body + tail


def _site(direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig("高手网论坛", URL, direction, SiteSection.EXISTING, PARSER_ID, "http_documents")


def _bundle(text: str) -> SourceBundle:
    document = SourceDocument(text, URL, DocumentType.HTML, 0, "http:0", 0)
    return SourceBundle((document,), scan_complete=True)


def test_top_edge_picks_302_and_full_window() -> None:
    site = _site()
    bundle = _bundle(_html())
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "虎"
    assert "『绝杀1肖1尾』" in decision.candidate.evidence[0]

    history_site = replace(site, direction=Direction.LEFT)
    history = build_registry().parse(history_site, bundle)
    values = {}
    for period in WINDOW:
        decided = validate_candidates(history_site, bundle, history, period)
        if decided.ok and decided.candidate is not None:
            values[period] = decided.candidate.zodiac
    assert "".join(values[period] for period in WINDOW) == WINDOW_TEXT


def test_duplicate_title_rejected() -> None:
    head = HEAD + '<div class="a1"><p>『绝杀1肖1尾』</p></div>\n'
    with pytest.raises(ParserRejection, match="来源不唯一"):
        build_registry().parse(_site(), _bundle(_html(head=head)))


def test_broken_data_region_rejected() -> None:
    rows = "".join(ROW.format("#000000", p, z, t, d) for p, z, t, d in ROWS[:3])
    rows += '    <tr><td><p>本站暂停更新，请稍后再来</p></td></tr>\n'
    rows += "".join(ROW.format("#000000", p, z, t, d) for p, z, t, d in ROWS[3:])
    with pytest.raises(ParserRejection, match="数据区被非期数行打断"):
        build_registry().parse(_site(), _bundle(HEAD + rows + TAIL))


def test_extra_matching_row_outside_section_rejected() -> None:
    extra = (
        '<div class="a1"><table><tbody><tr><td><p>'
        "<font>302期</font><font>【马+3尾】</font><font>开</font>\n"
        "<font>龙27准</font></p></td></tr></tbody></table></div>\n"
    )
    with pytest.raises(ParserRejection, match="来源不唯一"):
        build_registry().parse(_site(), _bundle(_html(tail=TAIL + extra)))


def test_registered_as_existing_site_with_dedicated_parser() -> None:
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))
    entry = next(item for item in sites if item["name"] == "高手网论坛")
    assert entry["url"] == URL
    assert entry["pick"] == "top"
    assert entry["section"] == SiteSection.EXISTING.value
    assert entry["parser_id"] == PARSER_ID
    assert entry["source_policy"] == "http_documents"
