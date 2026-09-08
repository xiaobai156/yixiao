from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.services.scrape import DefaultSourceGateway
from zodiac_v2.source.http import HttpResponse

BASE = "https://a.ttss.vip/list.aspx?id=79&page={}"
DETAIL = "https://a.ttss.vip/article.aspx?id=975008"


def _page(page: int) -> str:
    period = 240 if page <= 9 else 239
    title = "百变娘子【绝杀一肖】" if page == 8 else "其他栏目"
    return (
        f'<a href="/article.aspx?id={975000 + page}">{period}期: {title}</a>'
        f'<a href="/list.aspx?id=79&page={page + 1}">下一页</a>'
    )


class _Transport:
    def __init__(self) -> None:
        self.pages: list[int] = []

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        del timeout, max_bytes
        if url == DETAIL:
            body = "240期: 百变娘子【绝杀一肖】\n【牛】".encode()
        else:
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            self.pages.append(page)
            body = _page(page).encode()
        return HttpResponse(200, url, body, (("Content-Type", "text/html; charset=utf-8"),))


def test_period_scan_stops_after_target_period_pages() -> None:
    site = SiteConfig(
        "百变娘子",
        BASE.format(1),
        Direction.TOP,
        SiteSection.EXISTING,
        "special.ttss_period_article",
        "http_period_keyword_article",
        article_keyword="百变娘子【绝杀一肖】",
    )
    first = SourceDocument(
        _page(1), site.url, DocumentType.HTML, 0, f"period-list:{site.url}", 0
    )
    transport = _Transport()

    bundle = DefaultSourceGateway(transport=transport).period_keyword_article(
        site, SourceBundle((first,)), 240, 10
    )

    assert transport.pages == list(range(2, 11))
    assert bundle.documents[0].final_url == DETAIL
