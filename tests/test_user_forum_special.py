from __future__ import annotations

import json
from pathlib import Path

import pytest

from zodiac_v2.cli import SOURCE_POLICIES
from zodiac_v2.config import load_sites
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


def _site(
    name: str,
    user_id: int,
    *,
    host: str = _HOST,
    direction: Direction = Direction.BOTTOM,
    section: SiteSection = SiteSection.NEW,
) -> SiteConfig:
    api_url = f"{host}/api/v1/users/{user_id}/forums?per_page=20"
    return SiteConfig(
        name=name,
        url=f"{host}/#/users/{user_id}",
        direction=direction,
        section=section,
        parser_id="special.user_forum_post",
        source_policy="api_then_http",
        api_url=api_url,
    )


def _bundle(user_id: int, *rows: dict[str, object], host: str = _HOST) -> SourceBundle:
    api_url = f"{host}/api/v1/users/{user_id}/forums?per_page=20"
    return SourceBundle(
        (
            SourceDocument(
                json.dumps(list(rows), ensure_ascii=False),
                api_url,
                DocumentType.JSON,
                0,
                f"api:{user_id}",
                0,
            ),
        ),
        ("api:200", "scan_complete:1"),
        scan_complete=True,
    )


def _row(
    *,
    record_id: int,
    user_id: int,
    name: str,
    draw: int,
    topic: str,
    content: str,
) -> dict[str, object]:
    return {
        "id": record_id,
        "status": "published",
        "user_id": user_id,
        "draw": draw,
        "topic": topic,
        "content": content,
        "user": {"id": user_id, "nickname": name},
    }


def test_fulu_draw_binds_mislabelled_post_and_uses_bottom_history() -> None:
    row = _row(
        record_id=15823178,
        user_id=154933,
        name="福禄寿喜财",
        draw=228,
        topic="227期",
        content="182期杀牛√<div>227期杀马√</div><div>228期杀兔√</div>",
    )
    site = _site("福禄寿喜财", 154933)
    bundle = _bundle(154933, row)
    parser = UserForumPostParser()

    selected = parser.select_source(site, bundle, 228)

    assert selected is not None
    assert selected.documents[0].record_id == "15823178"
    candidates = parser.parse(site, selected)
    decision = validate_candidates(site, selected, candidates, 228)
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (228, "兔")


def test_hanwuji_bottom_uses_draw_record_and_left_mode_exposes_inline_history() -> None:
    row = _row(
        record_id=15892448,
        user_id=180502,
        name="寒武忌",
        draw=238,
        topic="238 澳门风云",
        content="237期杀&lt;鼠&gt;特开:羊12★<div>238期杀&lt;羊&gt;特开:？00★</div>",
    )
    site = _site(
        "寒武忌",
        180502,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )
    bundle = _bundle(
        180502,
        row,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )
    parser = UserForumPostParser()

    live_candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, live_candidates, 238)
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (238, "羊")

    history_site = _site(
        "寒武忌",
        180502,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
        direction=Direction.LEFT,
    )
    assert [(item.period, item.zodiac) for item in parser.parse(history_site, bundle)] == [
        (237, "鼠"),
        (238, "羊"),
    ]


def test_hanwuji_accepts_star_delimited_current_post() -> None:
    row = _row(
        record_id=15923741,
        user_id=180502,
        name="寒武忌",
        draw=243,
        topic="243 澳门风云",
        content=(
            "237期杀✦鼠✦开12羊√<div>238期杀✦羊✦开17虎√</div>"
            "<div>243期杀✦虎✦开00？√</div>"
        ),
    )
    site = _site(
        "寒武忌",
        180502,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )
    bundle = _bundle(
        180502,
        row,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )
    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 243)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (243, "虎")


def test_hanwuji_accepts_actual_bracket_delimited_current_post() -> None:
    row = _row(
        record_id=15968611,
        user_id=180502,
        name="寒武忌",
        draw=251,
        topic="251 澳门风云",
        content=(
            "<div>〖〗245期〗杀鼠 √〖18牛〗</div>"
            "<div>〖〗246期〗杀龙 √〖30牛〗</div>"
            "<div>〖〗247期〗杀牛 √〖48兔〗</div>"
            "<div>〖〗248期〗杀猪 ✕〖20猪〗</div>"
            "<div>〖〗249期〗杀猪 √〖23猴〗</div>"
            "<div>〖〗250期〗杀狗 √〖14蛇〗+杀 猴鼠鸡龙兔虎</div>"
            "<div>〖〗251期〗杀蛇 √〖？00〗</div>"
        ),
    )
    site = _site(
        "寒武忌",
        180502,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )
    bundle = _bundle(
        180502,
        row,
        host="https://uuizld.ytv5j-jva78-vglwnj.work",
    )

    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 251)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (251, "蛇")


