from __future__ import annotations

from pathlib import Path

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
from zodiac_v2.parsers.dedicated import (
    STRICT_ARTICLE_SPECS,
    GushouBandaoCycleParser,
    MacauCaixianzhiTableParser,
)
from zodiac_v2.parsers.families import StrictArticleFamilyParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates


def _bundle(name: str, *lines: str) -> SourceBundle:
    url = f"https://example.invalid/{name}"
    return SourceBundle(
        (
            SourceDocument(
                "\n".join(lines),
                url,
                DocumentType.SCRIPT,
                0,
                f"script:{name}",
                0,
                name,
            ),
        ),
        ("scan_complete:1",),
        scan_complete=True,
    )


def _browser_bundle(name: str, html: str) -> SourceBundle:
    url = f"https://example.invalid/{name}"
    return SourceBundle(
        (
            SourceDocument(
                html,
                url,
                DocumentType.BROWSER,
                0,
                f"browser:{name}",
                0,
                name,
            ),
        ),
        ("browser:200", "scan_complete:1"),
        scan_complete=True,
    )


def test_juesha_uses_latest_235_record_under_pending_236_title() -> None:
    site = SiteConfig(
        "决杀一肖",
        "https://example.invalid/juesha",
        Direction.BOTTOM,
        SiteSection.NEW,
        "family.strict_article",
        "http_documents",
    )
    bundle = _bundle(
        "决杀一肖",
        "236期:【决杀一肖】已更新",
        "233期 18-41-05-49-04-34 T07 07=鼠√",
        "234期 25-30-37-19-07-17 T39 39=龙√",
        "235期杀 龙√",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    current = validate_candidates(site, bundle, candidates, 235)
    pending = validate_candidates(site, bundle, candidates, 236)

    assert current.ok
    assert current.candidate is not None
    assert (current.candidate.period, current.candidate.zodiac) == (235, "龙")
    assert not pending.ok


def test_gushou_bottom_parser_keeps_only_last_record_cycle() -> None:
    site = SiteConfig(
        "孤守半岛",
        "https://example.invalid/gushou",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.gushou_bandao_cycle",
        "http_documents",
    )
    bundle = _bundle(
        "孤守半岛",
        "孤守半岛",
        "227期: 必杀一肖【马】",
        "235期: 必杀一肖【鸡】",
        "236期: 必杀一肖【龙】",
        "365期: 必杀一肖【蛇】",
        "001期: 必杀一肖【牛】",
        "227期: 必杀一肖【龙】",
        "235期: 必杀一肖【狗】",
        "236期: 必杀一肖【兔】",
    )

    candidates = GushouBandaoCycleParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert [(item.period, item.zodiac) for item in candidates] == [
        (1, "牛"),
        (227, "龙"),
        (235, "狗"),
        (236, "兔"),
    ]
    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, "兔")


def test_gushou_parser_rejects_records_without_exact_anchor() -> None:
    site = SiteConfig(
        "孤守半岛",
        "https://example.invalid/gushou",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.gushou_bandao_cycle",
        "http_documents",
    )
    bundle = _bundle("孤守半岛", "其他站点", "236期: 必杀一肖【兔】")

    assert GushouBandaoCycleParser().parse(site, bundle) == ()


