from __future__ import annotations

import json
from dataclasses import replace

import pytest

import zodiac_v2.cli as cli
import zodiac_v2.services.formal as formal
from zodiac_v2.cache import update_recent_cache, validate_cache_data
from zodiac_v2.contracts import Candidate, DocumentType, RunMode, SiteSection, SourceBundle, SourceDocument, WritePermit
from zodiac_v2.services.repair import sites_from_failure_text
from zodiac_v2.services.scrape import ScrapeService, cache_record_from_result
from test_review_output import all_output_paths, failure, make_site, paths_at, seed, success

PERMIT = WritePermit.formal_single(250)


def cache_seed(path, results=()):
    data = {"window_back_periods": 10, "latest_period": 250, "sites": []}
    if results:
        data = update_recent_cache(data, (cache_record_from_result(r) for r in results), current_period=250, permit=PERMIT)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.read_bytes()


def test_full_requires_explicit_scope_without_touching_outputs(tmp_path):
    paths=paths_at(tmp_path);before=seed(paths)
    with pytest.raises(ValueError, match='expected_sites'):
        formal.commit_formal_single((success(),),cache_path=tmp_path/'cache.json',paths=paths,permit=PERMIT)
    assert before == {p:p.read_bytes() for p in before}


@pytest.mark.parametrize('case', ['empty', 'subset', 'extra', 'duplicate', 'changed_config', 'period', 'readonly'])
def test_scope_rejections_have_no_file_side_effects(tmp_path, case):
    paths=paths_at(tmp_path);before=seed(paths)
    site=make_site();rows=(success(site),);expected=(site,)
    if case=='empty': rows=()
    if case=='subset': expected=(site,make_site('遗漏站'))
    if case=='extra': rows=(*rows,success(make_site('额外站')))
    if case=='duplicate': rows=(*rows,success(site,zodiac='牛'))
    if case=='changed_config': expected=(replace(site,parser_id='changed'),)
    if case=='period': rows=(success(site,period=249),)
    if case=='readonly': rows=(success(site,formal=False),)
    with pytest.raises((ValueError, PermissionError)):
        formal.commit_full_formal_single(rows,expected_sites=expected,cache_path=tmp_path/'cache.json',paths=paths,permit=PERMIT)
    assert before == {p:p.read_bytes() for p in before}
    assert not (tmp_path/'cache.json').exists()


def test_failed_retry_preserves_cache_and_all_success_bytes(tmp_path):
    paths=paths_at(tmp_path);before=seed(paths);cache=tmp_path/'cache.json'
    original=cache_seed(cache,(success(),success(make_site('其他站'),zodiac='牛')))
    formal.commit_targeted_formal_single((failure(),),expected_sites=(make_site(),),cache_path=cache,paths=paths,permit=PERMIT)
    assert cache.read_bytes()==original
    for p in (paths.existing_success,paths.new_success,paths.new_failure):
        assert p.read_bytes()==before[p]


def test_targeted_mixed_batch_updates_only_successful_selected_cache(tmp_path):
    paths=paths_at(tmp_path);seed(paths);cache=tmp_path/'cache.json'
    untouched=success(make_site('其他站'),zodiac='牛')
    failed=success(make_site('复抓失败站'),zodiac='狗')
    cache_seed(cache,(untouched,failed))
    before=json.loads(cache.read_text())
    rows=(success(),failure(failed.site))
    formal.commit_targeted_formal_single(rows,expected_sites=tuple(r.site for r in rows),cache_path=cache,paths=paths,permit=PERMIT)
    after=validate_cache_data(json.loads(cache.read_text()))
    for entry in before['sites']:
        assert entry == next(s for s in after['sites'] if s['name']==entry['name'])
    assert next(s for s in after['sites'] if s['name']=='目标站')['records'][0]['zodiac']=='鼠'


@pytest.mark.parametrize(('count','changed'),[(17,False),(18,True),(0,False)])
def test_full_gate_is_strictly_above_85_percent(tmp_path,count,changed):
    cache=tmp_path/'cache.json';original=cache_seed(cache)
    sites=tuple(make_site(str(i)) for i in range(20))
    rows=tuple(success(s) if i<count else failure(s) for i,s in enumerate(sites))
    formal.commit_full_formal_single(rows,expected_sites=sites,cache_path=cache,paths=paths_at(tmp_path),permit=PERMIT)
    assert (cache.read_bytes()!=original)==changed
    assert all(p.exists() for p in all_output_paths(paths_at(tmp_path)))


def test_cache_batch_validation_runs_once(tmp_path,monkeypatch):
    cache=tmp_path/'cache.json';cache_seed(cache)
    rows=tuple(success(make_site(str(i))) for i in range(12))
    calls=[];original=formal.update_recent_cache
    def tracked(data,records,**kwargs):
        materialized=tuple(records);calls.append(len(materialized))
        return original(data,materialized,**kwargs)
    monkeypatch.setattr(formal,'update_recent_cache',tracked)
    formal.commit_full_formal_single(rows,expected_sites=tuple(r.site for r in rows),cache_path=cache,paths=paths_at(tmp_path),permit=PERMIT)
    assert calls==[12]


