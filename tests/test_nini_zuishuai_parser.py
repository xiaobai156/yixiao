"""妮妮最帅（用户 231022）新增回归：栏目改名 / 新分隔符 / 旧写法兼容 / 方向取首条。"""
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
_USER_ID = 231022


def _site(direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(
        name="妮妮最帅",
        url=f"{_HOST}/#/users/{_USER_ID}",
        direction=direction,
        section=SiteSection.NEW,
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
        "user": {"id": _USER_ID, "nickname": "妮妮最帅"},
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


def test_current_period_with_new_topic_and_tilde_separator() -> None:
    """318 期栏目改成「恭喜发财」、分隔符换成「～」，正文取 318=龙。"""
    site = _site()
    bundle = _bundle(
        _row(16394739, 318, "恭喜发财", "<div>318期～绝杀一肖——龙——？</div>317期～绝杀一肖——猪——✓（蛇）（26）")
    )

    decision = validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 318)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"


def test_older_topic_and_abbreviated_kill_word_still_parse() -> None:
    """250-256 期栏目是「绝杀一肖」，个别期写作「绝杀—肖」，历史仍要识别。"""
    site = _site()
    bundle = _bundle(
        _row(15972710, 252, "绝杀一肖", "252期♥绝杀—肖——牛——？ 251期♥绝杀—肖——狗——✓（牛）（30）"),
        _row(16000042, 256, "绝杀一肖", "256期♥绝杀一肖——马——？ 255期♥绝杀一肖——羊——✓（猪）（44）"),
    )

    candidates = UserForumPostParser().parse(site, bundle)
    found = {candidate.period: candidate.zodiac for candidate in candidates}

    assert found[252] == "牛"
    assert found[256] == "马"


def test_top_direction_picks_first_matching_post() -> None:
    """同一期若有多帖，top 取第一帖；这里用一个 318 帖锁定行为。"""
    site = _site()
    bundle = _bundle(
        _row(16394739, 318, "恭喜发财", "318期～绝杀一肖——龙——？"),
        _row(16393696, 317, "恭喜发财", "317期～绝杀一肖——猪——？"),
    )

    decision = validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 318)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.record_id == "16394739"


def test_site_is_registered_in_new_section() -> None:
    entries = json.loads((_ROOT / "sites.json").read_text(encoding="utf-8"))
    hits = [entry for entry in entries if entry.get("name") == "妮妮最帅"]

    assert len(hits) == 1
    entry = hits[0]
    assert entry["url"] == f"{_HOST}/#/users/{_USER_ID}"
    assert entry["api_url"] == f"{_HOST}/api/v1/users/{_USER_ID}/forums?per_page=20"
    assert entry["pick"] == "top"
    assert entry["section"] == "新增的站点"
    assert entry["parser_id"] == "special.user_forum_post"
    assert entry["source_policy"] == "api_then_http"
    assert "special.user_forum_post" in build_registry().parser_ids
