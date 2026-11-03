# -*- coding: utf-8 -*-
"""302 期接入的两站（开心蒙蒙 / 打鸣小鸡）：配置与通用解析器方向窗口用例。"""
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

KAIXIN_URL = "https://gprakaak.9gr47-3du2a-erzanc.work:17477/topic/457925.html"
DAMING_URL = "https://gprakaak.9gr47-3du2a-erzanc.work:17477/topic/463898.html"

# 开心蒙蒙：列表按期数降序，302 在开头 → top
KAIXIN_TEXT = """高手帖子 302期九肖10码【大力杀一肖】高手发布
开心蒙蒙 发表于 10月29日 09:41:44
302期：【大力杀一肖】《兔兔》开？00准
301期：【大力杀一肖】《猴猴》开虎17准
300期：【大力杀一肖】《鼠鼠》开蛇38准
299期：【大力杀一肖】《兔兔》开猴23准
298期：【大力杀一肖】《猴猴》开猪08准
297期：【大力杀一肖】《羊羊》开马13准
296期：【大力杀一肖】《鸡鸡》开猴23准
295期：【大力杀一肖】《虎虎》开马25准
294期：【大力杀一肖】《猪猪》开兔28准
293期：【大力杀一肖】《虎虎》开虎05错
"""

# 打鸣小鸡：列表按期数升序，302 在末尾 → bottom
DAMING_TEXT = """高手帖子 302期【必杀一肖】高手发布
打鸣小鸡 发表于 10月29日 09:41:44
293期〓【必杀一肖】〓●马●开虎05准
294期〓【必杀一肖】〓●虎●开兔28错
295期〓【必杀一肖】〓●鸡●开马25准
296期〓【必杀一肖】〓●兔●开猴23准
297期〓【必杀一肖】〓●龙●开马13准
298期〓【必杀一肖】〓●羊●开猪08准
299期〓【必杀一肖】〓●鼠●开猴23准
300期〓【必杀一肖】〓●猴●开蛇38准
301期〓【必杀一肖】〓●鼠●开虎17准
302期〓【必杀一肖】〓●虎●开？00准
"""

WINDOW = tuple(range(293, 303))
KAIXIN_WINDOW = "虎猪虎鸡羊猴兔鼠猴兔"
DAMING_WINDOW = "马虎鸡兔龙羊鼠猴鼠虎"


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


def test_kaixinmengmeng_uses_top_edge_and_full_window() -> None:
    site = _site("开心蒙蒙", KAIXIN_URL, Direction.TOP)
    bundle = _bundle(KAIXIN_TEXT, KAIXIN_URL)
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "兔"

    values = _window(site, bundle)
    assert "".join(values[period] for period in WINDOW) == KAIXIN_WINDOW


def test_damingxiaojii_uses_bottom_edge_and_full_window() -> None:
    site = _site("打鸣小鸡", DAMING_URL, Direction.BOTTOM)
    bundle = _bundle(DAMING_TEXT, DAMING_URL)
    candidates = build_registry().parse(site, bundle)

    decision = validate_candidates(site, bundle, candidates, 302)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "虎"

    values = _window(site, bundle)
    assert "".join(values[period] for period in WINDOW) == DAMING_WINDOW


def test_both_sites_registered_as_existing_sites_with_common_parser() -> None:
    entries = _config_entries()

    kaixin = entries["开心蒙蒙"]
    assert kaixin["url"] == KAIXIN_URL
    assert kaixin["pick"] == "top"
    assert kaixin["section"] == SiteSection.EXISTING.value
    assert kaixin["parser_id"] == f"regex.{COMMON_PATTERN_ID}"
    assert kaixin["source_policy"] == "browser"

    daming = entries["打鸣小鸡"]
    assert daming["url"] == DAMING_URL
    assert daming["pick"] == "bottom"
    assert daming["section"] == SiteSection.EXISTING.value
    assert daming["parser_id"] == f"regex.{COMMON_PATTERN_ID}"
    assert daming["source_policy"] == "browser"