def test_cache_conflict_does_not_change_live_result(tmp_path,capsys):
    cache=tmp_path/'cache.json';cache_seed(cache,(success(zodiac='牛'),))
    before=cache.read_bytes();r=success()
    result=formal.commit_full_formal_single((r,),expected_sites=(r.site,),cache_path=cache,paths=paths_at(tmp_path),permit=PERMIT)
    assert result==(r,) and result[0].ok
    assert cache.read_bytes()==before
    assert '鼠 目标站' in paths_at(tmp_path).existing_success.read_text()
    assert '缓存同期冲突' in capsys.readouterr().out


class Gateway:
    def http(self,site,timeout):
        doc=SourceDocument('杀肖\n250期：鼠',site.url,DocumentType.HTML,0,'local',0)
        return SourceBundle((doc,),scan_complete=True)
    def embedded(self,site,bundle,timeout): return bundle


class Parser:
    def parse(self,site,bundle):
        return (Candidate(250,'鼠','250期：鼠','local',1,('section:杀肖','anchor-line:0','block-range:0-2')),)


def test_retry_cli_reaches_real_formal_evaluation_and_targeted_commit(tmp_path,monkeypatch):
    site=make_site();other=make_site('其他站');paths=paths_at(tmp_path);before=seed(paths)
    cache=tmp_path/'cache.json';cache_seed(cache)
    errors=tmp_path/'errors.txt';errors.write_text(f'{site.name} top {site.url} 原因：[网络失败] 失败\n',encoding='utf-8-sig')
    scraper=ScrapeService(Gateway(),Parser());calls=[];original=scraper.scrape_sites
    def tracked(*args,**kwargs):
        calls.append((args,kwargs));return original(*args,**kwargs)
    monkeypatch.setattr(scraper,'scrape_sites',tracked)
    monkeypatch.setattr(cli,'_runtime',lambda _:((site,other),scraper))
    def forbidden(*a,**kw): raise AssertionError('retry must never call full commit')
    monkeypatch.setattr(cli,'commit_formal_single',forbidden)
    assert cli.main(('retry','--period','250','--formal','--retry-errors',str(errors),'--cache-file',str(cache),
                     '--success-dir',str(paths.existing_success.parent),'--failure-dir',str(paths.existing_failure.parent),
                     '--timeout','7','--workers','2'))==0
    assert calls[0][0][2] is RunMode.FORMAL_SINGLE
    assert calls[0][0][0]==(site,) and calls[0][1]['timeout']==7 and calls[0][1]['workers']==2
    assert paths.new_success.read_bytes()==before[paths.new_success]
    assert '牛 其他站' in paths.existing_success.read_text()
    assert len(json.loads(cache.read_text())['sites'])==1


def test_empty_retry_never_calls_scraper_or_writer(tmp_path,monkeypatch):
    errors=tmp_path/'errors.txt';errors.write_text('无\n')
    monkeypatch.setattr(cli,'_runtime',lambda _:((make_site(),),object()))
    assert cli.main(('retry','--period','250','--formal','--retry-errors',str(errors)))==2


def test_failure_selector_rejects_ambiguous_or_changed_identity():
    a=make_site('甲');b=replace(a,name='乙')
    with pytest.raises(ValueError): sites_from_failure_text(a.url,(a,b))
    with pytest.raises(ValueError): sites_from_failure_text(f'未知 top {a.url}',(a,))
    with pytest.raises(ValueError): sites_from_failure_text(f'甲 bottom {a.url}',(a,))
    assert sites_from_failure_text(f'甲 top {a.url}',(a,b))==(a,)


@pytest.mark.parametrize(('flag','value'),[('--workers','0'),('--workers','-1'),('--timeout','nan'),('--timeout','inf'),('--timeout','0')])
def test_cli_rejects_invalid_execution_budget(flag,value):
    with pytest.raises(SystemExit): cli.parse_args(('single','--period','250',flag,value))


def test_cache_legacy_empty_entry_without_records_can_be_updated(tmp_path):
    r=success();cache=tmp_path/'cache.json'
    cache.write_text(json.dumps({'window_back_periods':10,'latest_period':250,'sites':[
        {'name':r.site.name,'url':r.site.url,'pick':'top','section':'已有站点','fingerprint':''}]}))
    formal.commit_targeted_formal_single((r,),expected_sites=(r.site,),cache_path=cache,paths=paths_at(tmp_path),permit=PERMIT)
    assert json.loads(cache.read_text())['sites'][0]['records']==[{'period':250,'zodiac':'鼠'}]


def test_targeted_commit_does_not_quarantine_unselected_invalid_cache(tmp_path,capsys):
    cache=tmp_path/'cache.json';cache_seed(cache,(success(make_site('未选中站')),))
    data=json.loads(cache.read_text());data['sites'][0]['fingerprint']='损坏'
    cache.write_text(json.dumps(data));before=cache.read_bytes()
    r=success()
    rows=formal.commit_targeted_formal_single((r,),expected_sites=(r.site,),cache_path=cache,paths=paths_at(tmp_path),permit=PERMIT)
    assert rows[0].ok and cache.read_bytes()==before
    assert '鼠 目标站' in paths_at(tmp_path).existing_success.read_text()
    assert '缓存更新未完成' in capsys.readouterr().out


def test_cache_path_cannot_alias_an_output_file(tmp_path):
    paths=paths_at(tmp_path);before=seed(paths);r=success()
    with pytest.raises(ValueError,match='重合'):
        formal.commit_full_formal_single((r,),expected_sites=(r.site,),cache_path=paths.existing_success,paths=paths,permit=PERMIT)
    assert before=={p:p.read_bytes() for p in before}
