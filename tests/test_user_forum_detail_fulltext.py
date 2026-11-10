from __future__ import annotations

import json

import pytest

from zodiac_v2.contracts import Direction, SiteConfig, SiteSection
from zodiac_v2.services.scrape import DefaultSourceGateway
from zodiac_v2.source.api import bind_user_forum_target
from zodiac_v2.source.http import HttpResponse, SourceFetchCode, SourceFetchError

LIST_URL = "https://example.test:16677/api/v1/users/133911/forums?per_page=20"
DETAIL_URL = "https://example.test:16677/api/v1/forums/16366439"
PAGE_URL = "https://example.test:16677/#/users/133911"


def _row(content: str, *, draw: int = 314, user_id: int = 133911) -> dict:
    return {
        "id": 16366439,
        "status": "published",
        "user_id": user_id,
        "draw": draw,
        "topic": "绝杀一肖",
        "content": content,
        "user": {"id": user_id, "nickname": "俊少"},
    }


class DetailTransport:
    """列表接口只回头 3 行摘要，详情接口才有完整正文。"""

    def __init__(self, *, detail_row: dict | None = None, detail_status: int = 200):
        self.urls: list[str] = []
        self.detail_row = detail_row if detail_row is not None else _row(
            "313.杀鸡准<div>314.杀鼠</div>"
        )
        self.detail_status = detail_status

    def request(self, url, *, timeout, max_bytes):
        self.urls.append(url)
        if url.startswith(DETAIL_URL):
            if self.detail_status != 200:
                body = json.dumps({"message": "not found"}).encode()
                return HttpResponse(self.detail_status, url, body, (("Content-Type", "application/json"),))
            body = json.dumps(self.detail_row, ensure_ascii=False).encode()
            return HttpResponse(200, url, body, (("Content-Type", "application/json; charset=utf-8"),))
        payload = [_row("233.杀猪准<br>234.杀鼠准<br>235.杀龙准")]
        body = json.dumps(payload, ensure_ascii=False).encode()
        return HttpResponse(200, url, body, (("Content-Type", "application/json; charset=utf-8"),))


def _site() -> SiteConfig:
    return SiteConfig(
        "俊少",
        PAGE_URL,
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.user_forum_post",
        "browser_user",
    )


def _list_bundle(transport: DetailTransport):
    return DefaultSourceGateway(transport=transport).browser_user(_site(), 10)


def test_list_api_summary_alone_hides_target_period_line():
    transport = DetailTransport()
    bundle = _list_bundle(transport)
    assert "314.杀鼠" not in bundle.documents[0].text


def test_bind_fetches_detail_endpoint_for_full_body():
    transport = DetailTransport()
    bundle = _list_bundle(transport)
    selected = bind_user_forum_target(
        _site().url,
        bundle,
        314,
        transport=transport,
    )
    text = selected.documents[0].text
    assert "314.杀鼠" in text
    assert "user-forum-detail:200" in selected.diagnostics
    assert "user-forum-detail-record:16366439" in selected.diagnostics
    assert transport.urls[-1] == DETAIL_URL


def test_bind_rejects_detail_belonging_to_other_user():
    transport = DetailTransport(detail_row=_row("314.杀鼠", user_id=999))
    bundle = _list_bundle(transport)
    with pytest.raises(SourceFetchError) as excinfo:
        bind_user_forum_target(_site().url, bundle, 314, transport=transport)
    assert excinfo.value.code is SourceFetchCode.SOURCE_IDENTITY


def test_bind_rejects_detail_with_other_period():
    transport = DetailTransport(detail_row=_row("313.杀鼠", draw=313))
    bundle = _list_bundle(transport)
    with pytest.raises(SourceFetchError) as excinfo:
        bind_user_forum_target(_site().url, bundle, 314, transport=transport)
    assert excinfo.value.code is SourceFetchCode.SOURCE_IDENTITY


def test_bind_reports_missing_detail_endpoint():
    transport = DetailTransport(detail_status=404)
    bundle = _list_bundle(transport)
    with pytest.raises(SourceFetchError) as excinfo:
        bind_user_forum_target(_site().url, bundle, 314, transport=transport)
    assert excinfo.value.code is SourceFetchCode.HTTP_STATUS


def test_bind_without_transport_keeps_list_content():
    transport = DetailTransport()
    bundle = _list_bundle(transport)
    selected = bind_user_forum_target(_site().url, bundle, 314)
    assert "user-forum-detail" not in " ".join(selected.diagnostics)
    assert "233.杀猪准" in selected.documents[0].text
