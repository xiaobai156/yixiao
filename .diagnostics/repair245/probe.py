from pathlib import Path
from dataclasses import asdict
import hashlib
import json
import re

from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode
from zodiac_v2.output import output_paths

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
OUTPUTS = output_paths(245, ROOT.parent / '七类数据统一归纳', ROOT.parent / '七类数据统一归纳失败')
FILES = [ROOT / 'sites.json', ROOT / 'recent_10_cache.json', *vars(OUTPUTS).values()] if hasattr(OUTPUTS, '__dict__') else [ROOT / 'sites.json', ROOT / 'recent_10_cache.json', OUTPUTS.existing_success, OUTPUTS.new_success, OUTPUTS.existing_failure, OUTPUTS.new_failure]

def hashes():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in FILES}

def selected(sites):
    found = []
    for path in (OUTPUTS.existing_failure, OUTPUTS.new_failure):
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            m = re.match(r'^(.+?)\s+(top|bottom)\s+(https?://\S+)\s+原因：', line)
            if not m:
                continue
            matches = [s for s in sites if (s.name, s.direction.value, s.url) == m.groups()]
            assert len(matches) == 1, (line, len(matches))
            found.extend(matches)
    assert len({s.identity for s in found}) == len(found)
    return tuple(found)

def main():
    before = hashes()
    sites, scraper = _runtime(ROOT / 'sites.json')
    targets = selected(sites)
    print('TARGETS', [s.name for s in targets], flush=True)
    results = scraper.scrape_sites(targets, 245, RunMode.READ_ONLY, workers=4)
    for result in results:
        data = asdict(result)
        if not result.documents and result.site.api_url:
            try:
                data['unbound_bundle'] = asdict(scraper._fetch(result.site, 30))
            except Exception as exc:
                data['unbound_error'] = str(exc)
        (EVIDENCE / (result.site.name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(result.site.name, result.candidate.zodiac if result.ok else result.reason, flush=True)
    assert before == hashes(), '正式文件在只读验证期间发生变化'
    (EVIDENCE / 'protected_hashes.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    print('READ_ONLY_HASHES_UNCHANGED', flush=True)

if __name__ == '__main__':
    main()
