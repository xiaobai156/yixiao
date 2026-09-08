from dataclasses import asdict, replace
import json

from probe import ROOT, EVIDENCE, hashes
from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode, SourceBundle


EXPECTED = {'澳门金手指': '虎', '碁布星罗': '羊', '宗政云裳': '马', '连中谎言': '狗', '寒武忌': '鼠'}


def main():
    before = hashes()
    sites, scraper = _runtime(ROOT / 'sites.json')
    targets = [replace(s, parser_id='family.strict_article') if s.name == '宗政云裳' else s
               for s in sites if s.name in EXPECTED]
    targets = [replace(s, source_policy='http_consensus') if s.name == '澳门金手指' else s for s in targets]
    assert len(targets) == len(EXPECTED)
    results = scraper.scrape_sites(targets, 245, RunMode.READ_ONLY, workers=3)
    report = []
    for r in results:
        (EVIDENCE / (r.site.name + '-verified.json')).write_text(
            json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding='utf-8')
        print(r.site.name, r.candidate.zodiac if r.ok else r.reason, flush=True)
        assert r.ok and r.candidate.zodiac == EXPECTED[r.site.name], (r.site.name, r.reason)
        bundle = SourceBundle(r.documents, (), scan_complete=True)
        checks = {p: scraper._evaluate(r.site, p, bundle, RunMode.READ_ONLY).ok for p in (244, 246, 999)}
        print('ADJACENT_AND_MISSING', checks, flush=True)
        assert not any(checks.values()), checks
        report.append({'site': r.site.name, 'period': 245, 'zodiac': r.candidate.zodiac, 'negative_checks': checks})
    assert hashes() == before
    (EVIDENCE / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('VERIFIED_5_FORMAL_FILES_UNCHANGED', flush=True)


if __name__ == '__main__':
    main()
