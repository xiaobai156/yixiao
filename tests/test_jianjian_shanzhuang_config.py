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
from zodiac_v2.parsers.dedicated import TtssPeriodArticleParser

_URL = "https://dh-nwsm-0806.cmw01490353c.app/pk/cmpk13.html"


def test_cmpk13_config_uses_semantic_site_name() -> None:
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "sites.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in config if item.get("url") == _URL)

    assert entry["name"] == "神剑山庄"
    assert entry["article_keyword"] == "神剑山庄"


def test_semantic_site_name_parses_top_period_cycle() -> None:
    site = SiteConfig(
        name="神剑山庄",
        url=_URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.ttss_period_article",
        source_policy="http_documents",
        article_keyword="神剑山庄",
    )
    document = SourceDocument(
        "\n".join(
            (
                "225期:神剑山庄 【绝杀一肖】",
                "【马】 开:00:准 31中29",
                "224期:神剑山庄 【绝杀一肖】",
                "【龙】 开09准 30中29",
            )
        ),
        _URL,
        DocumentType.HTML,
        0,
        "html:cmpk13",
        0,
    )

    candidates = TtssPeriodArticleParser().parse(site, SourceBundle((document,), ()))

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "马"),
        (224, "龙"),
    ]
