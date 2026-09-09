from __future__ import annotations

import json
import multiprocessing
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from zodiac_v2.contracts import Candidate, Direction, DocumentType, FailureCode, RunMode, ScrapeResult, SiteConfig, SiteSection, SourceBundle, SourceDocument, WritePermit
from zodiac_v2.output import build_output_payloads, output_paths
from zodiac_v2.services.persistence import commit_full_formal_single, commit_targeted_formal_single
from zodiac_v2.services.scrape import DefaultSourceGateway, ScrapeService, commit_formal_single
from zodiac_v2.source.http import HttpResponse, RequestsTransport, SourceFetchCode, SourceFetchError
from zodiac_v2.storage import atomic_batch_write, locked_paths, recover_transaction


def site(name='target', section=SiteSection.NEW, policy='http_documents'):
    return SiteConfig(name, f'https://example.test/source/{name}', Direction.TOP, section, 'test', policy)


class Parser:
    def parse(self, configured, bundle):
        from zodiac_v2.parsers.common import document_lines
        rows = []
        for document in bundle.documents:
            lines = document_lines(document)
            for index, line in enumerate(lines):
                for match in re.finditer(r'(\d+)期：([鼠牛虎兔龙蛇马羊猴鸡狗猪])', line.text):
                    rows.append(Candidate(int(match[1]), match[2], match[0], document.source_id,
                        document.page_order * 1_000_000 + index,
                        ('section:杀肖', 'anchor-line:0', f'block-range:0-{len(lines)}'), record_id=document.record_id))
        return tuple(rows)


def bundle(text, configured=None):
    configured = configured or site()
    return SourceBundle((SourceDocument('栏目：杀肖\n' + text, configured.url, DocumentType.HTML, 0, 'test-source', 0),))


class Gateway:
    def __init__(self, documents):
        self.documents = list(documents)
        self.index = 0
    def http(self, configured, timeout):
        result = self.documents[min(self.index, len(self.documents) - 1)]
        self.index += 1
        return result
    def embedded(self, configured, value, timeout):
        return value


def success(configured=None, *, period=224, zodiac='鼠', mode=RunMode.FORMAL_SINGLE):
    configured = configured or site()
    return ScrapeService(Gateway((bundle(f'{period}期：{zodiac}', configured),)), Parser()).scrape_site(configured, period, mode)


def failure(configured=None, period=224):
    return ScrapeResult.failure(configured or site(), period, FailureCode.NETWORK, 'temporary failure', ())


def prepared(tmp_path):
    paths = output_paths(224, tmp_path / 'success', tmp_path / 'failure')
    cache = tmp_path / 'cache.json'
    cache.write_text(json.dumps({'window_back_periods': 10, 'latest_period': 224, 'sites': []}), encoding='utf-8')
    for path in (paths.existing_success, paths.new_success, paths.existing_failure, paths.new_failure):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('无\n', encoding='utf-8')
    return paths, cache


def snapshot(paths, cache):
    return {path: path.read_bytes() for path in (paths.existing_success, paths.new_success, paths.existing_failure, paths.new_failure, cache)}


@pytest.mark.parametrize('kind', ['empty', 'subset', 'duplicate', 'foreign', 'readonly', 'wrong-period', 'changed-config'])
def test_full_scope_failure_touches_no_production_bytes(tmp_path, kind):
    paths, cache = prepared(tmp_path)
    a, b = site('a'), site('b')
    rows = [success(a), success(b)]
    if kind == 'empty': rows = []
    elif kind == 'subset': rows = rows[:1]
    elif kind == 'duplicate': rows = [rows[0], rows[0]]
    elif kind == 'foreign': rows[1] = success(site('foreign'))
    elif kind == 'readonly': rows[1] = success(b, mode=RunMode.READ_ONLY)
    elif kind == 'wrong-period': rows[1] = success(b, period=225)
    elif kind == 'changed-config': rows[1] = success(replace(b, api_url='https://example.test/other-api'))
    before = snapshot(paths, cache)
    with pytest.raises((ValueError, PermissionError)):
        commit_full_formal_single(rows, expected_sites=(a, b), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert snapshot(paths, cache) == before


def test_legacy_full_commit_cannot_infer_authorized_scope(tmp_path):
    paths, cache = prepared(tmp_path)
    with pytest.raises(ValueError, match='expected_sites'):
        commit_formal_single((success(),), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))


def test_output_builder_rejects_empty_and_duplicate_site(tmp_path):
    paths, _ = prepared(tmp_path)
    with pytest.raises(ValueError): build_output_payloads((), paths)
    with pytest.raises(ValueError): build_output_payloads((success(), success(zodiac='牛')), paths)


