from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import GuangdongTitleAuthorCycleParser

_PAGE_URL = "https://qmcrtk.2nbti-mbjeq-zxhgcd.work:16677/topic/440119.html"


def _site() -> SiteConfig:
    return SiteConfig(
        name="广东把而",
        url=_PAGE_URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.guangdong_title_author",
        source_policy="http_documents",
    )


def _bundle(*lines: str, document_type: DocumentType = DocumentType.SCRIPT) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text="\n".join(lines),
                final_url=_PAGE_URL,
                document_type=document_type,
                priority=0,
                source_id="guangdong-script",
                page_order=0,
                record_id="440119",
            ),
        )
    )


def test_semantic_title_does_not_depend_on_domain_or_author() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "作者：页面作者变更",
            "223期（必杀一肖）【羊】",
            "222期（必杀一肖）【马】",
            "上一篇：223期其他文章",
        ),
    )

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(223, "羊"), (222, "马")]
    assert all("field:必杀一肖" in candidate.evidence for candidate in candidates)
    assert all("title-semantic:杀掉一肖" in candidate.evidence for candidate in candidates)
    assert all(not item.startswith("title-author:") for candidate in candidates for item in candidate.evidence)


def test_same_block_boundary_excludes_records_after_navigation() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "223期（必杀一肖）【羊】",
            "222期（必杀一肖）【马】",
            "上一篇：223期其他文章",
            "223期（必杀一肖）【虎】",
        ),
    )

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(223, "羊"), (222, "马")]


def test_requires_semantic_title() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀一肖】93023d.com",
            "223期（必杀一肖）【羊】",
        ),
    )

    assert candidates == ()


def test_requires_same_block_bishayixiao_field() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "223期（杀一肖）【羊】",
            "上一篇：223期其他文章",
        ),
    )

    assert candidates == ()


def test_ambiguous_semantic_titles_fail_closed() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "222期：【杀掉一肖】另一个标题",
            "223期（必杀一肖）【羊】",
            "222期（必杀一肖）【马】",
        ),
    )

    assert candidates == ()


def test_ignores_non_script_documents() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "223期（必杀一肖）【羊】",
            document_type=DocumentType.HTML,
        ),
    )

    assert candidates == ()


def test_stops_cycle_at_a_period_gap() -> None:
    candidates = GuangdongTitleAuthorCycleParser().parse(
        _site(),
        _bundle(
            "223期：【杀掉一肖】93023d.com",
            "223期（必杀一肖）【羊】",
            "221期（必杀一肖）【猴】",
        ),
    )

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(223, "羊")]
