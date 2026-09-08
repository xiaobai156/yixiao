from __future__ import annotations

from pathlib import Path

import pytest

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
from zodiac_v2.parsers.dedicated import STRICT_ARTICLE_SPECS
from zodiac_v2.parsers.families import StrictArticleFamilyParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates


@pytest.mark.parametrize(
    ("name", "direction", "title", "author", "record", "expected"),
    [
        (
            "斩钉截铁",
            Direction.TOP,
            "235期:{斩钉截铁}日进斗金【绝杀一肖】",
            "斩钉截铁 发表于 08月23日",
            "235期:【绝杀一肖】《龙》",
            "龙",
        ),
        (
            "励精图治",
            Direction.TOP,
            "精华资料235期:内部提供【铁杀一肖】已公开信心100%",
            "励精图治 发表于 08月23日",
            "235期:铁杀一肖❁鸡鸡鸡❁",
            "鸡",
        ),
        (
            "满堂绝杀",
            Direction.BOTTOM,
            "235期:【绝杀一肖】",
            None,
            "235期杀 龙√",
            "龙",
        ),
        (
            "劬劳之恩",
            Direction.BOTTOM,
            "235期劬劳之恩→【新毙杀⒈肖】←免费公开",
            "作者：劬劳之恩",
            "235期〈劬劳之恩√毙杀⒈肖〉【鸡】",
            "鸡",
        ),
    ],
)
def test_selected_strict_articles_parse_exact_235(
    name: str,
    direction: Direction,
    title: str,
    author: str | None,
    record: str,
    expected: str,
) -> None:
    url = f"https://example.invalid/{name}"
    lines = [title]
    if author is not None:
        lines.append(author)
    lines.append(record)
    bundle = SourceBundle(
        (
            SourceDocument(
                "\n".join(lines),
                url,
                DocumentType.HTML,
                0,
                f"html:{name}",
                0,
                name,
            ),
        ),
        ("scan_complete:1",),
        scan_complete=True,
    )
    site = SiteConfig(
        name=name,
        url=url,
        direction=direction,
        section=SiteSection.NEW,
        parser_id="family.strict_article",
        source_policy="http_documents",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 235)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (235, expected)


def test_selected_strict_article_rejects_wrong_author() -> None:
    site = SiteConfig(
        name="励精图治",
        url="https://example.invalid/wrong-author",
        direction=Direction.TOP,
        section=SiteSection.NEW,
        parser_id="family.strict_article",
        source_policy="http_documents",
    )
    bundle = SourceBundle(
        (
            SourceDocument(
                "\n".join(
                    [
                        "精华资料235期:内部提供【铁杀一肖】已公开信心100%",
                        "其他作者 发表于 08月23日",
                        "235期:铁杀一肖❁鸡鸡鸡❁",
                    ]
                ),
                site.url,
                DocumentType.HTML,
                0,
                "html:wrong-author",
                0,
                "wrong-author",
            ),
        )
    )

    assert StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle) == ()


def test_selected_16_sites_are_registered_in_new_section() -> None:
    expected = {
        "斩钉截铁": Direction.TOP,
        "息息相关": Direction.BOTTOM,
        "励精图治": Direction.TOP,
        "黑旋风": Direction.TOP,
        "韶华胜极": Direction.BOTTOM,
        "壤驷鬼存": Direction.BOTTOM,
        "满堂绝杀": Direction.BOTTOM,
        "劬劳之恩": Direction.BOTTOM,
        "王木木儿涂涂": Direction.BOTTOM,
        "暴躁骨衬": Direction.TOP,
        "妮最可爱": Direction.TOP,
        "朱红山峰": Direction.TOP,
        "鼓舞木料": Direction.TOP,
        "强烈电视": Direction.TOP,
        "利尿金花": Direction.TOP,
        "困难戒指": Direction.TOP,
    }
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in expected}

    assert set(selected) == set(expected)
    assert all(site.section is SiteSection.NEW for site in selected.values())
    assert {name: site.direction for name, site in selected.items()} == expected


def test_four_236_suspected_duplicate_exceptions_are_registered() -> None:
    expected = {
        "经典推出": Direction.TOP,
        "盲风晦雨": Direction.TOP,
        "废然而反": Direction.TOP,
        "天老地荒": Direction.TOP,
    }
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in expected}

    assert set(selected) == set(expected)
    assert all(site.section is SiteSection.NEW for site in selected.values())
    assert {name: site.direction for name, site in selected.items()} == expected
    assert all(site.parser_id == "regex.86a7042b2c5a" for site in selected.values())
