"""寒武忌 281 期换格式回归：站方把 280 起写成 `NNN期〖殺X〗`（此前为 `〖期NNN〗殺X` / `NNN期：殺X`）。"""

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
from zodiac_v2.validation.conflicts import validate_candidates

HOST = "https://uuizld.ytv5j-jva78-vglwnj.work"
USER_ID = 180502


def _site(direction: Direction = Direction.BOTTOM) -> SiteConfig:
    return SiteConfig(
        name="寒武忌",
        url=f"{HOST}/#/users/{USER_ID}",
        direction=direction,
        section=SiteSection.NEW,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=f"{HOST}/api/v1/users/{USER_ID}/forums?per_page=20",
    )


def _bundle(*rows: dict[str, object]) -> SourceBundle:
    api_url = f"{HOST}/api/v1/users/{USER_ID}/forums?per_page=20"
    return SourceBundle(
        (
            SourceDocument(
                json.dumps(list(rows), ensure_ascii=False),
                api_url,
                DocumentType.JSON,
                0,
                f"api:{USER_ID}",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def _row(*, record_id: int, draw: int, topic: str, content: str) -> dict[str, object]:
    return {
        "id": record_id,
        "status": "published",
        "user_id": USER_ID,
        "draw": draw,
        "topic": topic,
        "content": content,
        "user": {"id": USER_ID, "nickname": "寒武忌"},
    }


def test_hanwuji_accepts_period_before_double_bracket_records() -> None:
    row = _row(
        record_id=16153903,
        draw=281,
        topic="281 澳门风云",
        content=(
            "268期〖殺雞〗√<div>269期〖殺龍〗√</div><div>270期〖殺狗〗√</div>"
            "<div>279期〖殺狗〗√</div><div>280期〖殺兔〗√</div><div>281期〖殺鼠〗</div>"
        ),
    )
    site = _site()
    bundle = _bundle(row)

    parser = UserForumPostParser()
    selected = parser.select_source(site, bundle, 281)
    assert selected is not None
    decision = validate_candidates(site, selected, parser.parse(site, selected), 281)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (281, "鼠")


def test_hanwuji_still_accepts_previous_period_first_style() -> None:
    row = _row(
        record_id=16147459,
        draw=280,
        topic="280 澳门风云",
        content="〖期279〗殺狗√〖0000〗<div>280期：殺兔√ &lt;&gt; 0000</div>",
    )
    site = _site()
    bundle = _bundle(row)

    parser = UserForumPostParser()
    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 280)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (280, "兔")
