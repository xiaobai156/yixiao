# -*- coding: utf-8 -*-
"""302 期接入的三站：九五之尊 / 旧梦思维 / 六合心经最专业。

三站页面都在最上面挂了一条「下一期还没开奖」的预告行（开??），
专属解析器把它标成 record-status:incomplete，方向窗口据此忽略它，
所以 top 方向仍以指定期为首组，不会被预告行顶掉。
"""
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
WINDOW = tuple(range(293, 303))

JIUWU_URL = "https://nedmannv.ueihu-xk88p-uvbyxa.xyz:16677/topic/461732.html"
JIUMENG_URL = "https://mm.198864.com:1888/bbs/144.html"
LIUHE_URL = "https://cc.979545m.com:1888/bbs/7977"

JIUWU_PARSER = "special.jiujiu_zhizun_kill_zodiac"
JIUMENG_PARSER = "special.jiumeng_siwei_kill_zodiac"
LIUHE_PARSER = "special.liuhe_xinjing_zhuanye_kill_zodiac"

# 302 → 293
JIUWU_ROWS = (
    (302, "狗", "狗45错"),
    (301, "羊", "虎17准"),
    (300, "龙", "蛇38准"),
    (299, "狗", "猴23准"),
    (298, "兔", "猪08准"),
    (297, "猪", "马13准"),
    (296, "虎", "猴23准"),
    (295, "牛", "马25准"),
    (294, "蛇", "兔28准"),
    (293, "兔", "虎05准"),
)
JIUWU_WINDOW = "狗羊龙狗兔猪虎牛蛇兔"

JIUMENG_ROWS = (
    (302, "鼠", "45狗"),
    (301, "羊", "17虎"),
    (300, "猪", "38蛇"),
    (299, "虎", "23猴"),
    (298, "兔", "08猪"),
    (297, "鼠", "13马"),
    (296, "羊", "23猴"),
    (295, "猪", "25马"),
    (294, "猪", "28兔"),
    (293, "蛇", "05虎"),
)
JIUMENG_WINDOW = "鼠羊猪虎兔鼠羊猪猪蛇"

# 站方缺 301、295
LIUHE_ROWS = (
    (302, "龙", "狗45"),
    (300, "猪", "蛇38"),
    (299, "兔", "猴23"),
    (298, "虎", "猪08"),
    (297, "虎", "马13"),
    (296, "狗", "猴23"),
    (294, "龙", "兔28"),
    (293, "马", "虎05"),
)
LIUHE_WINDOW = "龙猪兔虎虎狗龙马"


def _bundle(text: str, url: str) -> SourceBundle:
    document = SourceDocument(text, url, DocumentType.BROWSER, 0, "browser:0", 0)
    return SourceBundle((document,), scan_complete=True)


def _site(name: str, url: str, parser_id: str) -> SiteConfig:
    return SiteConfig(name, url, Direction.TOP, SiteSection.EXISTING, parser_id, "browser")


def _window(registry, site: SiteConfig, bundle: SourceBundle) -> str:
    left = replace(site, direction=Direction.LEFT)
    candidates = registry.parse(left, bundle)
    values = {}
    for period in WINDOW:
        decided = validate_candidates(left, bundle, candidates, period)
        if decided.ok and decided.candidate is not None:
            values[period] = decided.candidate.zodiac
    return "".join(values[period] for period in sorted(values, reverse=True))


# ---------------------------------------------------------------- 九五之尊

def _jiuwu_html(rows=JIUWU_ROWS, pending: bool = True) -> str:
    head = (
        '<div class="buttom"><div class="title">精华料303期:【绝杀一肖】</div>'
        '<div class="content">'
    )
    body = ""
    if pending:
        body += '<p>303期：<span class="style7">绝杀一肖</span>【猴猴猴】特0000准</p>\n'
    for period, zodiac, draw in rows:
        body += (
            f'<p>{period}期：<span class="style7">绝杀一肖</span>'
            f"【{zodiac}{zodiac}{zodiac}】特{draw}</p>\n"
        )
    return f'{head}{body}</div></div><div class="author">九五之尊</div>'


def test_jiuwu_top_takes_302_and_full_window() -> None:
    site = _site("九五之尊", JIUWU_URL, JIUWU_PARSER)
    bundle = _bundle(_jiuwu_html(), JIUWU_URL)
    registry = build_registry()
    candidates = registry.parse(site, bundle)

    pending = next(item for item in candidates if item.period == 303)
    assert "record-status:incomplete" in pending.evidence
    assert "draw-status:pending" in pending.evidence

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "狗"
    assert "【绝杀一肖】" in decision.candidate.evidence[0]
    assert _window(registry, site, bundle) == JIUWU_WINDOW


def test_jiuwu_duplicate_section_rejected() -> None:
    html = _jiuwu_html() + '<div class="title">精华料303期:【绝杀一肖】</div>'
    html += '<div class="title">精华料303期:【绝杀一肖】</div>'
    with pytest.raises(ParserRejection, match="来源不唯一"):
        build_registry().parse(_site("九五之尊", JIUWU_URL, JIUWU_PARSER), _bundle(html, JIUWU_URL))


# ---------------------------------------------------------------- 旧梦思维