def test_fulu_bottom_selects_last_post_when_same_period_value_matches() -> None:
    first = _row(
        record_id=15886292,
        user_id=154933,
        name="福禄寿喜财",
        draw=238,
        topic="238期",
        content="237期杀羊X<div>238期杀龙√</div>",
    )
    second = _row(
        record_id=15886257,
        user_id=154933,
        name="福禄寿喜财",
        draw=238,
        topic="238期",
        content="237期杀羊√<div>238期杀龙√</div>",
    )
    site = _site("福禄寿喜财", 154933)
    parser = UserForumPostParser()

    selected = parser.select_source(site, _bundle(154933, first, second), 238)

    assert selected is not None
    assert selected.documents[0].record_id == "15886257"
    candidates = parser.parse(site, selected)
    decision = validate_candidates(site, selected, candidates, 238)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"


def test_fulu_does_not_select_between_different_same_period_values() -> None:
    first = _row(
        record_id=15886292,
        user_id=154933,
        name="福禄寿喜财",
        draw=238,
        topic="238期",
        content="238期杀龙√",
    )
    second = _row(
        record_id=15886257,
        user_id=154933,
        name="福禄寿喜财",
        draw=238,
        topic="238期",
        content="238期杀蛇√",
    )
    parser = UserForumPostParser()

    assert parser.select_source(
        _site("福禄寿喜财", 154933),
        _bundle(154933, first, second),
        238,
    ) is None


def test_lianzhong_selects_valid_fans_post_and_ignores_cancel_post() -> None:
    valid_row = _row(
        record_id=15827548,
        user_id=166365,
        name="连中谎言",
        draw=228,
        topic="228  粉丝看就好",
        content="228绝杀一肖兔",
    )
    non_result_row = _row(
        record_id=15821032,
        user_id=166365,
        name="连中谎言",
        draw=228,
        topic="228",
        content="204绝杀一肖猴✔️<div>227绝杀一肖兔错的离谱</div>"
        "<div>228不再发杀了，取消关注吧</div>",
    )
    site = _site("连中谎言", 166365)
    bundle = _bundle(166365, valid_row, non_result_row)
    parser = UserForumPostParser()

    selected = parser.select_source(site, bundle, 228)

    assert selected is not None
    assert selected.documents[0].record_id == "15827548"
    candidates = parser.parse(site, selected)
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(228, "兔")]
    decision = validate_candidates(site, selected, candidates, 228)
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (228, "兔")


def test_qingyunzi_renamed_identity_keeps_user_post_detail_parser() -> None:
    host = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
    user_id = 200290
    site = _site(
        "青云子",
        user_id,
        host=host,
        section=SiteSection.EXISTING,
    )
    row = _row(
        record_id=15833333,
        user_id=user_id,
        name="青云子",
        draw=229,
        topic="六肖中特",
        content="资料杀一肖《今年错9》<div>228期杀《鼠》开17</div>"
        "<div>229期杀《羊》开??</div>",
    )
    bundle = _bundle(user_id, row, host=host)

    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 229)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (229, "羊")


def test_qingyunzi_accepts_236_four_kill_record_format() -> None:
    host = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
    user_id = 200290
    site = _site("青云子", user_id, host=host, section=SiteSection.EXISTING)
    row = _row(
        record_id=15888888,
        user_id=user_id,
        name="青云子",
        draw=236,
        topic="六肖中特",
        content="资料杀一肖《今年错9》<div>236四杀《虎》</div>",
    )
    bundle = _bundle(user_id, row, host=host)

    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, "虎")


