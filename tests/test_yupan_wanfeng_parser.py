"""预判晚风（用户 207650）双肖回归：322 期栏目改成「绝杀二肖」，按用户授权只取第一个生肖。"""
from __future__ import annotations

import json
from pathlib import Path

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

_HOST = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
_ROOT = Path(__file__).resolve().parents[1]
_USER_ID = 207650


def _site(direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(
        name="预判晚风",
        url=f"{_HOST}/#/users/{_USER_ID}",
        direction=direction,
        section=SiteSection.EXISTING,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=f"{_HOST}/api/v1/users/{_USER_ID}/forums?per_page=20",
    )


def _row(record_id: int, draw: int, topic: str, content: str) -> dict[str, object]:
    return {
        "id": record_id,
        "status": "published",
        "user_id": _USER_ID,
        "draw": draw,
        "topic": topic,
        "content": content,
        "user": {"id": _USER_ID, "nickname": "预判晚风"},
    }


def _bundle(*rows: dict[str, object]) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                json.dumps(list(rows), ensure_ascii=False),
                f"{_HOST}/api/v1/users/{_USER_ID}/forums?per_page=20",
                DocumentType.JSON,
                0,
                f"api:{_USER_ID}",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def test_two_zodiac_post_takes_the_first_one() -> None:
    """322 期正文「【鼠】【虎】」，按用户 2026-11-18 授权只取第一个（鼠）。"""
    site = _site()
    bundle = _bundle(
        _row(
            16425127,
            322,
            "322期:♥绝杀二肖♥",
            "117期～316期&nbsp; &nbsp; 共200期～错9期"
            "<div>322期:♥绝杀二肖♥【鼠】【虎】开:發00准</div>"
            "<div>放第一的就是固定的🔪一肖，以后改🔪2肖。</div>",
        )
    )

    decision = validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 322)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "鼠"
    assert decision.candidate.record_id == "16425127"


def test_old_one_zodiac_topic_still_parses() -> None:
    """旧写法「绝杀一肖」单肖必须继续按原样解析，不受双肖改动影响。"""
    site = _site()
    bundle = _bundle(
        _row(16418302, 321, "320期:♥绝杀一肖♥", "<div>321期:♥绝杀一肖♥【牛】开:發00准</div>")
    )

    candidates = UserForumPostParser().parse(site, bundle)
    found = {candidate.period: candidate.zodiac for candidate in candidates}

    assert found[321] == "牛"


def test_second_zodiac_is_never_produced_as_separate_candidate() -> None:
    """双肖帖不能产出第二个候选，否则统一校验会按同期冲突拦截。"""
    site = _site()
    bundle = _bundle(
        _row(16425127, 322, "322期:♥绝杀二肖♥", "<div>322期:♥绝杀二肖♥【鼠】【虎】开:發00准</div>")
    )

    candidates = UserForumPostParser().parse(site, bundle)

    assert [candidate.zodiac for candidate in candidates if candidate.period == 322] == ["鼠"]


def test_site_is_registered() -> None:
    entries = json.loads((_ROOT / "sites.json").read_text(encoding="utf-8"))
    hits = [entry for entry in entries if entry.get("name") == "预判晚风"]

    assert len(hits) == 1
    entry = hits[0]
    assert entry["url"] == f"{_HOST}/#/users/{_USER_ID}"
    assert entry["pick"] == "top"
    assert entry["parser_id"] == "special.user_forum_post"
    assert entry["source_policy"] == "api_then_http"
    assert "special.user_forum_post" in build_registry().parser_ids
