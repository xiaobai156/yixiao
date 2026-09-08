from __future__ import annotations

import pytest

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import ArContentVariantParser

_URL = "https://4.48kk49.com:1888/Article/ar_content/id/164/tid/6.html"


def _site(name: str, keyword: str) -> SiteConfig:
    return SiteConfig(
        name=name,
        url=_URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.ar_content_variant_article",
        source_policy="http_documents",
        article_keyword=keyword,
    )


def _bundle(title: str, field: str) -> SourceBundle:
    document = SourceDocument(
        "\n".join(
            (
                title,
                f"225期 {field} :【兔】 开 ?? 准",
                f"224期 {field} :【牛】 开 09,狗 准",
                f"223期 {field} :【马】 开 23,猴 准",
                "上一篇：225期: 其他栏目",
            )
        ),
        _URL,
        DocumentType.HTML,
        0,
        f"html:{_URL}",
        0,
        "164",
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def test_variant_parser_accepts_single_zodiac_title_with物_semantic() -> None:
    site = _site("鬼谷子必中", "鬼谷子必中")
    bundle = _bundle(
        "225期: ≡◤〖鬼谷子必中〗◥≡【精准绝杀①物】→已公开",
        "鬼谷子信息中心杀1肖",
    )

    candidates = ArContentVariantParser().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "兔"),
        (224, "牛"),
        (223, "马"),
    ]
    assert all("title-semantic:鬼谷子必中" in candidate.evidence for candidate in candidates)
    assert all("record-field:鬼谷子信息中心杀1肖" in candidate.evidence for candidate in candidates)


@pytest.mark.parametrize(
    ("name", "keyword", "title", "field"),
    (
        ("满堂红", "满㊣堂㊣红", "225期: 满㊣堂㊣红◤福臨門踩死一肖◥100%准", "福臨門踩死①生肖"),
        ("精选供料", "九龙禁肖", "225期: 精选供参料╬◤九龙禁肖无错记录◥已更新", "九龙禁生肖"),
        ("百大姐每期", "百大姐杀肖", "225期: 镇坛之宝‖≡『百大姐杀肖』≡‖免费料", "百大姐每期《绝杀》全年错五"),
        ("蓝月亮", "蓝月亮", "225期: 蓝月亮【九宫禁动物期期准】已免费公开", "九宫禁动物"),
        ("鬼5洞人", "鬼谷洞人", "225期: 鬼5洞人◆◆==绝杀一肖==◆◆==三行==◆◆!【鬼谷洞人】", "鬼谷洞人绝杀(一肖)"),
        ("黄大仙救世网", "黄大仙㊣救世网", "225期: 黄大仙㊣救世网(稳禁一肖)已公开", "禁"),
    ),
)
def test_variant_parser_uses_real_semantic_anchor(
    name: str,
    keyword: str,
    title: str,
    field: str,
) -> None:
    site = _site(name, keyword)
    candidates = ArContentVariantParser().parse(site, _bundle(title, field))

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "兔"),
        (224, "牛"),
        (223, "马"),
    ]


def test_variant_parser_does_not_generalize_to_unknown_or_multi_value_site() -> None:
    site = _site("博发世家", "博发世家")
    bundle = _bundle(
        "225期: 博发世家㊣【期期信心9肖王】准!",
        "博发原创九肖",
    )

    assert ArContentVariantParser().parse(site, bundle) == ()
