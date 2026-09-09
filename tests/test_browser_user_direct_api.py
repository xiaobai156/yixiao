from __future__ import annotations

import json

from zodiac_v2.contracts import Direction, SiteConfig, SiteSection
from zodiac_v2.services.scrape import DefaultSourceGateway
from zodiac_v2.source.api import derived_user_forum_api_url
from zodiac_v2.source.http import HttpResponse


class Transport:
    def __init__(self):
        self.urls = []

    def request(self, url, *, timeout, max_bytes):
        self.urls.append(url)
        body = json.dumps(
            [{
                "id": 1,
                "status": "published",
                "user_id": 28097,
                "draw": 252,
                "topic": "绝杀一肖",
                "content": "252期（绝杀一肖) 虎虎虎",
                "user": {"id": 28097, "nickname": "清爽凯蒂"},
            }],
            ensure_ascii=False,
        ).encode()
        return HttpResponse(200, url, body, (("Content-Type", "application/json; charset=utf-8"),))


def test_fragment_user_home_derives_same_user_api():
    page = "https://example.test:12277/#/users/28097"
    assert derived_user_forum_api_url(page) == (
        "https://example.test:12277/api/v1/users/28097/forums?per_page=100"
    )


def test_browser_user_gateway_prefers_verified_same_user_http_api():
    transport = Transport()
    site = SiteConfig(
        "清爽凯蒂",
        "https://example.test:12277/#/users/28097",
        Direction.TOP,
        SiteSection.EXISTING,
        "special.user_forum_post",
        "browser_user",
    )
    bundle = DefaultSourceGateway(transport=transport).browser_user(site, 10)
    assert transport.urls == ["https://example.test:12277/api/v1/users/28097/forums?per_page=100"]
    assert bundle.scan_complete
    assert "252" in bundle.documents[0].text
