"""One authorized 245 repair batch. No all-site entry point or historical writes."""
from contextlib import ExitStack
from dataclasses import asdict
import json
import msvcrt
from pathlib import Path
import tempfile

from probe import ROOT, EVIDENCE, OUTPUTS, hashes
from verify import EXPECTED
from zodiac_v2.cache import update_recent_cache, write_recent_cache
from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode, WritePermit
from zodiac_v2.output import merge_formal_single_result_output, output_paths
from zodiac_v2.services.scrape import cache_record_from_result


def prefix(text):
    return text.replace('\r\n', '\n').split('内容\t次数\t排名', 1)[0].rstrip('\r\n')


def main():
    verified = json.loads((EVIDENCE / 'verification.json').read_text(encoding='utf-8'))
    assert {r['site']: r['zodiac'] for r in verified} == EXPECTED
    sites, scraper = _runtime(ROOT / 'sites.json')
    targets = tuple(s for s in sites if s.name in EXPECTED)
    assert len(targets) == 5
    before_fetch = hashes()
    results = scraper.scrape_sites(targets, 245, RunMode.FORMAL_SINGLE, workers=3)
    passing = []
    for result in results:
        (EVIDENCE / (result.site.name + '-formal.json')).write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print('FORMAL', result.site.name, result.candidate.zodiac if result.ok else result.reason, flush=True)
        if result.ok:
            assert result.writable and result.validator_issued
            assert result.candidate.zodiac == EXPECTED[result.site.name], '验证与正式结果不一致'
            passing.append(result)
    assert before_fetch == hashes(), '运行期间正式数据变化；尚未写入，请重新合并最新文件'
    assert passing, '无正式通过站点'
    permit = WritePermit.formal_single(245)
    paths = [OUTPUTS.existing_success, OUTPUTS.new_success, OUTPUTS.existing_failure, OUTPUTS.new_failure]
    with ExitStack() as stack:
        for path in [ROOT / 'recent_10_cache.json', *paths]:
            lock = stack.enter_context(path.with_name(path.name + '.lock').open('a+b'))
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        original = {p: p.read_bytes() for p in paths}
        backup = EVIDENCE / 'before-formal'
        backup.mkdir(exist_ok=True)
        for path, data in original.items():
            (backup / path.name).write_bytes(data)
        with tempfile.TemporaryDirectory(prefix='output-preflight-', dir=EVIDENCE) as directory:
            staging = output_paths(245, Path(directory), Path(directory))
            for path, data in original.items():
                (Path(directory) / path.name).write_bytes(data)
            for result in passing:
                merge_formal_single_result_output(result, staging, permit)
            for path in paths[:2]:
                old = original[path].decode('utf-8-sig')
                new = (Path(directory) / path.name).read_text(encoding='utf-8')
                assert prefix(new).startswith(prefix(old)), f'禁止改变原成功内容：{path}'
                rows = [r for r in passing if (r.site.section.value == '已有站点') == (path == OUTPUTS.existing_success)]
                expected_added = [f'{r.candidate.zodiac} {r.site.name}' for r in rows
                                  if f'{r.candidate.zodiac} {r.site.name}' not in prefix(old).splitlines()]
                assert prefix(new)[len(prefix(old)):].split() == ' '.join(expected_added).split()
            for path in paths[2:]:
                old_lines = original[path].decode('utf-8-sig').splitlines()
                new_lines = (Path(directory) / path.name).read_text(encoding='utf-8').splitlines()
                expected = [line for line in old_lines if ' 原因：' in line
                            and not any(line.startswith(r.site.name + ' ') for r in passing)]
                assert [line for line in new_lines if ' 原因：' in line] == expected
            assert all(p.read_bytes() == original[p] for p in paths), '正式输出并发变化'
            for result in passing:
                merge_formal_single_result_output(result, OUTPUTS, permit)
            assert all(p.read_bytes() == (Path(directory) / p.name).read_bytes() for p in paths)
        print('SUCCESS_APPENDED_AND_TARGET_FAILURES_CLEARED', flush=True)
        # Cache is read only after live decisions and TXT finalization.
        cache_path = ROOT / 'recent_10_cache.json'
        cache_bytes = cache_path.read_bytes()
        (backup / cache_path.name).write_bytes(cache_bytes)
        old_cache = json.loads(cache_bytes)
        updated = update_recent_cache(old_cache, [cache_record_from_result(r) for r in passing],
                                      current_period=245, permit=permit)
        names = {r.site.name for r in passing}
        assert len(old_cache['sites']) == len(updated['sites'])
        for old, new in zip(old_cache['sites'], updated['sites']):
            assert old['name'] == new['name']
            if old['name'] not in names:
                assert old == new
                raw = ('    ' + json.dumps(old, ensure_ascii=False, indent=2).replace('\n', '\n    ')).encode()
                assert raw in cache_bytes, f'原缓存格式需保留：{old["name"]}'
            else:
                assert [r for r in old['records'] if r['period'] != 245][:9] == [r for r in new['records'] if r['period'] != 245]
        assert {k: v for k, v in old_cache.items() if k != 'sites'} == {k: v for k, v in updated.items() if k != 'sites'}
        assert cache_path.read_bytes() == cache_bytes
        write_recent_cache(cache_path, updated, permit)
        actual = json.loads(cache_path.read_bytes())
        assert actual == updated
        for old in old_cache['sites']:
            if old['name'] not in names:
                raw = ('    ' + json.dumps(old, ensure_ascii=False, indent=2).replace('\n', '\n    ')).encode()
                assert raw in cache_path.read_bytes()
        report = {'period': 245, 'updated': {r.site.name: r.candidate.zodiac for r in passing},
                  'unrelated_cache_entries_unchanged': len(actual['sites']) - len(names),
                  'hashes': hashes()}
        (EVIDENCE / 'commit-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('COMMITTED', report['updated'], 'UNRELATED_CACHE_UNCHANGED', report['unrelated_cache_entries_unchanged'], flush=True)


if __name__ == '__main__':
    main()
