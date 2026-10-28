# -*- coding: utf-8 -*-
"""301 期救站回归：栏目改名、当期省「杀」字、同页两段递减列表。"""
from __future__ import annotations

import json

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import UserForumPostParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates

_HOST = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz"


def _user_site(name: str, user_id: int, direction: Direction) -> SiteConfig:
    return SiteConfig(
        name=name,
        url=f"{_HOST}/#/users/{user_id}",
        direction=direction,
        section=SiteSection.NEW,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=f"{_HOST}/api/v1/users/{user_id}/forums?per_page=20",
    )


def _user_bundle(user_id: int, row: dict[str, object]) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                json.dumps([row], ensure_ascii=False),
                f"{_HOST}/api/v1/users/{user_id}/forums?per_page=20",
                DocumentType.JSON,
                0,
                f"api:{user_id}",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def _user_row(user_id: int, name: str, topic: str, content: str) -> dict[str, object]:
    return {
        "id": 16285183,
        "status": "published",
        "user_id": user_id,
        "draw": 301,
        "topic": topic,
        "content": content,
        "user": {"id": user_id, "nickname": name},
    }


def test_nizuikeai_accepts_renamed_topic() -> None:
    """站方把栏目名从「大吉大利」改成「招财进宝」，301 期取值必须照常取到。"""
    site = _user_site("妮最可爱", 231014, Direction.TOP)
    row = _user_row(
        231014,
        "妮最可爱",
        "招财进宝",
        "301期♥绝杀一肖——狗——？ 300期♥绝杀一肖——鸡——✓（蛇）（38）",
    )
    bundle = _user_bundle(231014, row)
    decision = validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 301)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "狗"


def test_junshao_accepts_current_post_without_kill_word() -> None:
    """俊少当期那行写作「301.猴」，省了「杀」字，仍要取到 301=猴。"""
    site = _user_site("俊少", 133911, Direction.BOTTOM)
    row = _user_row(
        133911,
        "俊少",
        "绝杀一肖",
        "299.杀马准\n300.杀马准\n301.猴\n理性参考，谨慎谨慎！！！",
    )
    bundle = _user_bundle(133911, row)
    decision = validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 301)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猴"


def _page_bundle(text: str) -> SourceBundle:
    url = "https://example.test/topic/255727.html"
    return SourceBundle(
        (SourceDocument(text, url, DocumentType.HTML, 0, f"html:{url}", 0, None),),
        ("http:200", "scan_complete:1"),
        scan_complete=True,
    )


def test_shangyi_two_descending_lists_pick_first_for_top() -> None:
    """同一篇文章里「今年 301→…」后面接「去年 306→…」，top 必须取当年那段。"""
    site = SiteConfig(
        "伤夷折衄",
        "https://example.test/topic/255727.html",
        Direction.TOP,
        SiteSection.NEW,
        "regex.fc1ff5a3d08c",
        "http_documents",
    )
    text = "\n".join(
        [
            "湖南资料高手版3301期:【伤夷折衄☆绝杀一肖】",
            "301期:【绝杀一肖】【蛇】开:？00准",
            "300期:【绝杀一肖】【鸡】开:蛇38准",
            "306期:【绝杀一肖】【鼠】开:牛17准",
            "305期:【绝杀一肖】【蛇】开:鼠42准",
            "301期:【绝杀一肖】【马】开:牛05准",
        ]
    )
    bundle = _page_bundle(text)
    candidates = build_registry().parse(site, bundle)
    assert any("record-cycle:0" in item.evidence for item in candidates)
    decision = validate_candidates(site, bundle, candidates, 301)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "蛇"
