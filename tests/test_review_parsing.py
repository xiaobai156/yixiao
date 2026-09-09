from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest

from zodiac_v2.contracts import Candidate, Direction, DocumentType, FailureCode, RunMode, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.families import AnchoredSectionFamilyParser, AnchoredSectionSpec, RegexFamilyParser
from zodiac_v2.services.scrape import DefaultSourceGateway, ScrapeService
from zodiac_v2.source.documents import collect_content_documents, DiscoveredDocument
from zodiac_v2.source.http import HttpResponse, SourceFetchError
from zodiac_v2.validation.conflicts import validate_candidates, validate_period_presence
from zodiac_v2.validation.evidence import validate_candidate_evidence


def site(policy='http_consensus'):
    return SiteConfig('测试站','https://example.test/topic/1.html',Direction.TOP,SiteSection.NEW,'test',policy)


def bundle(*rows):
    text='测试站\n'+'\n'.join(f'{p}期【绝杀一肖】【{z}】开00' for p,z in rows)
    return SourceBundle((SourceDocument(text,site().url,DocumentType.HTML,0,'local',0),))


def regex(cycles=False):
    return RegexFamilyParser((r'(\d{2,4})期【绝杀一肖】【([鼠牛虎兔龙蛇马羊猴鸡狗猪])】',),
                             directional_cycle_sites={'测试站'} if cycles else ())


class ProbeGateway:
    def __init__(self,frames): self.frames=iter(frames);self.calls=0
    def http(self,site,timeout): self.calls+=1;return next(self.frames)
    def embedded(self,site,source,timeout): return source


@pytest.mark.parametrize('conflicted_period',[250,251])
def test_consensus_explicit_conflict_not_hidden_by_two_confirmations(conflicted_period):
    good=bundle((250,'鼠'))
    conflict=bundle((250,'鼠'),(conflicted_period,'牛'),(conflicted_period,'虎'))
    gateway=ProbeGateway((good,good,conflict,good,good))
    result=ScrapeService(gateway,regex()).scrape_site(site(),250)
    assert not result.ok and result.failure_code is FailureCode.CONFLICT
    assert gateway.calls==3


def test_consensus_next_period_presence_does_not_require_edge():
    source=bundle((250,'鼠'),(251,'牛'),(249,'虎'))
    result=ScrapeService(ProbeGateway((source,)*5),regex()).scrape_site(site(),250)
    assert result.failure_code is FailureCode.DIRECTION
    assert '251期' in result.reason


def test_consensus_ignores_only_proven_inactive_cycle():
    source=bundle((250,'鼠'),(249,'狗'),(20,'牛'),(300,'鸡'),(250,'虎'))
    result=ScrapeService(ProbeGateway((source,)*5),regex(True)).scrape_site(site(),250,RunMode.FORMAL_SINGLE)
    assert result.ok and result.candidate.zodiac=='鼠' and result.validator_issued


def test_presence_conflict_checked_even_when_target_not_at_edge():
    source=bundle((249,'鼠'),(250,'牛'),(250,'虎'))
    decision=validate_period_presence(site(),source,regex().parse(site(),source),250)
    assert decision.failure_code is FailureCode.CONFLICT


def test_filtered_empty_direction_window_is_explicit_boundary_failure():
    source=bundle((251,'鼠'))
    result=validate_candidates(site(),source,regex().parse(site(),source),250)
    assert result.failure_code is FailureCode.BOUNDARY


@pytest.mark.parametrize('separator',['结束','目标栏目'])
def test_anchored_rolling_window_cannot_take_value_after_block_boundary(separator):
    config=site('http_documents')
    parser=AnchoredSectionFamilyParser({'测试站':AnchoredSectionSpec(
        '目标栏目',r'(\d{3})期.*?([鼠牛虎兔龙蛇马羊猴鸡狗猪])',stop_pattern='结束',record_window_lines=3,
    )})
    doc=SourceDocument(f'目标栏目\n250期\n{separator}\n牛',config.url,DocumentType.HTML,0,'local',0)
    assert parser.parse(config,SourceBundle((doc,)))==()


def test_anchored_candidates_have_final_not_document_end_range():
    config=site('http_documents')
    parser=AnchoredSectionFamilyParser({'测试站':AnchoredSectionSpec('目标栏目',r'(\d{3})期：([鼠牛虎兔龙蛇马羊猴鸡狗猪])',stop_pattern='结束')})
    doc=SourceDocument('目标栏目\n250期：鼠\n结束\n其他栏目\n250期：牛',config.url,DocumentType.HTML,0,'local',0)
    source=SourceBundle((doc,));items=parser.parse(config,source)
    assert len(items)==1 and 'section-range:0-2' in items[0].evidence
    assert validate_candidates(config,source,items,250).ok


def test_evidence_rejects_raw_text_crossing_declared_range():
    doc=SourceDocument('杀肖\n250期\n牛',site().url,DocumentType.HTML,0,'local',0)
    c=Candidate(250,'牛','250期 牛','local',1,('section:杀肖','anchor-line:0','block-range:0-2'))
    decision=validate_candidate_evidence(c,SourceBundle((doc,)))
    assert decision.failure_code is FailureCode.BOUNDARY


