from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zodiac_v2.contracts import (
    Candidate, Direction, DocumentType, FailureCode, RunMode, ScrapeResult,
    SiteConfig, SiteSection, SourceDocument, WritePermit,
)
from zodiac_v2.output import (
    _format_success_rows, all_output_paths, build_output_payloads, merge_formal_results_output,
    merge_formal_single_result_output, output_journal, output_paths, write_output_payloads,
)
from zodiac_v2.storage import atomic_write_many, locked_paths


def make_site(name='目标站', section=SiteSection.EXISTING):
    return SiteConfig(name, f'https://example.test/{name}', Direction.TOP, section, 'test', 'http_documents')


def success(site=None, *, period=250, zodiac='鼠', formal=True):
    site = site or make_site()
    doc = SourceDocument(f'杀肖\n{period}期：{zodiac}', site.url, DocumentType.HTML, 0, 'test', 0)
    candidate = Candidate(period, zodiac, f'{period}期：{zodiac}', 'test', 1,
                          ('section:杀肖', 'anchor-line:0', 'block-range:0-2'))
    if formal:
        return ScrapeResult._validated_success(site, period, candidate, (doc,))
    return ScrapeResult.success(site, period, candidate, (doc,), writable=False)


def failure(site=None, *, period=250):
    return ScrapeResult.failure(site or make_site(), period, FailureCode.NETWORK, '本次网络失败', ())


def paths_at(root):
    return output_paths(250, root/'success', root/'failure')


def seed(paths):
    contents = ('鼠 目标站\n牛 其他站\n羽墨\n\n生肖次数排行榜\n鼠 1次\n牛 1次\n\n前一期失败统计\n历史附属内容\n',
                '羊 新站\n红色\n',
                '其他失败站 top https://other.test/ 原因：[网络失败] 失败\n',
                '无\n')
    for p, text in zip(all_output_paths(paths), contents):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.replace('\n','\r\n').encode())
    return {p: p.read_bytes() for p in all_output_paths(paths)}


def test_empty_full_payload_is_rejected_before_io(tmp_path):
    paths=paths_at(tmp_path);before=seed(paths)
    with pytest.raises(ValueError, match='为空'):
        build_output_payloads((), paths)
    assert before == {p:p.read_bytes() for p in before}


@pytest.mark.parametrize('second', [lambda:success(), lambda:success(zodiac='牛'), lambda:failure()])
def test_duplicate_site_status_or_value_rejected(tmp_path, second):
    with pytest.raises(ValueError, match='重复站点'):
        build_output_payloads((success(), second()), paths_at(tmp_path))


def test_readonly_success_not_promoted(tmp_path):
    with pytest.raises(PermissionError):
        build_output_payloads((success(formal=False),),paths_at(tmp_path))


def test_targeted_failure_keeps_success_bytes_and_other_section(tmp_path):
    paths=paths_at(tmp_path); before=seed(paths)
    merge_formal_single_result_output(failure(),paths,WritePermit.formal_single(250))
    for p in (paths.existing_success, paths.new_success, paths.new_failure):
        assert p.read_bytes() == before[p]
    text=paths.existing_failure.read_text()
    assert '目标站' in text and '其他失败站' in text


def test_mixed_targeted_results_are_preflighted_before_any_write(tmp_path):
    paths=paths_at(tmp_path); before=seed(paths)
    with pytest.raises(ValueError, match='禁止覆盖'):
        merge_formal_results_output((success(make_site('新增目标',SiteSection.NEW)),success(zodiac='牛')),
                                    paths,WritePermit.formal_single(250))
    assert before == {p:p.read_bytes() for p in before}


def test_targeted_success_retains_raw_details_and_tail(tmp_path):
    paths=paths_at(tmp_path);seed(paths)
    text='鼠   \u200c目标站\n\n牛   其他站\n华林\n羽墨\n\n生肖次数排行榜\n鼠 1次\n\n前一期失败统计\n不要删除\n'
    paths.existing_success.write_text(text)
    merge_formal_results_output((success(),success(make_site('修复站'),zodiac='狗')),paths,
                                WritePermit.formal_single(250))
    written=paths.existing_success.read_text()
    assert '鼠   \u200c目标站\n\n牛   其他站\n华林\n羽墨' in written
    assert written.count('目标站') == 1
    assert written.index('羽墨') < written.index('狗 修复站') < written.index('内容\t次数\t排名')
    assert written.endswith('前一期失败统计\n不要删除\n')


def test_success_removes_selected_old_url_failure_only(tmp_path):
    paths=paths_at(tmp_path);seed(paths)
    paths.existing_failure.write_text('目标站 top https://old.test/ 原因：[网络失败] 旧\n\n其他站 top https://x.test/ 原因：[网络失败] 保留\n')
    merge_formal_single_result_output(success(),paths,WritePermit.formal_single(250))
    assert '目标站' not in paths.existing_failure.read_text()
    assert '其他站' in paths.existing_failure.read_text()


def test_dense_ranking_contract():
    text=_format_success_rows((('狗','甲'),('狗','乙'),('狗','丙'),('马','丁'),('马','戊'),('龙','己'),('龙','庚'),('羊','辛')),SiteSection.EXISTING)
    assert '内容\t次数\t排名\n狗\t3\t1\n马\t2\t2\n龙\t2\t2\n羊\t1\t3\n' in text


