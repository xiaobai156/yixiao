from __future__ import annotations

import json

import pytest

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import UserForumPostParser
from zodiac_v2.source.api import bind_user_forum_target
from zodiac_v2.source.http import SourceFetchError
from zodiac_v2.validation.conflicts import validate_candidates

_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/#/users/166365"
_API_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/api/v1/users/166365/forums?per_page=20"


def _site() -> SiteConfig:
    return SiteConfig(
        name="连中谎言",
        url=_URL,
        direction=Direction.BOTTOM,
        section=SiteSection.NEW,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=_API_URL,
    )


def _row(record_id: int, draw: int, topic_period: int, zodiac: str) -> dict[str, object]:
    content = "204绝杀一肖猴✔️<div>223绝杀一肖龙✔️</div>"
    content += f"<div>{topic_period}绝杀一肖{zodiac}</div>"
    return {
        "id": record_id,
        "status": "published",
        "user_id": 166365,
        "draw": draw,
        "topic": f"{topic_period} 重头来过",
        "content": content,
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }


def _bundle(*rows: dict[str, object]) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                json.dumps(list(rows), ensure_ascii=False),
                _API_URL,
                DocumentType.JSON,
                0,
                "api:166365",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def test_semantic_topic_period_binds_mismatched_draw_and_parses_bottom_record() -> None:
    site = _site()
    bundle = _bundle(
        _row(15801865, 225, 225, "马"),
        _row(15793955, 223, 224, "羊"),
        _row(15788535, 223, 223, "龙"),
    )

    selected = bind_user_forum_target(site.url, bundle, 224)
    selected_row = json.loads(selected.documents[0].text)[0]
    assert selected.documents[0].record_id == "15793955"
    assert selected_row["draw"] == 223
    assert selected_row["topic"] == "224 重头来过"

    candidates = UserForumPostParser().parse(site, selected)
    assert [(candidate.period, candidate.zodiac, candidate.record_id) for candidate in candidates] == [
        (224, "羊", "15793955")
    ]
    decision = validate_candidates(site, selected, candidates, 224)
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (224, "羊")


def test_topic_period_prevents_content_from_neighboring_post_being_selected() -> None:
    bundle = _bundle(
        _row(15801865, 225, 225, "马"),
        _row(15793955, 223, 224, "羊"),
    )

    selected = bind_user_forum_target(_site().url, bundle, 224)

    assert selected.documents[0].record_id == "15793955"


def test_duplicate_semantic_target_posts_fail_closed() -> None:
    bundle = _bundle(
        _row(15793955, 223, 224, "羊"),
        _row(15793956, 223, 224, "虎"),
    )

    with pytest.raises(SourceFetchError, match="找到多个不同的 224期帖子"):
        bind_user_forum_target(_site().url, bundle, 224)


def test_236_reference_topic_and_short_kill_record_are_supported() -> None:
    row = {
        "id": 15899999,
        "status": "published",
        "user_id": 166365,
        "draw": 236,
        "topic": "236 杀肖只能参考",
        "content": "236杀猪开",
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }
    bundle = _bundle(row)

    selected = bind_user_forum_target(_site().url, bundle, 236)
    candidates = UserForumPostParser().parse(_site(), selected)
    decision = validate_candidates(_site(), selected, candidates, 236)

    assert selected.documents[0].record_id == "15899999"
    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, "猪")


def test_305_period_suffixed_reference_topic_binds_short_record() -> None:
    """305 期帖栏目改成「305期  只能做参考的杀」，正文当期行是「305杀一肖猪」。"""
    row = {
        "id": 16308238,
        "status": "published",
        "user_id": 166365,
        "draw": 305,
        "topic": "305期  只能做参考的杀",
        "content": "304杀一肖猪✔️<div>305杀一肖猪</div>",
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }
    bundle = _bundle(row)

    selected = bind_user_forum_target(_site().url, bundle, 305)
    candidates = UserForumPostParser().parse(_site(), selected)
    decision = validate_candidates(_site(), selected, candidates, 305)

    assert selected.documents[0].record_id == "16308238"
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(305, "猪")]
    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (305, "猪")


def test_315_open_placeholder_topic_and_compact_record_are_supported() -> None:
    """315 期帖栏目改成「315期 开帖用的」，正文只有一行「315绝杀一肖鼠」。"""
    row = {
        "id": 16374103,
        "status": "published",
        "user_id": 166365,
        "draw": 315,
        "topic": "315期 开帖用的",
        "content": "315绝杀一肖鼠",
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }
    bundle = _bundle(row)

    selected = bind_user_forum_target(_site().url, bundle, 315)
    candidates = UserForumPostParser().parse(_site(), selected)
    decision = validate_candidates(_site(), selected, candidates, 315)

    assert selected.documents[0].record_id == "16374103"
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(315, "鼠")]
    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (315, "鼠")


def test_327_new_topic_and_period_suffixed_kill_record_are_supported() -> None:
    """327 期帖栏目改成「327   回归一下，点赞起来」，正文写成「327期杀猴」。"""
    row = {
        "id": 16459424,
        "status": "published",
        "user_id": 166365,
        "draw": 327,
        "topic": "327   回归一下，点赞起来",
        "content": "327期杀猴<br>开贴用的",
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }
    bundle = _bundle(row)

    selected = bind_user_forum_target(_site().url, bundle, 327)
    candidates = UserForumPostParser().parse(_site(), selected)
    decision = validate_candidates(_site(), selected, candidates, 327)

    assert selected.documents[0].record_id == "16459424"
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(327, "猴")]
    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (327, "猴")


def test_328_topic_and_body_with_previous_period_line_are_supported() -> None:
    """328 期帖栏目是「328   一切以评论区为主」，正文同时含 327 与 328 两行，只取 328。"""
    row = {
        "id": 16459848,
        "status": "published",
        "user_id": 166365,
        "draw": 328,
        "topic": "328   一切以评论区为主",
        "content": "327期杀猴✔️&nbsp; &nbsp; &nbsp;一肖特狗✔️<div>328期杀狗<br><div>开贴用的</div></div>",
        "user": {"id": 166365, "nickname": "杨家男孩"},
    }
    bundle = _bundle(row)

    selected = bind_user_forum_target(_site().url, bundle, 328)
    candidates = UserForumPostParser().parse(_site(), selected)
    decision = validate_candidates(_site(), selected, candidates, 328)

    assert selected.documents[0].record_id == "16459848"
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(328, "狗")]
    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (328, "狗")