def test_small_wanzi_bottom_selects_last_complete_record_cycle() -> None:
    site = SiteConfig(
        "小小丸子",
        "https://example.invalid/xiaoxiaowanzi",
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "family.strict_article",
        "browser",
    )
    bundle = _browser_bundle(
        "小小丸子",
        "<div>236期:小小丸子【绝杀一肖】</div>"
        "<div>235期:绝杀一肖【狗狗狗】</div><div>236期:绝杀一肖【鼠鼠鼠】</div>"
        "<div>237期:绝杀一肖【龙龙龙】</div><div>365期:绝杀一肖【蛇蛇蛇】</div>"
        "<div>001期:绝杀一肖【牛牛牛】</div><div>235期:绝杀一肖【羊羊羊】</div>"
        "<div>236期:绝杀一肖【猪猪猪】</div>",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    current = validate_candidates(site, bundle, candidates, 236)
    previous = validate_candidates(site, bundle, candidates, 235)
    nonexistent = validate_candidates(site, bundle, candidates, 237)

    assert current.ok and current.candidate is not None
    assert (current.candidate.period, current.candidate.zodiac) == (236, "猪")
    assert not previous.ok
    assert not nonexistent.ok


def test_tianfan_difu_bottom_selects_last_complete_record_cycle() -> None:
    site = SiteConfig(
        "天翻地覆",
        "https://example.invalid/tianfan-difu",
        Direction.BOTTOM,
        SiteSection.NEW,
        "family.strict_article",
        "browser",
    )
    bundle = _browser_bundle(
        "天翻地覆",
        "<div>236期:天翻地覆【绝杀一肖】已公开！</div><div>天翻地覆 发表于</div>"
        "<div>235期【绝杀一肖】【狗狗狗】开:01准</div>"
        "<div>236期【绝杀一肖】【牛牛牛】开:00准</div>"
        "<div>237期【绝杀一肖】【龙龙龙】开:??准</div>"
        "<div>365期【绝杀一肖】【蛇蛇蛇】开:01准</div>"
        "<div>001期【绝杀一肖】【鼠鼠鼠】开:01准</div>"
        "<div>235期【绝杀一肖】【羊羊羊】开:01准</div>"
        "<div>236期【绝杀一肖】【虎虎虎】开:0000准</div>",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, "虎")
    assert not validate_candidates(site, bundle, candidates, 237).ok


def test_directional_cycle_keeps_conflict_inside_selected_cycle() -> None:
    site = SiteConfig(
        "天翻地覆",
        "https://example.invalid/tianfan-difu",
        Direction.BOTTOM,
        SiteSection.NEW,
        "family.strict_article",
        "browser",
    )
    bundle = _browser_bundle(
        "天翻地覆",
        "<div>236期:天翻地覆【绝杀一肖】已公开！</div><div>天翻地覆 发表于</div>"
        "<div>236期【绝杀一肖】【牛牛牛】开:00准</div>"
        "<div>365期【绝杀一肖】【蛇蛇蛇】开:01准</div>"
        "<div>001期【绝杀一肖】【鼠鼠鼠】开:01准</div>"
        "<div>236期【绝杀一肖】【虎虎虎】开:0000准</div>"
        "<div>236期【绝杀一肖】【猪猪猪】开:0000准</div>",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert not decision.ok
    assert "多个合法候选" in decision.reason


def test_qianwang_bottom_selects_last_completed_annual_cycle() -> None:
    site = SiteConfig(
        "千王之王",
        "https://example.invalid/qianwang",
        Direction.BOTTOM,
        SiteSection.NEW,
        "family.strict_article",
        "http_documents",
    )
    bundle = _bundle(
        "千王之王",
        "238期【千王之王】（绝杀一肖）已公开",
        "237期（绝杀一肖）：蛇肖",
        "238期（绝杀一肖）：牛肖",
        "001期（绝杀一肖）：猴肖",
        "237期（绝杀一肖）：蛇肖",
        "238期（绝杀一肖）：龙肖",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 238)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"
    assert not validate_candidates(site, bundle, candidates, 237).ok


def test_repeated_archive_strict_sites_enable_directional_cycles() -> None:
    names = {
        "六合兵团",
        "准杀一肖",
        "金牌谜语",
        "发财之道",
        "乘风转舵",
        "门庭若市",
        "西东字宙",
        "高风亮节",
        "雷猴烧酒",
    }

    assert all(STRICT_ARTICLE_SPECS[name].directional_cycles for name in names)


def test_macau_caixianzhi_accepts_exact_rendered_table() -> None:
    site = SiteConfig(
        "澳门彩先知",
        "https://example.invalid/macau",
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "special.macau_caixianzhi_table",
        "browser",
        embedded_max_bytes=8_000_000,
    )
    bundle = _browser_bundle(
        "澳门彩先知",
        '<div id="con_jihuadanshuang50000qd_1"><p>澳门彩先知官方网址</p><table>'
        "<tr><th>期数</th><th>禁肖</th><th>禁半波</th><th>禁1尾</th><th>禁1头</th><th>开奖结果</th></tr>"
        "<tr><td>235期</td><td>鸡肖</td><td>蓝波单</td><td>五尾</td><td>3头</td><td>开:32准</td></tr>"
        "<tr><td>236期</td><td>猪肖</td><td>红波双</td><td>六尾</td><td>4头</td><td>开:0000准</td></tr>"
        "</table></div>",
    )

    candidates = MacauCaixianzhiTableParser().parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 236)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (236, "猪")
    assert not validate_candidates(site, bundle, candidates, 237).ok


def test_two_repaired_exception_sites_are_registered_as_new_bottom_sites() -> None:
    expected = {
        "决杀一肖": "family.strict_article",
        "孤守半岛": "special.gushou_bandao_cycle",
    }
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {site.name: site for site in sites if site.name in expected}

    assert set(selected) == set(expected)
    assert all(site.section is SiteSection.NEW for site in selected.values())
    assert all(site.direction is Direction.BOTTOM for site in selected.values())
    assert {name: site.parser_id for name, site in selected.items()} == expected


def test_three_js_sites_use_fixed_browser_source_policy() -> None:
    sites = load_sites(
        Path("sites.json"),
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = {
        site.name: site
        for site in sites
        if site.name in {"澳门彩先知", "小小丸子", "天翻地覆"}
    }

    assert set(selected) == {"澳门彩先知", "小小丸子", "天翻地覆"}
    assert all(site.direction is Direction.BOTTOM for site in selected.values())
    assert all(site.source_policy == "browser" for site in selected.values())
    assert selected["澳门彩先知"].embedded_max_bytes == 8_000_000
    assert selected["天翻地覆"].parser_id == "family.strict_article"
