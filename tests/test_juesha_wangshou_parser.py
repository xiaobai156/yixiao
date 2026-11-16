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

_URL = "https://bizlpijd.idswv-7egq9-mcpegk.xyz:16677/topic/265088.html"
_ROOT = Path(__file__).resolve().parents[1]


def _site() -> SiteConfig:
    return SiteConfig(
        "绝杀高手",
        _URL,
        Direction.BOTTOM,
        SiteSection.NEW,
        "family.strict_article",
        "http_documents",
    )


def _bundle(*lines: str) -> SourceBundle:
    html = "<div>" + "</div><div>".join(lines) + "</div>"
    return SourceBundle(
        (SourceDocument(html, _URL, DocumentType.HTML, 0, "http:265088", 0, "265088"),),
        ("http:200", "scan_complete:1"),
        scan_complete=True,
    )


def _article(*extra: str) -> SourceBundle:
    # 真实页面按「旧→新」排列，目标期在区块末尾，故 bottom 命中的是最后一条。
    return _bundle(
        "318期:绝杀高手【精杀一肖】发财之道",
        "绝杀高手 发表于 11月14日 10:53:27",
        "316期【精杀一肖】《猴》开猪07准",
        "317期【精杀一肖】《狗》开鼠06准",
        *extra,
        "318期【精杀一肖】《龙》开0000准",
    )


def _read_site() -> dict[str, object]:
    entries = json.loads((_ROOT / "sites.json").read_text(encoding="utf-8"))
    hits = [entry for entry in entries if entry.get("name") == "绝杀高手"]
    assert len(hits) == 1, hits
    return hits[0]


def test_juesha_wangshou_uses_dedicated_strict_parser() -> None:
    """配通用正则时，广告行「318期:澳门聚宝盆→【精准杀肖】很牛逼」会被误判成 318=牛。"""
    entry = _read_site()

    assert entry["parser_id"] == "family.strict_article"
    assert entry["pick"] == "bottom"
    assert "绝杀高手" in STRICT_ARTICLE_SPECS


def test_ad_line_with_niu_does_not_create_competing_candidate() -> None:
    site = _site()
    bundle = _article("318期:澳门聚宝盆→【精准杀肖】很牛逼")

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 318)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (318, "龙")


def test_record_outside_advertising_title_only() -> None:
    """没有文章标题锚点时不得回落到广告行，必须失败。"""
    site = _site()
    bundle = _bundle(
        "318期:澳门聚宝盆→【精准杀肖】很牛逼",
        "317期【精杀一肖】《狗》开鼠06准",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)

    assert candidates == ()