def _jiumeng_html(rows=JIUMENG_ROWS, pending: bool = True) -> str:
    head = (
        '<div class="tit-date"><div class="tit-date-l">作者：旧梦思维</div></div>'
        '<div class="cgi-content"><div class="t">303期:必杀一肖</div>\n'
    )
    body = ""
    if pending:
        body += '<p>303期 旧梦思维杀肖<span class="am_tit">【羊】</span>开??准 </p>\n'
    for period, zodiac, draw in rows:
        body += (
            f'<p>{period}期 旧梦思维杀肖<span class="am_tit">【{zodiac}】</span>'
            f"开{draw}准 </p>\n"
        )
    return f"{head}{body}</div>"


def test_jiumeng_top_takes_302_and_full_window() -> None:
    site = _site("旧梦思维", JIUMENG_URL, JIUMENG_PARSER)
    bundle = _bundle(_jiumeng_html(), JIUMENG_URL)
    registry = build_registry()
    candidates = registry.parse(site, bundle)

    pending = next(item for item in candidates if item.period == 303)
    assert "record-status:incomplete" in pending.evidence

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "鼠"
    assert decision.candidate.raw_line.startswith("302期 旧梦思维杀肖【鼠】")
    assert _window(registry, site, bundle) == JIUMENG_WINDOW


def test_jiumeng_broken_data_region_rejected() -> None:
    head = (
        '<div class="tit-date-l">作者：旧梦思维</div><div class="cgi-content">'
        "<div>303期:必杀一肖</div>\n"
        '<p>303期 旧梦思维杀肖<span>【羊】</span>开??准 </p>\n'
        '<p>302期 旧梦思维杀肖<span>【鼠】</span>开45狗准 </p>\n'
        '<p>本站暂停更新，请稍后再来</p>\n'
        '<p>301期 旧梦思维杀肖<span>【羊】</span>开17虎准 </p>\n'
        "</div>"
    )
    with pytest.raises(ParserRejection, match="数据区被非期数行打断"):
        build_registry().parse(_site("旧梦思维", JIUMENG_URL, JIUMENG_PARSER), _bundle(head, JIUMENG_URL))


# ---------------------------------------------------------------- 六合心经最专业

def _liuhe_html(rows=LIUHE_ROWS, pending: bool = True) -> str:
    head = (
        "<h3>303期:【最专业】━━━必杀一肖</h3>"
        "<table><thead><tr>"
        "<th>期数</th><th>类型</th><th>预测</th><th>开奖结果</th>"
        "</tr></thead></table>"
        '<div class="x-body">\n'
    )
    body = ""
    if pending:
        body += (
            '<p><span class="spanqi">303期</span><span class="spanti">杀1肖</span>'
            '<span class="spanyc"><i class="n">【</i>猪<i class="n">】</i></span>'
            '<span class="spankj">开??准 </span></p>\n'
        )
    for period, zodiac, draw in rows:
        body += (
            f'<p><span class="spanqi">{period}期</span><span class="spanti">杀1肖</span>'
            f'<span class="spanyc"><i class="n">【</i>{zodiac}<i class="n">】</i></span>'
            f'<span class="spankj">开{draw}准 </span></p>\n'
        )
    return f"{head}{body}</div>"


def test_liuhe_top_takes_302_with_eight_period_history() -> None:
    site = _site("六合心经最专业", LIUHE_URL, LIUHE_PARSER)
    bundle = _bundle(_liuhe_html(), LIUHE_URL)
    registry = build_registry()
    candidates = registry.parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"
    assert "table-columns:期数/类型/预测/开奖结果" in decision.candidate.evidence
    assert _window(registry, site, bundle) == LIUHE_WINDOW


def test_liuhe_missing_header_column_rejected() -> None:
    html = _liuhe_html().replace("<th>类型</th>", "")
    with pytest.raises(ParserRejection, match="表头缺少"):
        build_registry().parse(_site("六合心经最专业", LIUHE_URL, LIUHE_PARSER), _bundle(html, LIUHE_URL))


def test_liuhe_extra_row_outside_block_rejected() -> None:
    extra = (
        '<div class="y-body"><p><span class="spanqi">302期</span>'
        '<span class="spanti">杀1肖</span><span class="spanyc">【马】</span>'
        '<span class="spankj">开龙15准 </span></p></div>'
    )
    with pytest.raises(ParserRejection, match="来源不唯一|期数不是严格递减的单一列表"):
        build_registry().parse(
            _site("六合心经最专业", LIUHE_URL, LIUHE_PARSER), _bundle(_liuhe_html() + extra, LIUHE_URL)
        )


# ---------------------------------------------------------------- 配置

@pytest.mark.parametrize(
    ("name", "url", "parser_id"),
    (
        ("九五之尊", JIUWU_URL, JIUWU_PARSER),
        ("旧梦思维", JIUMENG_URL, JIUMENG_PARSER),
        ("六合心经最专业", LIUHE_URL, LIUHE_PARSER),
    ),
)
def test_registered_as_existing_site(name: str, url: str, parser_id: str) -> None:
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))
    entry = next(item for item in sites if item["name"] == name)
    assert entry["url"] == url
    assert entry["pick"] == "top"
    assert entry["section"] == SiteSection.EXISTING.value
    assert entry["parser_id"] == parser_id
    assert entry["source_policy"] == "browser"