@pytest.mark.parametrize(
    ("name", "user_id", "topic", "content", "expected"),
    [
        ("王木木儿涂涂", 202661, "🍻干杯朋友🍻", "235期杀☞猪", "猪"),
        ("暴躁骨衬", 46320, "绝杀一肖", "235期绝杀一肖【龙】", "龙"),
        ("妮最可爱", 231014, "大吉大利", "235期♥绝杀一肖——猪——", "猪"),
        ("朱红山峰", 6018, "绝杀一肖", "235期绝杀一肖《狗》", "狗"),
        ("鼓舞木料", 22134, "绝杀一肖", "235期绝杀一肖【虎】", "虎"),
        ("强烈电视", 2957, "绝杀一肖", "235期绝杀一肖《羊》", "羊"),
        ("利尿金花", 18126, "绝杀一肖", "235期精杀一肖【虎】", "虎"),
        ("困难戒指", 2450, "绝杀一肖", "235期：【绝杀一肖】【蛇】", "蛇"),
    ],
)
def test_selected_new_user_sites_parse_exact_235_post(
    name: str,
    user_id: int,
    topic: str,
    content: str,
    expected: str,
) -> None:
    site = _site(
        name,
        user_id,
        direction=Direction.BOTTOM if name == "王木木儿涂涂" else Direction.TOP,
    )
    row = _row(
        record_id=23500000 + user_id,
        user_id=user_id,
        name=name,
        draw=235,
        topic=topic,
        content=content,
    )
    bundle = _bundle(user_id, row)

    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 235)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (235, expected)
    assert decision.candidate.record_id == str(row["id"])


@pytest.mark.parametrize(
    ("name", "user_id", "topic", "content", "expected"),
    [
        ("高亢毛栗", 6148, "绝杀一肖", "236期：绝杀一肖 ▼杀狗▼", "狗"),
        ("分心猫咪", 1776, "【绝杀一肖】", "236期：【绝杀一肖】【兔】", "兔"),
    ],
)
def test_two_remaining_user_sites_parse_exact_236_post(
    name: str,
    user_id: int,
    topic: str,
    content: str,
    expected: str,
) -> None:
    site = _site(name, user_id, direction=Direction.TOP)
    row = _row(
        record_id=23600000 + user_id,
        user_id=user_id,
        name=name,
        draw=236,
        topic=topic,
        content=content,
    )
    bundle = _bundle(user_id, row)

    candidates = UserForumPostParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, expected)


def test_two_remaining_user_sites_expose_inline_history_for_onboarding() -> None:
    host = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
    parser = UserForumPostParser()
    for name, user_id, topic, content, expected in (
        (
            "高亢毛栗",
            6148,
            "绝杀一肖",
            "236期：绝杀一肖 ▼杀狗▼<p>235期：绝杀一肖 ▼杀羊▼</p>",
            [(236, "狗"), (235, "羊")],
        ),
        (
            "分心猫咪",
            1776,
            "【绝杀一肖】",
            "236期：【绝杀一肖】【兔】<p>235期：【绝杀一肖】【马】</p>",
            [(236, "兔"), (235, "马")],
        ),
    ):
        site = _site(
            name,
            user_id,
            host=host,
            direction=Direction.LEFT,
        )
        bundle = _bundle(
            user_id,
            _row(
                record_id=23600000 + user_id,
                user_id=user_id,
                name=name,
                draw=236,
                topic=topic,
                content=content,
            ),
            host=host,
        )

        candidates = parser.parse(site, bundle)

        assert [(candidate.period, candidate.zodiac) for candidate in candidates] == expected
        decision = validate_candidates(site, bundle, candidates, 235)
        assert decision.ok


def test_two_remaining_user_sites_stop_history_at_previous_cycle() -> None:
    host = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
    for name, user_id, topic, content, expected in (
        (
            "高亢毛栗",
            6148,
            "绝杀一肖",
            "236期：绝杀一肖 ▼杀狗▼<p>235期：绝杀一肖 ▼杀羊▼</p>"
            "<p>001期：绝杀一肖 ▼杀牛▼</p><p>365期：绝杀一肖 ▼杀鸡▼</p>"
            "<p>236期：绝杀一肖 ▼杀鸡▼</p>",
            [(236, "狗"), (235, "羊"), (1, "牛")],
        ),
        (
            "分心猫咪",
            1776,
            "【绝杀一肖】",
            "236期：【绝杀一肖】【兔】<p>235期：【绝杀一肖】【马】</p>"
            "<p>001期：【绝杀一肖】【牛】</p><p>365期：【绝杀一肖】【鸡】</p>"
            "<p>236期：【绝杀一肖】【鸡】</p>",
            [(236, "兔"), (235, "马"), (1, "牛")],
        ),
    ):
        site = _site(
            name,
            user_id,
            host=host,
            direction=Direction.LEFT,
        )
        bundle = _bundle(
            user_id,
            _row(
                record_id=23600000 + user_id,
                user_id=user_id,
                name=name,
                draw=236,
                topic=topic,
                content=content,
            ),
            host=host,
        )

        candidates = UserForumPostParser().parse(site, bundle)

        assert [(candidate.period, candidate.zodiac) for candidate in candidates] == expected