@pytest.mark.parametrize('period',[0,-1,10000,True])
def test_output_period_contract(period,tmp_path):
    with pytest.raises(ValueError): output_paths(period,tmp_path,tmp_path)


def test_output_mismatched_result_period_rejected(tmp_path):
    with pytest.raises(PermissionError):build_output_payloads((success(period=249),),paths_at(tmp_path))


def test_full_failure_still_generates_failure_text(tmp_path):
    paths=paths_at(tmp_path)
    write_output_payloads(build_output_payloads((failure(),),paths),WritePermit.formal_single(250))
    assert paths.existing_success.read_text()=='无\n'
    assert '本次网络失败' in paths.existing_failure.read_text()


def test_replace_failure_restores_original_bytes(monkeypatch,tmp_path):
    import zodiac_v2.storage as storage
    paths=paths_at(tmp_path);before=seed(paths)
    replace=storage.os.replace
    failed=False
    def fail_once(src,dst):
        nonlocal failed
        if Path(dst)==paths.new_success and not failed:
            failed=True
            raise OSError('injected replacement failure')
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',fail_once)
    with pytest.raises(OSError,match='injected'):
        write_output_payloads(build_output_payloads((success(),),paths),WritePermit.formal_single(250))
    assert before == {p:p.read_bytes() for p in before}
    assert not output_journal(paths,250).exists()
    assert not list(tmp_path.rglob('*.tmp'))


def test_partial_staging_cleans_scratch_without_touching_originals(monkeypatch,tmp_path):
    import zodiac_v2.storage as storage
    paths=paths_at(tmp_path);before=seed(paths)
    stage=storage.stage_bytes
    calls=0
    def fail_third(path,content):
        nonlocal calls
        calls+=1
        if calls==3:raise OSError('stage failure')
        return stage(path,content)
    monkeypatch.setattr(storage,'stage_bytes',fail_third)
    with pytest.raises(OSError,match='stage failure'):
        write_output_payloads(build_output_payloads((success(),),paths),WritePermit.formal_single(250))
    assert before == {p:p.read_bytes() for p in before}
    assert not list(tmp_path.rglob('*.tmp'))


def test_pending_journal_blocks_even_different_section(tmp_path):
    paths=paths_at(tmp_path);before=seed(paths)
    output_journal(paths,250).write_text('{}')
    with pytest.raises(RuntimeError,match='未完成'):
        merge_formal_single_result_output(success(make_site('新增目标',SiteSection.NEW)),paths,
                                           WritePermit.formal_single(250))
    assert before == {p:p.read_bytes() for p in before}


def test_lock_is_reentrant_and_excludes_another_process(tmp_path):
    p=tmp_path/'cache.json'
    code='''from pathlib import Path
import sys
from zodiac_v2.storage import locked_paths
try:
    with locked_paths((Path(sys.argv[1]),)):
        sys.exit(0)
except RuntimeError:
    sys.exit(3)
'''
    env={**os.environ,'PYTHONPATH':str(Path(__file__).parents[1]/'src')}
    with locked_paths((p,)):
        with locked_paths((p,)):
            result=subprocess.run([sys.executable,'-c',code,str(p)],env=env,capture_output=True,timeout=10)
            assert result.returncode==3,result.stderr
    result=subprocess.run([sys.executable,'-c',code,str(p)],env=env,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_hard_crash_leaves_journal_and_blocks_next_writer(tmp_path):
    p=tmp_path/'first.txt';q=tmp_path/'second.txt';journal=tmp_path/'journal.json'
    p.write_bytes(b'old1');q.write_bytes(b'old2')
    code='''import os,sys
from pathlib import Path
import zodiac_v2.storage as storage
p,q,j=map(Path,sys.argv[1:])
original=storage.os.replace
def crash(src,dst):
    result=original(src,dst)
    if Path(dst)==p:os._exit(19)
    return result
storage.os.replace=crash
storage.atomic_write_many({p:b'new1',q:b'new2'},journal=j)
'''
    env={**os.environ,'PYTHONPATH':str(Path(__file__).parents[1]/'src')}
    result=subprocess.run([sys.executable,'-c',code,str(p),str(q),str(journal)],env=env,
                          capture_output=True,timeout=10)
    assert result.returncode==19,result.stderr
    assert journal.exists()
    metadata=json.loads(journal.read_text())
    assert all(Path(row['backup']).exists() for row in metadata['files'])
    with pytest.raises(RuntimeError,match='未完成'):
        atomic_write_many({p:b'next'},journal=journal)


def test_cleanup_failure_after_commit_never_rolls_back_without_journal(tmp_path,monkeypatch):
    import zodiac_v2.storage as storage
    a=tmp_path/'a.txt';b=tmp_path/'b.txt';journal=tmp_path/'journal.json'
    a.write_bytes(b'old-a');b.write_bytes(b'old-b')
    original=storage._sync_directory
    def fail_only_after_commit(directory):
        if not journal.exists() and a.read_bytes()==b'new-a' and b.read_bytes()==b'new-b':
            raise OSError('directory sync error after journal unlink')
        return original(directory)
    monkeypatch.setattr(storage,'_sync_directory',fail_only_after_commit)
    with pytest.raises(RuntimeError,match='已完整替换'):
        storage.atomic_write_many({a:b'new-a',b:b'new-b'},journal=journal)
    assert a.read_bytes()==b'new-a' and b.read_bytes()==b'new-b'
