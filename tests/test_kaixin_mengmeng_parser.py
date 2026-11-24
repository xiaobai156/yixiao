"""开心蒙蒙（327 期修复）回归：年度双循环里旧年 327 期不得参与 top 竞争。"""

from __future__ import annotations

import json
from pathlib import Path

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import STRICT_ARTICLE_SPECS
from zodiac_v2.parsers.families import StrictArticleFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates

_URL = "https://gprakaak.9gr47-3du2a-erzanc.work:17477/topic/457925.html"
_ROOT = Path(__file__).resolve().parents[1]


def _site() -> SiteConfig:
    return SiteConfig(
        "开心蒙蒙",
        _URL,
        Direction.TOP,
        SiteSection.EXISTING,
        "family.strict_article",
        "browser",
    )


def _bundle(*lines: str) -> SourceBundle:
    html = "<div>" + "</div><div>".join(lines) + "</div>"
    return SourceBundle(
        (SourceDocument(html, _URL, DocumentType.HTML, 0, "http:457925", 0, "457925"),),
        ("http:200", "scan_complete:1"),
        scan_complete=True,
    )


def _article() -> SourceBundle:
    """真实页面：当期年度区块 327→001，紧接旧年区块 365→327；旧年 327 是「鼠鼠」。"""

    return _bundle(
        "高手帖子 327期九肖10码【大力杀一肖】高手发布",
        "开心蒙蒙 发表于 11月23日 09:58:42",
        "327期：【大力杀一肖】《虎虎》开？00准",
        "326期：【大力杀一肖】《鼠鼠》开猴23准",
        "325期：【大力杀一肖】《羊羊》开龙03准",
        "003期：【大力杀一肖】《龙龙》开猴47准",
        "002期：【大力杀一肖】《蛇蛇》开鼠07准",
        "001期：【大力杀一肖】《猴猴》开虎41准",
        "365期：【大力杀一肖】《狗狗》开龙26准",
        "328期：【大力杀一肖】《羊羊》开兔03准",
        "327期：【大力杀一肖】《鼠鼠》开蛇37准",
    )


def _read_site() -> dict[str, object]:
    entries = json.loads((_ROOT / "sites.json").read_text(encoding="utf-8"))
    hits = [entry for entry in entries if entry.get("name") == "开心蒙蒙"]
    assert len(hits) == 1, hits
    return hits[0]


def test_kaixin_mengmeng_uses_dedicated_strict_parser() -> None:
    """配通用正则时，旧年区块的「327期《鼠鼠》」会与当期「《虎虎》」冲突成 虎/鼠。"""

    entry = _read_site()

    assert entry["parser_id"] == "family.strict_article"
    assert entry["pick"] == "top"
    assert "开心蒙蒙" in STRICT_ARTICLE_SPECS


def test_old_year_cycle_does_not_compete_with_current_period() -> None:
    site = _site()
    bundle = _article()

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 327)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (327, "虎")


def test_records_without_title_anchor_are_rejected() -> None:
    """没有「高手帖子 327期…高手发布」标题锚点时不得出候选。"""

    site = _site()
    bundle = _bundle(
        "327期：【大力杀一肖】《虎虎》开？00准",
        "326期：【大力杀一肖】《鼠鼠》开猴23准",
    )

    assert StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle) == ()
