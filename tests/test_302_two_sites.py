# -*- coding: utf-8 -*-
"""302 期接入的两站（天外有天 / 爆竹声中）：配置与通用解析器方向窗口用例。"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import COMMON_PATTERN_ID
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates

ROOT = Path(__file__).resolve().parents[1]

TIANWAI_URL = "https://eyxcfxcw.0nmq7-eh2st-jeifgu.work:17455/topic/479827.html"
BAOZHU_URL = "https://boarsyqo.n14p6-phtp6-njdhzx.work:17466/topic/504953.html"

# 天外有天：列表按期数升序，302 在末尾 → bottom
TIANWAI_TEXT = """302期【天外有天】铁杀一肖已公开
293期【铁杀一肖】【狗】开兔28准
294期【铁杀一肖】【鼠】开兔28准
295期【铁杀一肖】【牛】开马25准
296期【铁杀一肖】【鼠】开猴23准
297期【铁杀一肖】【虎】开马13准
298期【铁杀一肖】【兔】开猪08准
299期【铁杀一肖】【猴】开猴23错
300期【铁杀一肖】【龙】开蛇38准
301期【铁杀一肖】【狗】开虎17准
302期【铁杀一肖】【猪】开0000准
"""

# 爆竹声中：列表按期数降序，302 在开头 → top
BAOZHU_TEXT = """302期:爆竹声中【绝杀一肖】资料已公开
302期：绝杀一肖【龙龙龙】开0000准
301期：绝杀一肖【羊羊羊】开虎17准
300期：绝杀一肖【猪猪猪】开蛇38准
299期：绝杀一肖【猪猪猪】开猴23准
298期：绝杀一肖【羊羊羊】开猪08准
297期：绝杀一肖【兔兔兔】开马13准
296期：绝杀一肖【羊羊羊】开猴23准
295期：绝杀一肖【鸡鸡鸡】开马25准
294期：绝杀一肖【龙龙龙】开兔28准
293期：绝杀一肖【兔兔兔】开虎05准
"""

WINDOW = tuple(range(293, 303))
TIANWAI_WINDOW = "狗鼠牛鼠虎兔猴龙狗猪"
BAOZHU_WINDOW = "兔龙鸡羊兔羊猪猪羊龙"


def _site(name: str, url: str, direction: Direction) -> SiteConfig:
    return SiteConfig(
        name, url, direction, SiteSection.EXISTING, f"regex.{COMMON_PATTERN_ID}", "browser"
    )


def _bundle(text: str, url: str) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(text, url, DocumentType.BROWSER, 0, "browser:0", 0),
        ),
        scan_complete=True,
    )


def _window(site: SiteConfig, bundle: SourceBundle) -> dict[int, str]:
    """历史窗口按 LEFT 方向逐期取值（与 historical_results 一致）。"""
    history_site = replace(site, direction=Direction.LEFT)
    candidates = build_registry().parse(history_site, bundle)
    values: dict[int, str] = {}
    for period in WINDOW:
        decision = validate_candidates(history_site, bundle, candidates, period)
        if decision.ok and decision.candidate is not None:
            values[period] = decision.candidate.zodiac
    return values


def _config_entries() -> dict[str, dict[str, str]]:
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))
    return {item["name"]: item for item in sites}


def test_tianwaiyoutian_uses_bottom_edge_and_full_window() -> None:
    site = _site("天外有天", TIANWAI_URL, Direction.BOTTOM)
    bundle = _bundle(TIANWAI_TEXT, TIANWAI_URL)
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猪"

    values = _window(site, bundle)
    assert "".join(values[period] for period in WINDOW) == TIANWAI_WINDOW


def test_baozhushengzhong_uses_top_edge_and_full_window() -> None:
    site = _site("爆竹声中", BAOZHU_URL, Direction.TOP)
    bundle = _bundle(BAOZHU_TEXT, BAOZHU_URL)
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"

    values = _window(site, bundle)
    assert "".join(values[period] for period in WINDOW) == BAOZHU_WINDOW


def test_both_sites_registered_as_existing_sites() -> None:
    entries = _config_entries()

    tianwai = entries["天外有天"]
    assert tianwai["url"] == TIANWAI_URL
    assert tianwai["pick"] == "bottom"
    assert tianwai["section"] == SiteSection.EXISTING.value
    assert tianwai["parser_id"] == f"regex.{COMMON_PATTERN_ID}"
    assert tianwai["source_policy"] == "browser"

    baozhu = entries["爆竹声中"]
    assert baozhu["url"] == BAOZHU_URL
    assert baozhu["pick"] == "top"
    assert baozhu["section"] == SiteSection.EXISTING.value
    # 306 期起「最新帖」列表偶发把别站「绝杀一头…鸡」算进 306 期造成随机冲突，
    # 改由 strict_article 锁标题块；见 tests/test_baozhushengzhong_parser.py。
    assert baozhu["parser_id"] == "family.strict_article"
    assert baozhu["source_policy"] == "browser"
