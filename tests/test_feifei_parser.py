from __future__ import annotations

import json

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import UserForumPostParser
from zodiac_v2.source.api import bind_user_forum_target
from zodiac_v2.validation.conflicts import validate_candidates

_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/#/users/85947"
_API_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/api/v1/users/85947/forums?per_page=20"


def _site() -> SiteConfig:
    return SiteConfig(
        name="请叫我菲菲",
        url=_URL,
        direction=Direction.BOTTOM,
        section=SiteSection.NEW,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=_API_URL,
    )


def _row(record_id: int, draw: int, topic_period: int, zodiac: str) -> dict[str, object]:
    content = "200杀羊√<div>223杀蛇√</div>"
    content += f"<div>{topic_period}杀{zodiac}</div>"
    return {
        "id": record_id,
        "status": "published",
        "user_id": 85947,
        "draw": draw,
        "topic": str(topic_period),
        "content": content,
        "user": {"id": 85947, "nickname": "请叫我菲菲"},
    }


def _bundle(*rows: dict[str, object]) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                json.dumps(list(rows), ensure_ascii=False),
                _API_URL,
                DocumentType.JSON,
                0,
                "api:85947",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def test_semantic_topic_period_binds_mismatched_draw_and_parses_bottom_record() -> None:
    site = _site()
    bundle = _bundle(
        _row(15801750, 225, 225, "蛇"),
        _row(15793939, 223, 224, "蛇"),
    )

    selected = bind_user_forum_target(site.url, bundle, 224)
    assert selected.documents[0].record_id == "15793939"
    assert json.loads(selected.documents[0].text)[0]["draw"] == 223

    candidates = UserForumPostParser().parse(site, selected)
    assert [(candidate.period, candidate.zodiac, candidate.record_id) for candidate in candidates] == [
        (224, "蛇", "15793939")
    ]
    decision = validate_candidates(site, selected, candidates, 224)
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (224, "蛇")
