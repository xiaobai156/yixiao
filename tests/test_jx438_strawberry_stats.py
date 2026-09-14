from __future__ import annotations

import json

import pytest

from zodiac_v2.config import ConfigError, load_sites
from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    RunMode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.services.scrape import DefaultSourceGateway, ScrapeService
from zodiac_v2.source.documents import discover_named_stat_links
from zodiac_v2.source.http import HttpResponse, SourceFetchError
from zodiac_v2.validation.conflicts import validate_candidates
from zodiac_v2.validation.evidence import validate_candidate_evidence

HOME_URL = "https://www.jx438.com/index.php?fid=3"
DETAIL_URL = "https://www.jx438.com/read.php?tid=13805613"

HOME_HTML = (
    '<ul><li class="xxqgsb"><a class="subject_text" href="read.php?tid=13805613">'
    "&#127827;256期上错统计</a><span class=\"author\">【草莓菇凉】</span>"
    '<a class="record" href="txs.php?authorid=1260">(认证记录)</a></li></ul>'
)

DETAIL_HTML = (
    "<div>新澳门256期</div>"
    "<div>六助上错九肖统计</div>"
    "<div>快乐佳佳:马-蛇-羊-鸡-猴-虎-龙-狗-猪★★★</div>"
    "<div>西门西门:鸡-鼠-蛇-羊-猴-龙-兔-马-牛★★</div>"
    "<div>统计结果：</div>"
    "<div>〖5次〗:蛇,（共1个）</div>"
    "<div>〖6次〗:虎,猪,（共2个）</div>"
    "<div>〖10次〗:猴,（共1个）</div>"
    "<div>🍓🍓🍓</div>"
    "<div>新澳门256期</div>"
    "<div>上错杀五码统计</div>"
    "<div>〖0次〗:01,02,（共2个）</div>"
)


def _site() -> SiteConfig:
    return SiteConfig(
        name="草莓菇凉",
        url=HOME_URL,
        direction=Direction.TOP,
        section=SiteSection.NEW,
        parser_id="special.jx438_strawberry_stats",
        source_policy="http_named_stat_article",
        article_keyword="草莓菇凉",
    )


class _Transport:
    def __init__(self, home: str = HOME_HTML, detail: str = DETAIL_HTML) -> None:
        self.home = home
        self.detail = detail

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        del timeout, max_bytes
        if url == HOME_URL:
            return HttpResponse(200, url, self.home.encode(), (("Content-Type", "text/html; charset=utf-8"),))
        if url == DETAIL_URL:
            return HttpResponse(200, url, self.detail.encode(), (("Content-Type", "text/html; charset=utf-8"),))
        raise AssertionError(f"unexpected request: {url}")


def _detail_bundle(detail: str = DETAIL_HTML) -> SourceBundle:
    home_doc = SourceDocument(HOME_HTML, HOME_URL, DocumentType.HTML, 0, "home", 0)
    detail_doc = SourceDocument(detail, DETAIL_URL, DocumentType.HTML, 0, "detail", 1, "13805613")
    return SourceBundle((home_doc, detail_doc), ("named-stat:200:256", "scan_complete:1"), scan_complete=True)


def test_discover_named_stat_links_binds_period_and_author() -> None:
    links = discover_named_stat_links(HOME_HTML, HOME_URL, "草莓菇凉")

    assert links == ((256, DETAIL_URL),)
    assert discover_named_stat_links(HOME_HTML.replace("【草莓菇凉】", "【别人】"), HOME_URL, "草莓菇凉") == ()


def test_discover_named_stat_links_rejects_cross_origin_row() -> None:
    foreign = HOME_HTML.replace('href="read.php?tid=13805613"', 'href="https://evil.test/read.php?tid=1"')
    assert discover_named_stat_links(foreign, HOME_URL, "草莓菇凉") == ()


def test_gateway_two_hop_requires_unique_target_period_row() -> None:
    gateway = DefaultSourceGateway(_Transport())
    site = _site()
    home_bundle = gateway.http(site, 5)

    bundle = gateway.named_stat_article(site, home_bundle, 256, 5)

    assert [document.final_url for document in bundle.documents] == [HOME_URL, DETAIL_URL]
    assert bundle.scan_complete
    assert bundle.diagnostics[0] == "named-stat:200:256"
    assert bundle.documents[1].record_id == "13805613"

    with pytest.raises(SourceFetchError, match="首页统计行期数 256 不等于目标 255期"):
        gateway.named_stat_article(site, home_bundle, 255, 5)


def test_gateway_rejects_multiple_stat_rows() -> None:
    doubled = HOME_HTML.replace("</li></ul>", "</li><li><a href=\"read.php?tid=1\">🍓255期上错统计</a><span class=\"author\">【草莓菇凉】</span></li></ul>")
    gateway = DefaultSourceGateway(_Transport(home=doubled))
    site = _site()
    home_bundle = gateway.http(site, 5)

    with pytest.raises(SourceFetchError, match="命中 2 个"):
        gateway.named_stat_article(site, home_bundle, 256, 5)


def test_config_requires_article_keyword_for_named_stat_policy(tmp_path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "草莓菇凉",
                    "pick": "top",
                    "url": HOME_URL,
                    "section": "新增的站点",
                    "parser_id": "special.jx438_strawberry_stats",
                    "source_policy": "http_named_stat_article",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="article_keyword"):
        load_sites(path, parser_ids=build_registry().parser_ids, source_policies={"http_named_stat_article"})


def test_parser_emits_unique_least_hit_zodiac() -> None:
    site = _site()
    bundle = _detail_bundle()

    candidates = build_registry().parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(256, "蛇")]
    decision = validate_candidate_evidence(candidates[0], bundle)
    assert decision.ok
    assert "stat-count:5" in candidates[0].evidence
    assert "title-period:256" in candidates[0].evidence