def test_mismatched_document_record_id_rejected():
    doc=SourceDocument('杀肖\n250期：鼠',site().url,DocumentType.HTML,0,'local',0,'1')
    c=Candidate(250,'鼠','250期：鼠','local',1,('section:杀肖','anchor-line:0'),record_id='2')
    assert validate_candidate_evidence(c,SourceBundle((doc,))).failure_code is FailureCode.SOURCE_IDENTITY


BASE='https://example.test/list.aspx?id=79&page={}'
DETAIL='https://example.test/article.aspx?id=100'


class Transport:
    def __init__(self,pages): self.pages=pages;self.fetched=[]
    def request(self,url,*,timeout,max_bytes):
        self.fetched.append(url)
        body='250期：测试站【绝杀一肖】【鼠】' if url==DETAIL else self.pages[int(parse_qs(urlsplit(url).query)['page'][0])]
        return HttpResponse(200,url,body.encode(),(('Content-Type','text/html; charset=utf-8'),))


def page(period,number,*,match=False,next_page=None):
    article_id=100 if match else 200+number
    return (f'<a href="/article.aspx?id={article_id}">{period}期: {"测试站" if match else "其他"}</a>'
            +(f'<a href="/list.aspx?id=79&page={next_page}">下一页</a>' if next_page else ''))


def scan(pages):
    config=replace(site(),url=BASE.format(1),source_policy='http_period_keyword_article',article_keyword='测试站')
    first=SourceDocument(pages[1],config.url,DocumentType.HTML,0,'first',0)
    transport=Transport(pages)
    return transport,lambda:DefaultSourceGateway(transport=transport).period_keyword_article(config,SourceBundle((first,)),250,10)


def test_pagination_follows_newer_first_page_to_target():
    transport,run=scan({1:page(251,1,next_page=2),2:page(250,2,match=True)})
    assert run().documents[0].final_url==DETAIL
    assert transport.fetched==[BASE.format(2),DETAIL]


def test_pagination_stops_on_first_strictly_older_page():
    pages={i:page(250,i,match=(i==8),next_page=i+1) for i in range(1,10)}
    pages[10]=page(249,10,next_page=11)
    transport,run=scan(pages)
    assert run().documents[0].final_url==DETAIL
    assert transport.fetched==[BASE.format(i) for i in range(2,11)]+[DETAIL]


def test_pagination_limit_checked_before_eleventh_network_fetch():
    transport,run=scan({i:page(250,i,match=(i==8),next_page=i+1) for i in range(1,11)})
    with pytest.raises(SourceFetchError,match='10 页'): run()
    assert BASE.format(11) not in transport.fetched and DETAIL not in transport.fetched


def test_missing_consecutive_navigation_fails_instead_of_skipping_page():
    transport,run=scan({1:page(251,1,next_page=3)})
    with pytest.raises(SourceFetchError,match='连续下一页'): run()
    assert transport.fetched==[]


def test_embedded_total_size_limit_marks_source_incomplete():
    parent=SourceDocument('12345','https://example.test/',DocumentType.HTML,0,'parent',0)
    resource=DiscoveredDocument('https://example.test/upload/1.js',DocumentType.SCRIPT,0)
    def fetch(r): return SourceDocument('123456',r.url,r.document_type,0,'child',1)
    result=collect_content_documents(parent,(resource,),fetch,max_total_bytes=10)
    assert not result.scan_complete and 'content_truncated:total_bytes' in result.diagnostics


class ArticleGateway:
    def __init__(self,body): self.body=body;self.calls=[]
    def article_api(self,site,timeout): self.calls.append('api');return ()
    def http(self,site,timeout):
        self.calls.append('http');return SourceBundle((SourceDocument(self.body,site.url,DocumentType.HTML,0,'local',0),))
    def embedded(self,site,bundle,timeout): return bundle
    def browser(self,site,timeout):
        self.calls.append('browser');return bundle((250,'鼠'))


@pytest.mark.parametrize(('body','expected'),[('测试站\n250期【绝杀一肖】【鼠】',['api','http']),
                                             ('已有完整正文但没有目标数据',['api','http']),
                                             ('<html><script>shell()</script></html>',['api','http','browser'])])
def test_api_all_404_uses_page_http_before_browser(body,expected):
    config=replace(site('http_then_browser'),url='https://example.test/article/admin/abc')
    gateway=ArticleGateway(body)
    ScrapeService(gateway,regex()).scrape_site(config,250)
    assert gateway.calls==expected


def test_consensus_final_evaluation_conflict_also_vetoes_confirmations(monkeypatch):
    from zodiac_v2.contracts import ScrapeResult
    good = bundle((250, "鼠"))
    service = ScrapeService(ProbeGateway((good,) * 5), regex())
    original = service._evaluate
    calls = []

    def evaluate(config, period, source, mode):
        calls.append(period)
        if len(calls) == 3:
            return ScrapeResult.failure(
                config, period, FailureCode.CONFLICT, "明确冲突", source.documents,
            )
        return original(config, period, source, mode)

    monkeypatch.setattr(service, "_evaluate", evaluate)
    result = service.scrape_site(site(), 250)
    assert result.failure_code is FailureCode.CONFLICT
    assert len(calls) == 3
