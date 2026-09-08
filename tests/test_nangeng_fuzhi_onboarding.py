import json
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
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates


ROOT = Path(__file__).parents[1]
NAME = "男耕妇织"
URL = "https://igzsdnmg.b8dwh-jbi7g-pdseaa.work:17455/topic/213799.html"
EXPECTED = {
    241: "牛",
    240: "龙",
    239: "鸡",
    238: "龙",
    237: "羊",
    236: "猴",
    235: "狗",
    234: "虎",
    233: "兔",
    232: "狗",
}


def _site() -> SiteConfig:
    return SiteConfig(
        NAME,
        URL,
        Direction.TOP,
        SiteSection.EXISTING,
        "family.strict_article",
        "http_documents",
    )


def test_nangeng_fuzhi_strict_article_parser() -> None:
    text = "\n".join(
        (
            "241期:男耕妇织→原创【杀特一肖】已公開",
            "作者:男耕妇织",
            *(f"{period}期：→【杀特一肖】→【{zodiac}】〓开：00" for period, zodiac in EXPECTED.items()),
        )
    )
    document = SourceDocument(text, URL, DocumentType.SCRIPT, 0, "script:test", 0, "213799")
    bundle = SourceBundle((document,))
    candidates = build_registry().parse(_site(), bundle)

    assert [(item.period, item.zodiac) for item in candidates] == list(EXPECTED.items())
    decision = validate_candidates(_site(), bundle, candidates, 241)
    assert decision.ok
    assert decision.candidate is not None
    assert decision.candidate.zodiac == "牛"


def test_nangeng_fuzhi_formal_config_and_cache() -> None:
    sites = load_sites(
        ROOT / "sites.json",
        parser_ids=build_registry().parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    selected = [site for site in sites if site.name == NAME]
    assert selected == [_site()]

    cache = json.loads((ROOT / "recent_10_cache.json").read_text(encoding="utf-8"))
    cached = next(site for site in cache["sites"] if site["name"] == NAME)
    assert [(record["period"], record["zodiac"]) for record in cached["records"]] == list(
        EXPECTED.items()
    )
    assert cached["onboarding_exception"]["duplicate_with"] == ["听天委命", "夏侯跣一"]
