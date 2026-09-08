from __future__ import annotations

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import ArContentPeriodArticleParser
from zodiac_v2.validation.conflicts import validate_candidates

_BLUE_URL = "https://4.48kk49.com:1888/Article/ar_content/id/1539/tid/82.html"
_PINK_URL = "https://4.48kk49.com:1888/Article/ar_content/id/1484/tid/82.html"


def _site(name: str, url: str, *, article_keyword: str | None = None) -> SiteConfig:
    return SiteConfig(
        name=name,
        url=url,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.ar_content_period_article",
        source_policy="http_documents",
        article_keyword=article_keyword or name,
    )


def _bundle(url: str, record_id: str, title: str, field: str) -> SourceBundle:
    rows = [
        title,
        f"225期 {field} :【猴】 开 31 准",
        f"224期 {field} :【马】 开 09,狗 准",
        f"223期 {field} :【龙】 开 23,猴 准",
        "上一篇：225期: 其他栏目",
    ]
    document = SourceDocument(
        "\n".join(rows),
        url,
        DocumentType.HTML,
        0,
        f"html:{url}",
        0,
        record_id,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def test_ar_content_parser_uses_blue_semantic_title_and_field() -> None:
    site = _site("蓝大海", _BLUE_URL)
    bundle = _bundle(_BLUE_URL, "1539", "225期: 蓝大海★原创【大杀一肖】", "大杀一肖")

    candidates = ArContentPeriodArticleParser().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "猴"),
        (224, "马"),
        (223, "龙"),
    ]
    assert all(candidate.record_id == "1539" for candidate in candidates)
    assert all("title-semantic:蓝大海" in candidate.evidence for candidate in candidates)


def test_ar_content_parser_rejects_unproven_pink_name() -> None:
    site = _site("粉色棼提出", _PINK_URL)
    bundle = _bundle(_PINK_URL, "1484", "225期: 粉色棼精心选【稳杀一肖】", "稳杀一肖")

    assert ArContentPeriodArticleParser().parse(site, bundle) == ()


def test_custom_pink_name_uses_real_semantic_anchor() -> None:
    site = _site("粉色棼提出", _PINK_URL, article_keyword="粉色棼精心选")
    bundle = _bundle(_PINK_URL, "1484", "225期: 粉色棼精心选【稳杀一肖】", "稳杀一肖")

    candidates = ArContentPeriodArticleParser().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "猴"),
        (224, "马"),
        (223, "龙"),
    ]
    assert all("title-semantic:粉色棼精心选" in candidate.evidence for candidate in candidates)


def _variant_bundle(url: str, record_id: str, title: str, rows: list[str]) -> SourceBundle:
    document = SourceDocument(
        "\n".join([title, *rows, "上一篇：225期: 其他栏目"]),
        url,
        DocumentType.HTML,
        0,
        f"html:{url}",
        0,
        record_id,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def test_ar_content_parser_separates_title_field_from_record_field() -> None:
    url = "https://4.48kk49.com:1888/Article/ar_content/id/214/tid/3.html"
    site = _site("白姐最准", url)
    bundle = _variant_bundle(
        url,
        "214",
        "225期: ★白姐最准★→【期期禁一肖】←已公开",
        [
            "225期 白小姐禁一肖 :【鼠】 开 ?? 准",
            "224期 白小姐禁一肖 :【猪】 开 09,狗 准",
            "223期 白小姐禁一肖 :【牛】 开 23,猴 准",
        ],
    )

    candidates = ArContentPeriodArticleParser().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "鼠"),
        (224, "猪"),
        (223, "牛"),
    ]
    assert all("title-field:期期禁一肖" in candidate.evidence for candidate in candidates)
    assert all("record-field:白小姐禁一肖" in candidate.evidence for candidate in candidates)
    assert "record-status:incomplete" in candidates[0].evidence


def test_ar_content_parser_accepts_corner_quote_title_and_custom_anchor() -> None:
    url = "https://4.48kk49.com:1888/Article/ar_content/id/177/tid/5.html"
    site = _site(" 白小姐", url, article_keyword="白小姐杀肖")
    bundle = _variant_bundle(
        url,
        "177",
        "225期: 管家婆‖≡『白小姐杀肖』≡‖100%准",
        [
            "225期 白小姐《绝杀》全年无错 :【羊】 开 ?? 准",
            "224期 白小姐《绝杀》全年无错 :【猪】 开 09,狗 准",
            "223期 白小姐《绝杀》全年无错 :【狗】 开 23,猴 准",
        ],
    )

    candidates = ArContentPeriodArticleParser().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "羊"),
        (224, "猪"),
        (223, "狗"),
    ]
    assert all("title-semantic:白小姐杀肖" in candidate.evidence for candidate in candidates)
    assert all("record-field:白小姐《绝杀》全年无错" in candidate.evidence for candidate in candidates)


def test_incomplete_newest_row_is_usable_for_225_but_not_older_top_window() -> None:
    url = "https://4.48kk49.com:1888/Article/ar_content/id/214/tid/3.html"
    site = _site("白姐最准", url)
    bundle = _variant_bundle(
        url,
        "214",
        "225期: ★白姐最准★→【期期禁一肖】←已公开",
        [
            "225期 白小姐禁一肖 :【鼠】 开 ?? 准",
            "224期 白小姐禁一肖 :【猪】 开 09,狗 准",
            "223期 白小姐禁一肖 :【牛】 开 23,猴 准",
        ],
    )
    candidates = ArContentPeriodArticleParser().parse(site, bundle)

    current = validate_candidates(site, bundle, candidates, 225)
    previous = validate_candidates(site, bundle, candidates, 224)

    assert current.ok and current.candidate is not None
    assert current.candidate.period == 225
    assert current.candidate.zodiac == "鼠"
    assert previous.ok and previous.candidate is not None
    assert previous.candidate.period == 224
    assert previous.candidate.zodiac == "猪"
