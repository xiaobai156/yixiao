from __future__ import annotations

from pathlib import Path

from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import KaijiangFacaiTableParser
from zodiac_v2.validation.conflicts import validate_candidates

ROOT = Path(__file__).parents[1]
URL = "https://84477.kjfc88b.app:2443/welcome.html#234432"


def _bundle(url: str = URL) -> SourceBundle:
    rows = (
        ("238期", "5尾", "猴肖", "05", "蓝波", "开:虎17"),
        ("239期", "1尾", "虎肖", "03", "绿波", "开:赚99"),
        ("240期", "?尾", "?", "?", "?", "开:赚99"),
    )
    table = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in (("期数", "杀尾", "杀肖", "杀合", "杀波", "开奖"), *rows)
    )
    return SourceBundle(
        (
            SourceDocument(
                f'<div class="list-title">开奖发财【综合杀料】11447.COM</div><table>{table}</table>',
                url,
                DocumentType.BROWSER,
                0,
                f"browser-page:{url}",
                0,
                "234432",
            ),
        ),
        scan_complete=True,
    )


def test_browser_table_selects_239_and_rejects_adjacent_periods() -> None:
    sites, _scraper = _runtime(ROOT / "sites.json")
    site = next(site for site in sites if site.name == "开奖发财")
    candidates = KaijiangFacaiTableParser().parse(site, _bundle())

    current = validate_candidates(site, _bundle(), candidates, 239)
    previous = validate_candidates(site, _bundle(), candidates, 238)
    pending = validate_candidates(site, _bundle(), candidates, 240)

    assert current.ok and current.candidate is not None
    assert current.candidate.zodiac == "虎"
    assert not previous.ok
    assert not pending.ok


def test_browser_table_rejects_wrong_endpoint() -> None:
    sites, _scraper = _runtime(ROOT / "sites.json")
    site = next(site for site in sites if site.name == "开奖发财")

    assert not KaijiangFacaiTableParser().parse(
        site,
        _bundle("https://wrong.example/welcome.html#234432"),
    )


def test_kaijiang_facai_uses_fixed_browser_source() -> None:
    sites, _scraper = _runtime(ROOT / "sites.json")
    site = next(site for site in sites if site.name == "开奖发财")

    assert site.url == URL
    assert site.source_policy == "browser"