def test_parser_selects_minimum_across_all_stat_rows() -> None:
    site = _site()
    detail = (
        "<div>新澳门256期</div>"
        "<div>六助上错九肖统计</div>"
        "<div>统计结果：</div>"
        "<div>〖9次〗:牛,兔,鸡,（共3个）</div>"
        "<div>〖10次〗:猴,（共1个）</div>"
        "<div>〖5次〗:蛇,（共1个）</div>"
        "<div>🍓🍓🍓</div>"
    )
    candidates = build_registry().parse(site, _detail_bundle(detail))

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(256, "蛇")]


def test_parser_skips_block_when_minimum_is_ambiguous() -> None:
    site = _site()
    detail = (
        "<div>新澳门256期</div>"
        "<div>六助上错九肖统计</div>"
        "<div>统计结果：</div>"
        "<div>〖5次〗:蛇,（共1个）</div>"
        "<div>〖5次〗:牛,（共1个）</div>"
        "<div>〖8次〗:羊,（共1个）</div>"
        "<div>🍓🍓🍓</div>"
    )

    assert build_registry().parse(site, _detail_bundle(detail)) == ()


def test_parser_requires_strawberry_column_anchor() -> None:
    site = _site()
    detail = (
        "<div>新澳门256期</div>"
        "<div>上错杀五码统计</div>"
        "<div>统计结果：</div>"
        "<div>〖5次〗:蛇,（共1个）</div>"
        "<div>🍓🍓🍓</div>"
    )

    assert build_registry().parse(site, _detail_bundle(detail)) == ()


def test_parser_ignores_old_macau_heading() -> None:
    site = _site()
    detail = (
        "<div>旧澳门256期</div>"
        "<div>六助上错九肖统计</div>"
        "<div>统计结果：</div>"
        "<div>〖5次〗:蛇,（共1个）</div>"
        "<div>🍓🍓🍓</div>"
    )

    assert build_registry().parse(site, _detail_bundle(detail)) == ()


def test_direction_validation_selects_the_single_candidate() -> None:
    site = _site()
    bundle = _detail_bundle()
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 256)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (256, "蛇")
    assert not validate_candidates(site, bundle, candidates, 255).ok
    assert not validate_candidates(site, bundle, candidates, 257).ok


def test_title_period_binding_accepts_block_bound_record() -> None:
    document = SourceDocument(
        "新澳门256期\n六助上错九肖统计\n〖5次〗:蛇,（共1个）",
        "https://example.test/detail",
        DocumentType.HTML,
        0,
        "doc",
        0,
        "1",
    )
    candidate = Candidate(
        256,
        "蛇",
        "〖5次〗:蛇,（共1个）",
        "doc",
        2,
        (
            "title-text:新澳门256期",
            "title-period:256",
            "title-line:0",
            "section-range:0-3",
        ),
        record_id="1",
    )

    assert validate_candidate_evidence(candidate, SourceBundle((document,))).ok


def test_title_period_binding_requires_matching_period() -> None:
    document = SourceDocument(
        "新澳门256期\n六助上错九肖统计\n〖5次〗:蛇,（共1个）",
        "https://example.test/detail",
        DocumentType.HTML,
        0,
        "doc",
        0,
        "1",
    )
    candidate = Candidate(
        256,
        "蛇",
        "〖5次〗:蛇,（共1个）",
        "doc",
        2,
        (
            "title-text:新澳门256期",
            "title-period:255",
            "title-line:0",
            "section-range:0-3",
        ),
        record_id="1",
    )

    decision = validate_candidate_evidence(candidate, SourceBundle((document,)))
    assert decision.failure_code is FailureCode.FIELD


def test_title_period_binding_requires_common_range() -> None:
    document = SourceDocument(
        "新澳门256期\n六助上错九肖统计\n〖5次〗:蛇,（共1个）",
        "https://example.test/detail",
        DocumentType.HTML,
        0,
        "doc",
        0,
        "1",
    )
    candidate = Candidate(
        256,
        "蛇",
        "〖5次〗:蛇,（共1个）",
        "doc",
        2,
        (
            "title-text:新澳门256期",
            "title-period:256",
            "title-line:0",
            "section-range:2-3",
        ),
        record_id="1",
    )

    decision = validate_candidate_evidence(candidate, SourceBundle((document,)))
    assert decision.failure_code is FailureCode.FIELD


def test_plain_candidates_still_require_period_in_raw_line() -> None:
    document = SourceDocument(
        "新澳门256期\n六助上错九肖统计\n〖5次〗:蛇,（共1个）",
        "https://example.test/detail",
        DocumentType.HTML,
        0,
        "doc",
        0,
        "1",
    )
    candidate = Candidate(
        256,
        "蛇",
        "〖5次〗:蛇,（共1个）",
        "doc",
        2,
        ("section:新澳门256期", "block-range:0-3"),
        record_id="1",
    )

    decision = validate_candidate_evidence(candidate, SourceBundle((document,)))
    assert decision.failure_code is FailureCode.FIELD


def test_end_to_end_formal_single_issues_validator_success() -> None:
    site = _site()
    service = ScrapeService(DefaultSourceGateway(_Transport()), build_registry())

    result = service.scrape_site(site, 256, RunMode.FORMAL_SINGLE, timeout=5)

    assert result.ok and result.validator_issued
    assert result.candidate is not None
    assert (result.candidate.period, result.candidate.zodiac) == (256, "蛇")
    assert result.candidate.record_id == "13805613"

    missing = service.scrape_site(site, 255, RunMode.READ_ONLY, timeout=5)
    assert not missing.ok
    assert missing.failure_code is FailureCode.SOURCE_IDENTITY