def test_targeted_failure_preserves_success_and_cache_byte_for_byte(tmp_path):
    paths, cache = prepared(tmp_path)
    paths.new_success.write_bytes('鼠 target\r\n红色\r\n\r\n生肖次数排行榜\r\n鼠 1次\r\n'.encode())
    before = snapshot(paths, cache)
    commit_targeted_formal_single((failure(),), expected_sites=(site(),), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    after = snapshot(paths, cache)
    assert all(after[path] == data for path, data in before.items() if path != paths.new_failure)
    assert 'temporary failure' in paths.new_failure.read_text(encoding='utf-8')


def test_targeted_success_keeps_unselected_outputs_and_cache_entries(tmp_path):
    paths, cache = prepared(tmp_path)
    a, b = site('a'), site('b')
    commit_full_formal_single((success(a), success(b)), expected_sites=(a, b), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    previous = json.loads(cache.read_text(encoding='utf-8'))
    old_b = next(entry for entry in previous['sites'] if entry['name'] == 'b')
    unselected = (paths.existing_success.read_bytes(), paths.existing_failure.read_bytes())
    commit_targeted_formal_single((success(a),), expected_sites=(a,), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert '鼠 b' in paths.new_success.read_text(encoding='utf-8')
    assert next(entry for entry in json.loads(cache.read_text(encoding='utf-8'))['sites'] if entry['name'] == 'b') == old_b
    assert (paths.existing_success.read_bytes(), paths.existing_failure.read_bytes()) == unselected


def test_targeted_batch_is_preflighted_before_any_file_write(tmp_path):
    paths, cache = prepared(tmp_path)
    a, b = site('a'), site('b')
    paths.new_success.write_text('牛 b\n红色\n\n生肖次数排行榜\n牛 1次\n', encoding='utf-8')
    before = snapshot(paths, cache)
    with pytest.raises(ValueError, match='禁止覆盖'):
        commit_targeted_formal_single((success(a), success(b)), expected_sites=(a, b), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert snapshot(paths, cache) == before


def test_targeted_success_is_not_blocked_by_full_batch_ratio(tmp_path):
    paths, cache = prepared(tmp_path)
    a, b = site('a'), site('b')
    commit_targeted_formal_single((success(a), failure(b)), expected_sites=(a, b), cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert [entry['name'] for entry in json.loads(cache.read_text(encoding='utf-8'))['sites']] == ['a']


def test_full_ratio_85_percent_retains_original_cache(tmp_path):
    paths, cache = prepared(tmp_path)
    configured = tuple(site(f's{i}') for i in range(20))
    results = tuple(success(item) if index < 17 else failure(item) for index, item in enumerate(configured))
    before = cache.read_bytes()
    commit_full_formal_single(results, expected_sites=configured, cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert cache.read_bytes() == before
    assert '鼠 s0' in paths.new_success.read_text(encoding='utf-8')


def test_cache_batch_update_called_once(tmp_path, monkeypatch):
    import zodiac_v2.services.persistence as persistence
    paths, cache = prepared(tmp_path)
    original = persistence.update_recent_cache
    calls = []
    def update(data, records, **kwargs):
        records = tuple(records)
        calls.append(len(records))
        return original(data, records, **kwargs)
    monkeypatch.setattr(persistence, 'update_recent_cache', update)
    configured = tuple(site(f's{i}') for i in range(6))
    commit_full_formal_single(tuple(success(item) for item in configured), expected_sites=configured, cache_path=cache, paths=paths, permit=WritePermit.formal_single(224))
    assert calls == [6]


def test_retry_cli_uses_formal_mode_and_only_targeted_commit(tmp_path, monkeypatch):
    import zodiac_v2.cli as cli
    a, b = site('a'), site('b')
    errors = tmp_path / 'errors.txt'
    errors.write_text(f'a top {a.url} 原因：[网络失败] old\n', encoding='utf-8')
    calls = []
    class Scraper:
        def scrape_sites(self, selected, period, mode, **kwargs):
            calls.append((selected, period, mode, kwargs))
            return (success(a),)
    monkeypatch.setattr(cli, '_runtime', lambda path: ((a, b), Scraper()))
    def forbidden(*args, **kwargs): raise AssertionError('full batch commit called by retry')
    def target(results, **kwargs):
        assert kwargs['expected_sites'] == (a,)
        return results
    monkeypatch.setattr(cli, 'commit_formal_single', forbidden)
    monkeypatch.setattr(cli, 'commit_targeted_formal_single', target)
    assert cli.main(('retry', '--period', '224', '--formal', '--retry-errors', str(errors), '--timeout', '3', '--workers', '2')) == 0
    assert calls == [((a,), 224, RunMode.FORMAL_SINGLE, {'timeout': 3.0, 'workers': 2})]


def test_empty_retry_cli_does_not_commit(tmp_path, monkeypatch):
    import zodiac_v2.cli as cli
    errors = tmp_path / 'errors.txt'
    errors.write_text('无\n', encoding='utf-8')
    monkeypatch.setattr(cli, '_runtime', lambda path: ((site(),), object()))
    assert cli.main(('retry', '--period', '224', '--formal', '--retry-errors', str(errors))) == 2


def test_failure_selector_never_falls_back_to_another_name():
    from zodiac_v2.services.repair import sites_from_failure_text
    configured = site()
    with pytest.raises(ValueError):
        sites_from_failure_text(f'unknown top {configured.url} 原因：network', (configured,))


@pytest.mark.parametrize('bad', ['nan', 'inf', '-1', '0'])
def test_cli_rejects_nonfinite_timeout(bad):
    from zodiac_v2.cli import parse_args
    with pytest.raises(SystemExit): parse_args(('single', '--period', '224', '--timeout', bad))


def test_onboard_small_period_never_builds_zero_or_negative_periods(monkeypatch):
    import zodiac_v2.cli as cli
    calls = []
    monkeypatch.setattr(cli, '_runtime', lambda path: ((), object()))
    monkeypatch.setattr(cli, 'load_recent_cache', lambda path: {})
    def validate(scraper, candidate, existing, cache, periods, **kwargs):
        calls.append(periods)
        return SimpleNamespace(reasons=(), accepted=True)
    monkeypatch.setattr(cli, 'validate_new_site', validate)
    assert cli.main(('onboard', '--name', 'x', '--url', 'https://example.test/x', '--period', '3')) == 0
    assert calls == [(3, 2, 1)]


def test_consensus_cannot_hide_one_conflicting_capture():
    configured = site(policy='http_consensus')
    source = Gateway((bundle('224期：鼠'), bundle('224期：鼠'), bundle('224期：鼠\n224期：牛')))
    result = ScrapeService(source, Parser()).scrape_site(configured, 224)
    assert result.failure_code is FailureCode.CONFLICT


def test_consensus_sees_next_period_away_from_edge():
    configured = site(policy='http_consensus')
    source = Gateway((bundle('224期：鼠'), bundle('224期：鼠'), bundle('224期：鼠\n225期：牛\n223期：虎')))
    result = ScrapeService(source, Parser()).scrape_site(configured, 224)
    assert result.failure_code is FailureCode.DIRECTION


def test_consensus_two_confirmations_without_conflict_succeeds():
    configured = site(policy='http_consensus')
    assert ScrapeService(Gateway((bundle('224期：鼠'),)), Parser()).scrape_site(configured, 224).ok


def test_all_newer_incomplete_candidates_returns_boundary_not_index_error():
    from zodiac_v2.validation.conflicts import _direction_window
    candidate = Candidate(225, '鼠', '225期：鼠', 'doc', 0, ('record-status:incomplete',))
    _, decision = _direction_window((candidate,), Direction.TOP, 224)
    assert decision.failure_code is FailureCode.BOUNDARY


def test_pagination_follows_first_page_with_only_newer_issues():
    base = 'https://example.test/list.aspx?id=79&page='
    detail = 'https://example.test/article.aspx?id=2'
    def html(page):
        return f'<a href="/article.aspx?id={page}">{226-page}期: keyword</a><a href="/list.aspx?id=79&page={page+1}">下一页</a>'
    calls = []
    class Transport:
        def request(self, url, **kwargs):
            calls.append(url)
            text = '224期：鼠' if url == detail else html(int(url.rsplit('=', 1)[-1]))
            return HttpResponse(200, url, text.encode(), (('Content-Type', 'text/html; charset=utf-8'),))
    configured = SiteConfig('keyword', base + '1', Direction.TOP, SiteSection.NEW, 'test', 'http_period_keyword_article', article_keyword='keyword')
    first = SourceBundle((SourceDocument(html(1), configured.url, DocumentType.HTML, 0, 'list', 0),))
    result = DefaultSourceGateway(Transport()).period_keyword_article(configured, first, 224, 10)
    assert calls == [base + '2', base + '3', detail]
    assert result.documents[0].final_url == detail
    assert result.scan_complete


def test_anchor_window_cannot_borrow_value_after_stop():
    from zodiac_v2.parsers.families import AnchoredSectionFamilyParser, AnchoredSectionSpec
    configured = site()
    parser = AnchoredSectionFamilyParser({'target': AnchoredSectionSpec('栏目A', r'(\d+)期：\s*结束\s*([鼠牛])', stop_pattern='结束', record_window_lines=3)})
    document = SourceDocument('栏目A\n224期：\n结束\n鼠', configured.url, DocumentType.HTML, 0, 'a', 0)
    assert parser.parse(configured, SourceBundle((document,))) == ()


def test_anchor_proves_actual_block_end():
    from zodiac_v2.parsers.families import AnchoredSectionFamilyParser, AnchoredSectionSpec
    configured = site()
    parser = AnchoredSectionFamilyParser({'target': AnchoredSectionSpec('栏目A', r'(\d+)期：([鼠牛])', stop_pattern='结束')})
    document = SourceDocument('栏目A\n224期：鼠\n结束\n225期：牛', configured.url, DocumentType.HTML, 0, 'a', 0)
    rows = parser.parse(configured, SourceBundle((document,)))
    assert len(rows) == 1 and 'section-range:0-2' in rows[0].evidence


def test_record_id_mismatch_is_rejected():
    from zodiac_v2.validation.evidence import validate_candidate_evidence
    configured = site()
    document = SourceDocument('栏目：杀肖\n224期：鼠', configured.url, DocumentType.JSON, 0, 'a', 0, 'expected')
    candidate = Candidate(224, '鼠', '224期：鼠', 'a', 1, ('section:杀肖',), record_id='other')
    assert validate_candidate_evidence(candidate, SourceBundle((document,))).failure_code is FailureCode.SOURCE_IDENTITY


def test_browser_projects_only_unique_article_not_whole_array():
    from zodiac_v2.source.browser import BrowserCapture, BrowserResponse, browser_documents
    url = 'https://example.test/article/admin/abc'
    api = 'https://example.test/api/proxy/admin-articles/abc'
    data = json.dumps([{'id': 'abc', 'content': '224期：鼠'}, {'id': 'other', 'content': '224期：牛'}])
    class Renderer:
        def capture(self, requested, **kwargs):
            return BrowserCapture(url, 'shell', (BrowserResponse(api, 200, 'application/json', data),))
    result = browser_documents(Renderer(), url, allowed_response_urls=(api,))
    assert len(result.documents) == 2
    assert json.loads(result.documents[1].text) == {'id': 'abc', 'content': '224期：鼠'}
    assert result.documents[1].record_id == 'abc'


def test_identity_cannot_be_borrowed_from_foreign_article_recommendations():
    from zodiac_v2.source.documents import source_identity
    from zodiac_v2.source.identity_records import IdentityRecordMissing, project_response_record
    with pytest.raises(IdentityRecordMissing):
        project_response_record(json.dumps({'id': 'other', 'content': '224期：牛', 'data': {'id': 'abc', 'content': '224期：鼠'}}), source_identity('https://example.test/article/admin/abc'))


def test_conflicting_same_id_json_is_rejected():
    from zodiac_v2.source.documents import SourceIdentityError, source_identity
    from zodiac_v2.source.identity_records import project_response_record
    with pytest.raises(SourceIdentityError, match='冲突'):
        project_response_record(json.dumps([{'id': 'abc', 'content': '鼠'}, {'id': 'abc', 'content': '牛'}]), source_identity('https://example.test/article/admin/abc'))


def test_user_projection_keeps_only_owned_posts():
    from zodiac_v2.source.documents import source_identity
    from zodiac_v2.source.identity_records import project_response_record
    body = json.dumps([{'id': 1, 'user_id': 7, 'content': '鼠'}, {'id': 2, 'user_id': 7, 'content': '牛'}, {'id': 3, 'user_id': 8, 'content': '虎'}])
    projected = json.loads(project_response_record(body, source_identity('https://example.test/#/users/7')))
    assert [row['id'] for row in projected] == [1, 2]


def test_tls_failure_never_retries_without_verification(monkeypatch):
    import requests
    calls = []
    def request(self, url, **kwargs):
        calls.append(kwargs['verify'])
        raise requests.exceptions.SSLError('certificate error')
    monkeypatch.setattr(RequestsTransport, '_request', request)
    with pytest.raises(SourceFetchError):
        RequestsTransport(insecure_tls_hosts={'example.test'}).request('https://example.test/', timeout=1, max_bytes=100)
    assert calls == [True]


def test_api_404_path_tries_http_before_browser():
    configured = replace(site(policy='http_then_browser'), url='https://example.test/article/admin/abc')
    calls = []
    class Sources(Gateway):
        def article_api(self, configured, timeout):
            calls.append('api')
            return ()
        def http(self, configured, timeout):
            calls.append('http')
            return bundle('224期：鼠', configured)
        def browser(self, configured, timeout):
            raise AssertionError('Complete HTTP must not start browser')
    result = ScrapeService(Sources(()), Parser()).scrape_site(configured, 224)
    assert result.ok and calls == ['api', 'http']


def test_repeated_source_rejected_but_different_approved_columns_remain(tmp_path):
    from zodiac_v2.config import ConfigError, load_sites
    records = [dict(name=name, url='https://example.test/list.aspx?id=79&page=1', pick='top', section='已有站点', parser_id='test', source_policy='http_documents') for name in ('a', 'b')]
    config = tmp_path / 'sites.json'
    config.write_text(json.dumps(records), encoding='utf-8')
    with pytest.raises(ConfigError, match='同一来源'):
        load_sites(config, parser_ids={'test'}, source_policies={'http_documents'})
    for row in records:
        row.update(source_policy='http_period_keyword_article', article_keyword=row['name'])
    config.write_text(json.dumps(records), encoding='utf-8')
    assert len(load_sites(config, parser_ids={'test'}, source_policies={'http_period_keyword_article'})) == 2


def test_output_replace_failure_restores_all_originals(tmp_path, monkeypatch):
    import zodiac_v2.storage as storage
    a, b = tmp_path / 'a.txt', tmp_path / 'b.txt'
    a.write_bytes(b'old-a'); b.write_bytes(b'old-b')
    original_replace = storage.os.replace
    state = {'failed': False}
    def replace_once(source, destination):
        if Path(destination) == b and not state['failed']:
            state['failed'] = True
            raise OSError('injected replacement failure')
        return original_replace(source, destination)
    monkeypatch.setattr(storage.os, 'replace', replace_once)
    with pytest.raises(OSError): atomic_batch_write({a: b'new-a', b: b'new-b'})
    assert a.read_bytes() == b'old-a' and b.read_bytes() == b'old-b'
    assert not list(tmp_path.glob('.zodiac-txn-*.json'))
    assert not list(tmp_path.glob('*.tmp'))


def test_pending_transaction_blocks_new_output_until_explicit_recovery(tmp_path):
    import hashlib
    target, backup = tmp_path / 'a.txt', tmp_path / '.a.bak'
    target.write_bytes(b'new'); backup.write_bytes(b'old')
    journal = tmp_path / '.zodiac-txn-test.json'
    journal.write_text(json.dumps({'version': 1, 'files': [{'path': str(target), 'backup': str(backup), 'old_sha256': hashlib.sha256(b'old').hexdigest(), 'new_sha256': hashlib.sha256(b'new').hexdigest()}]}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='未完成事务'): atomic_batch_write({target: b'other'})
    recover_transaction(journal)
    assert target.read_bytes() == b'old' and not journal.exists()


def _hold_lock(path, ready, release):
    with locked_paths((Path(path),)):
        ready.set()
        release.wait(10)


def test_process_lock_prevents_overlapping_writers(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    ready, release = ctx.Event(), ctx.Event()
    path = tmp_path / 'cache.json'
    process = ctx.Process(target=_hold_lock, args=(str(path), ready, release))
    process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(RuntimeError, match='已有正式写入任务'):
            with locked_paths((path,)):
                raise AssertionError('second writer acquired lock')
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join()
    assert process.exitcode == 0


def test_browser_content_length_is_checked_before_text_read(monkeypatch):
    from zodiac_v2.source.browser import PlaywrightBrowserRenderer
    api = 'https://example.test/api/data'
    class Response:
        url = api
        status = 200
        def header_value(self, name): return 'application/json' if name == 'content-type' else '999999999'
        def text(self): raise AssertionError('oversized body was read')
    class Page:
        url = 'https://example.test/'
        def on(self, name, callback): self.callback = callback
        def goto(self, *args, **kwargs): self.callback(Response()); return None
        def wait_for_load_state(self, *args, **kwargs): pass
        def content(self): return 'ok'
    page = Page()
    class Context:
        def route(self, *args): pass
        def new_page(self): return page
    class Browser:
        def new_context(self, **kwargs): return Context()
        def close(self): pass
    class Playwright:
        def __enter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))
        def __exit__(self, *args): pass
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(sync_playwright=Playwright))
    with pytest.raises(SourceFetchError) as caught:
        PlaywrightBrowserRenderer().capture(page.url, timeout=2, allowed_response_urls=(api,))
    assert caught.value.code is SourceFetchCode.TOO_LARGE