def test_two_remaining_user_sites_are_registered_as_new_top_sites() -> None:
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in {"高亢毛栗", "分心猫咪"}}

    assert set(selected) == {"高亢毛栗", "分心猫咪"}
    assert all(site.section is SiteSection.NEW for site in selected.values())
    assert all(site.direction is Direction.TOP for site in selected.values())
    assert all(site.parser_id == "special.user_forum_post" for site in selected.values())


@pytest.mark.parametrize(
    ("name", "user_id", "topic", "content", "expected"),
    (
        (
            "捡料糊口的曾白温",
            176592,
            "杀一肖",
            "239期：杀鼠-✔<div>240起：杀龙-✖</div><div>241期：杀牛-</div>",
            [(239, "鼠"), (240, "龙"), (241, "牛")],
        ),
        (
            "钟哥割",
            143002,
            "杀肖",
            "<div>239杀狗√</div><div>240杀鼠√</div><div>241杀马</div>",
            [(239, "狗"), (240, "鼠"), (241, "马")],
        ),
    ),
)
def test_241_bottom_user_sites_expose_only_valid_inline_history(
    name: str,
    user_id: int,
    topic: str,
    content: str,
    expected: list[tuple[int, str]],
) -> None:
    host = "https://zcphjs.ce83x-ms2rz-orwude.work:12277"
    parser = UserForumPostParser()
    row = _row(
        record_id=15900000 + user_id,
        user_id=user_id,
        name=name,
        draw=241,
        topic=topic,
        content=content,
    )
    bundle = _bundle(user_id, row, host=host)

    live_site = _site(name, user_id, host=host, direction=Direction.BOTTOM)
    live_candidates = parser.parse(live_site, bundle)
    live = validate_candidates(live_site, bundle, live_candidates, 241)
    assert live.ok
    assert live.candidate is not None
    assert (live.candidate.period, live.candidate.zodiac) == expected[-1]

    history_site = _site(name, user_id, host=host, direction=Direction.LEFT)
    assert [(item.period, item.zodiac) for item in parser.parse(history_site, bundle)] == expected


def test_241_special_user_sites_are_formal_existing_sites_with_cache_and_output() -> None:
    names = {"捡料糊口的曾白温", "钟哥割"}
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in names}

    assert set(selected) == names
    assert all(site.section is SiteSection.EXISTING for site in selected.values())
    assert all(site.direction is Direction.BOTTOM for site in selected.values())
    assert all(site.parser_id == "special.user_forum_post" for site in selected.values())

    cache = json.loads(Path("recent_10_cache.json").read_text(encoding="utf-8-sig"))
    cached = {site["name"]: site for site in cache["sites"] if site["name"] in names}
    assert [record["period"] for record in cached["捡料糊口的曾白温"]["records"]] == [
        241,
        240,
        239,
        238,
        237,
        236,
        235,
        234,
        233,
        232,
    ]
    assert cached["捡料糊口的曾白温"]["onboarding_exception"]["missing_periods"] == []
    assert [record["period"] for record in cached["钟哥割"]["records"]] == list(
        range(241, 231, -1)
    )
    assert cached["钟哥割"]["onboarding_exception"]["duplicate_with"] == ["七月未时"]

    success = Path(
        r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳\241期-肖.txt"
    ).read_text(encoding="utf-8")
    failure_path = Path(
        r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败\241期-肖-失败.txt"
    )
    failure = failure_path.read_text(encoding="utf-8") if failure_path.exists() else ""
    assert "牛 捡料糊口的曾白温" in success
    assert "马 钟哥割" in success
    assert not any(name in failure for name in names)
