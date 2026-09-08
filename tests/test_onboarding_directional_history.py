from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    ScrapeResult,
    SiteConfig,
    SiteSection,
    SourceDocument,
)
from zodiac_v2.parsers.registry import ParserRegistry
from zodiac_v2.services.scrape import ScrapeService


class _TwoCycleParser:
    def parse(self, site, bundle):
        document = bundle.documents[0]
        values = ((240, "龙", 1, 0), (239, "羊", 2, 0), (240, "蛇", 3, 1), (239, "虎", 4, 1))
        return tuple(
            Candidate(
                period,
                zodiac,
                f"{period}期【绝杀一肖】【{zodiac}】",
                document.source_id,
                line,
                (
                    "anchor:测试栏目",
                    "anchor-line:0",
                    "block-range:0-5",
                    f"record-cycle:{cycle}",
                    "record-offset:0",
                ),
                record_id=document.record_id,
            )
            for period, zodiac, line, cycle in values
        )


class _LeftHistoryParser:
    def parse(self, site, bundle):
        document = bundle.documents[0]
        values = ((241, "牛"), (240, "龙"))
        if site.direction is not Direction.LEFT:
            values = values[:1]
        return tuple(
            Candidate(
                period,
                zodiac,
                f"{period}{'起' if period == 240 else '期'}：杀{zodiac}",
                document.source_id,
                index,
                ("section:杀一肖", "record-cycle:1", "block-range:0-3"),
                record_id=document.record_id,
            )
            for index, (period, zodiac) in enumerate(values, start=1)
        )


def test_onboarding_history_keeps_the_live_top_cycle() -> None:
    site = SiteConfig(
        "测试站",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        "test.two_cycles",
        "http_documents",
    )
    document = SourceDocument(
        "测试栏目\n240期【绝杀一肖】【龙】\n239期【绝杀一肖】【羊】\n"
        "240期【绝杀一肖】【蛇】\n239期【绝杀一肖】【虎】",
        site.url,
        DocumentType.HTML,
        0,
        "html:test",
        0,
        "1",
    )
    candidates = _TwoCycleParser().parse(site, type("Bundle", (), {"documents": (document,)})())
    live = ScrapeResult.success(site, 240, candidates[0], (document,), writable=False)
    service = ScrapeService(None, ParserRegistry(((site.parser_id, _TwoCycleParser()),)))

    results = service.historical_results(site, (240, 239), live)

    assert [result.candidate.zodiac for result in results if result.candidate] == ["龙", "羊"]


def test_history_parser_receives_left_direction() -> None:
    site = SiteConfig(
        "测试站",
        "https://example.test/users/1",
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "test.left_history",
        "api_then_http",
    )
    document = SourceDocument(
        "杀一肖\n241期：杀牛\n240起：杀龙",
        site.url,
        DocumentType.HTML,
        0,
        "json:test",
        0,
        "1",
    )
    parser = _LeftHistoryParser()
    live_candidate = parser.parse(site, type("Bundle", (), {"documents": (document,)})())[0]
    live = ScrapeResult.success(site, 241, live_candidate, (document,), writable=False)
    service = ScrapeService(None, ParserRegistry(((site.parser_id, parser),)))

    result = service.historical_results(site, (240,), live)[0]

    assert result.ok
    assert result.candidate is not None
    assert result.candidate.zodiac == "龙"
