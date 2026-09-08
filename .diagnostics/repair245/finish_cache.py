"""Finish only persistence of the completed formal run; never refetch or rewrite TXT."""
import json
import msvcrt

from probe import ROOT, EVIDENCE, OUTPUTS, hashes
from verify import EXPECTED
from zodiac_v2.cache import update_recent_cache, write_recent_cache
from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import DocumentType, RunMode, SourceBundle, SourceDocument, WritePermit
from zodiac_v2.services.scrape import cache_record_from_result


sites, scraper = _runtime(ROOT / 'sites.json')
before = hashes()
results = []
for site in sites:
    if site.name not in EXPECTED:
        continue
    saved = json.loads((EVIDENCE / (site.name + '-formal.json')).read_text(encoding='utf-8'))
    assert saved['target_period'] == 245 and saved['writable'] and saved['validation_receipt']
    docs = tuple(SourceDocument(**{**d, 'document_type': DocumentType(d['document_type'])}) for d in saved['documents'])
    # Recheck the captured formal-run evidence with the unified validator, not cache or TXT.
    result = scraper._evaluate(site, 245, SourceBundle(docs, (), scan_complete=True), RunMode.FORMAL_SINGLE)
    assert result.ok and result.candidate.zodiac == EXPECTED[site.name]
    assert result.candidate.raw_line == saved['candidate']['raw_line']
    success = OUTPUTS.existing_success if site.section.value == '已有站点' else OUTPUTS.new_success
    assert f'{EXPECTED[site.name]} {site.name}' in success.read_text(encoding='utf-8').splitlines()
    results.append(result)
assert len(results) == 5
cache_path = ROOT / 'recent_10_cache.json'
with cache_path.with_name(cache_path.name + '.lock').open('a+b') as lock:
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    cache_bytes = cache_path.read_bytes()
    assert cache_bytes == (EVIDENCE / 'before-formal' / cache_path.name).read_bytes()
    old = json.loads(cache_bytes)
    permit = WritePermit.formal_single(245)
    updated = update_recent_cache(old, [cache_record_from_result(r) for r in results], current_period=245, permit=permit)
    assert len(old['sites']) == len(updated['sites'])
    evicted = {}
    unchanged_fragments = []
    for a, b in zip(old['sites'], updated['sites']):
        assert a['name'] == b['name']
        if a['name'] not in EXPECTED:
            assert a == b
            fragment = ('    ' + json.dumps(a, ensure_ascii=False, indent=2).replace('\n', '\n    ')).encode()
            assert fragment in cache_bytes
            unchanged_fragments.append(fragment)
        else:
            assert b['records'][0] == {'period': 245, 'zodiac': EXPECTED[a['name']]}
            assert b['records'][1:] == a['records'][:9]
            assert not b['error']
            evicted[a['name']] = a['records'][9:]
    assert {k:v for k,v in old.items() if k != 'sites'} == {k:v for k,v in updated.items() if k != 'sites'}
    assert hashes() == before
    write_recent_cache(cache_path, updated, permit)
    written = cache_path.read_bytes()
    assert json.loads(written) == updated
    assert all(fragment in written for fragment in unchanged_fragments)
after = hashes()
assert all(after[p] == h for p, h in before.items() if p != str(cache_path))
report = {'period': 245, 'updated': EXPECTED, 'unrelated_cache_entries_unchanged': len(unchanged_fragments),
          'normal_10_record_window_evictions': evicted, 'hashes': after}
(EVIDENCE / 'commit-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
