from dataclasses import asdict
import json

from probe import EVIDENCE, NAMES, ROOT, hashes
from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode, SourceBundle


EXPECTED = {"极乐世界": "兔", "寒武忌": "龙"}


def main():
    before = hashes()
    sites, scraper = _runtime(ROOT / "sites.json")
    targets = tuple(site for site in sites if site.name in NAMES)
    results = scraper.scrape_sites(targets, 246, RunMode.READ_ONLY, workers=3)
    report = []
    for result in results:
        (EVIDENCE / f"{result.site.name}-verified.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result.ok:
            assert result.site.name in EXPECTED
            assert result.candidate is not None
            assert result.candidate.zodiac == EXPECTED[result.site.name]
            bundle = SourceBundle(result.documents, (), scan_complete=True)
            checks = {
                period: scraper._evaluate(result.site, period, bundle, RunMode.READ_ONLY).ok
                for period in (245, 247, 999)
            }
            assert not any(checks.values()), (result.site.name, checks)
            report.append({"site": result.site.name, "zodiac": result.candidate.zodiac, "negative_checks": checks})
            print("PASS", result.site.name, result.candidate.zodiac, checks)
        else:
            assert result.site.name not in EXPECTED, (result.site.name, result.reason)
            report.append({"site": result.site.name, "reason": result.reason})
            print("FAIL", result.site.name, result.reason)
    assert hashes() == before
    (EVIDENCE / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("VERIFIED_FORMAL_FILES_UNCHANGED")


if __name__ == "__main__":
    main()
