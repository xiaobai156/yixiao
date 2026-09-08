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
from zodiac_v2.validation.conflicts import validate_candidates


def _hanwu(content: str, *, topic: str = "246 澳门风云", user_id: int = 180502):
    api_url = "https://example.test/api/v1/users/180502/forums?per_page=20"
    site = SiteConfig(
        "寒武忌",
        "https://example.test/#/users/180502",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.user_forum_post",
        "api_then_http",
        api_url=api_url,
    )
    row = {
        "id": 15939443,
        "status": "published",
        "user_id": user_id,
        "draw": 246,
        "topic": topic,
        "content": content,
        "user": {"id": 180502, "nickname": "寒武忌"},
    }
    document = SourceDocument(
        json.dumps([row], ensure_ascii=False),
        api_url,
        DocumentType.JSON,
        0,
        "user:180502:record:15939443",
        0,
        "15939443",
    )
    return site, SourceBundle((document,), (), scan_complete=True)


def _decision(content: str, **kwargs):
    site, bundle = _hanwu(content, **kwargs)
    return validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 246)


def test_hanwu_246_colon_format_is_the_bottom_candidate():
    decision = _decision("245期:杀鼠✦特:18牛 ✓<div>246期:杀龙✦特:？00</div>")
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"


def test_hanwu_246_rejects_wrong_identity_topic_field_conflict_and_direction():
    assert not _decision("246期:杀龙✦特:？00", user_id=99).ok
    assert not _decision("246期:杀龙✦特:？00", topic="246 推荐一肖").ok
    assert not _decision("246期:推荐龙✦特:？00").ok
    assert not _decision("246期:杀龙✦特:？00<div>246期:杀羊✦特:？00</div>").ok
    assert not _decision("246期:杀龙✦特:？00<div>247期:杀羊✦特:？00</div>").ok


def test_hanwu_246_rejects_adjacent_and_missing_periods():
    site, bundle = _hanwu("245期:杀鼠✦特:18牛 ✓<div>246期:杀龙✦特:？00</div>")
    candidates = UserForumPostParser().parse(site, bundle)
    assert not validate_candidates(site, bundle, candidates, 245).ok
    assert not validate_candidates(site, bundle, candidates, 247).ok
