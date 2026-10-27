from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import zodiac_v2.services.scrape as scrape_module
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


def test_browser_period_scan_opens_target_detail(monkeypatch) -> None:
    site = SiteConfig(
        "百变娘子",
        BASE.format(1),
        Direction.TOP,
        SiteSection.EXISTING,
        "special.ttss_period_article",
        "browser_period_keyword_article",
        article_keyword="百变娘子【绝杀一肖】",
    )
    detail_url = "https://a.ttss.vip/article.aspx?id=975008"
    list_bundle = SourceBundle(
        (
            SourceDocument(
                '<a href="/article.aspx?id=975008">240期: 百变娘子【绝杀一肖】</a>',
                site.url,
                DocumentType.BROWSER,
                0,
                "browser-page:list",
                0,
            ),
        )
    )
    detail_bundle = SourceBundle(
        (
            SourceDocument(
                "240期: 百变娘子【绝杀一肖】\\n【牛】",
                detail_url,
                DocumentType.BROWSER,
                0,
                "browser-page:detail",
                0,
            ),
        )
    )
    calls: list[str] = []

    def fake_browser_documents(renderer, page_url, *, timeout, **kwargs):
        del renderer, timeout, kwargs
        calls.append(page_url)
        return list_bundle if page_url == site.url else detail_bundle

    monkeypatch.setattr(scrape_module, "browser_documents", fake_browser_documents)
    bundle = DefaultSourceGateway(transport=object(), renderer=object()).browser_period_keyword_article(
        site, 240, 10
    )

    assert calls == [site.url, detail_url]
    assert bundle.documents[0].final_url == detail_url


STICKY_DETAIL = "https://a.ttss.vip/article.aspx?id=975001"


class _StickyTransport:
    """目标期条目挂在每一页（真实 a.ttss.vip 列表结构），第 16 页才出现更旧期数。"""

    def __init__(self) -> None:
        self.pages: list[int] = []

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        del timeout, max_bytes
        if url == STICKY_DETAIL:
            body = "240期: 百变娘子【绝杀一肖】\n【牛】".encode()
        else:
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            self.pages.append(page)
            period = 240 if page <= 15 else 239
            title = "百变娘子【绝杀一肖】" if page == 1 else "其他栏目"
            body = (
                f'<a href="{STICKY_DETAIL}">{period}期: {title}</a>'
                f'<a href="/list.aspx?id=79&page={page + 1}">下一页</a>'
            ).encode()
        return HttpResponse(200, url, body, (("Content-Type", "text/html; charset=utf-8"),))


def test_period_scan_survives_target_period_listed_on_every_page() -> None:
    """目标期文章铺满十几页时仍需翻到更旧期数才能证明扫描完整（旧上限 10 页会误报分页异常）。"""
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
        '<a href="/article.aspx?id=975001">240期: 百变娘子【绝杀一肖】</a>'
        '<a href="/list.aspx?id=79&page=2">下一页</a>',
        site.url,
        DocumentType.HTML,
        0,
        f"period-list:{site.url}",
        0,
    )
    transport = _StickyTransport()

    bundle = DefaultSourceGateway(transport=transport).period_keyword_article(
        site, SourceBundle((first,)), 240, 30
    )

    assert transport.pages == list(range(2, 17))
    assert bundle.documents[0].final_url == STICKY_DETAIL
