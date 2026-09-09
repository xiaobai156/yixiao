from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import zodiac_v2.source.browser as mod
from zodiac_v2.contracts import Candidate, Direction, DocumentType, FailureCode, SiteConfig, SiteSection
from zodiac_v2.source.browser import BrowserCapture, BrowserResponse, PlaywrightBrowserRenderer, browser_documents
from zodiac_v2.source.documents import source_identity
from zodiac_v2.source.http import RequestsTransport, SourceFetchCode, SourceFetchError
from zodiac_v2.validation.conflicts import validate_candidates

PAGE='https://example.test/article/admin/abc'
API='https://example.test/api/proxy/admin-articles/abc'


class Renderer:
    def __init__(self,*responses,complete=True): self.responses=responses;self.complete=complete
    def capture(self,url,*,timeout,allowed_response_urls=(),allowed_response_origins=()):
        return BrowserCapture(url,'empty',self.responses,self.complete)


def response(payload,status=200,content_type='application/json'):
    return BrowserResponse(API,status,content_type,json.dumps(payload,ensure_ascii=False))


def test_browser_projects_only_unique_target_record():
    target={'id':'abc','content':'杀肖\n250期：鼠'}
    source=browser_documents(Renderer(response({'data':[target,{'id':'other','content':'250期：牛'}]})),PAGE)
    assert json.loads(source.documents[1].text)==target
    assert source.documents[1].record_id=='abc'


def test_nested_recommendations_do_not_survive_projection():
    target={'id':'abc','content':'杀肖\n250期：鼠',
            'recommendations':[{'id':'other','content':'250期：牛'}], 'footer':'250期：牛'}
    source=browser_documents(Renderer(response(target)),PAGE)
    assert json.loads(source.documents[1].text)=={'id':'abc','content':'杀肖\n250期：鼠'}


def test_repeated_url_responses_keep_unique_evidence_ids_and_detect_conflict():
    source=browser_documents(Renderer(response({'id':'abc','content':'杀肖\n250期：鼠'}),
                                      response({'id':'abc','content':'杀肖\n250期：牛'})),PAGE)
    docs=source.documents[1:]
    assert len({d.source_id for d in docs})==2
    candidates=tuple(Candidate(250,z,f'250期：{z}',d.source_id,d.page_order*1_000_000+1,
                              ('section:杀肖','anchor-line:0','block-range:0-2'),record_id='abc')
                     for d,z in zip(docs,'鼠牛'))
    site=SiteConfig('测试',PAGE,Direction.TOP,SiteSection.NEW,'test','browser')
    assert validate_candidates(site,source,candidates,250).failure_code is FailureCode.CONFLICT


def test_browser_count_limit_is_enforced_for_injected_renderer():
    with pytest.raises(SourceFetchError) as exc:
        browser_documents(Renderer(*(response({'id':'abc','content':'x'}) for _ in range(33))),PAGE)
    assert exc.value.code is SourceFetchCode.TOO_LARGE


def test_browser_total_byte_limit_is_enforced_for_injected_renderer(monkeypatch):
    monkeypatch.setattr(mod,'MAX_BROWSER_TOTAL_BYTES',10)
    with pytest.raises(SourceFetchError) as exc:
        browser_documents(Renderer(response({'id':'abc','content':'x'})),PAGE)
    assert exc.value.code is SourceFetchCode.TOO_LARGE


@pytest.mark.parametrize(('status','ctype'),[(500,'application/json'),(200,'text/html')])
def test_explicit_api_errors_are_not_silently_replaced_with_dom(status,ctype):
    with pytest.raises(SourceFetchError):
        browser_documents(Renderer(response({},status,ctype)),PAGE,allowed_response_urls=(API,))


def test_incomplete_browser_capture_cannot_be_accepted():
    source=browser_documents(Renderer(response({'id':'abc','content':'x'}),complete=False),PAGE)
    assert not source.scan_complete


def test_tls_error_never_retries_without_verification(monkeypatch):
    import requests
    transport=RequestsTransport();calls=[]
    def failing(*a,**kw): calls.append(kw['verify']);raise requests.exceptions.SSLError('bad certificate')
    monkeypatch.setattr(transport,'_request',failing)
    with pytest.raises(SourceFetchError): transport.request(PAGE,timeout=1,max_bytes=100)
    assert calls==[True]
    with pytest.raises(ValueError): RequestsTransport(insecure_tls_hosts={'example.test'})


@pytest.fixture
def local_page():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/api/data':
                body=json.dumps({'data':[{'id':'123','content':'杀肖\n250期：鼠'},
                                         {'id':'999','content':'杀肖\n250期：牛'}]},ensure_ascii=False).encode()
                kind='application/json'
            else:
                body=b'''<html><body><p id="content"></p><script>
                fetch('/api/data').then(r=>r.json()).then(d=>{
                  document.getElementById('content').textContent=d.data[0].content;
                });</script></body></html>'''
                kind='text/html'
            self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally: server.shutdown();server.server_close();thread.join()


def test_real_chromium_pool_reuses_owners_and_projects_local_api(monkeypatch,local_page):
    executable=shutil.which('chromium')
    if not executable:
        pytest.skip('Local system Chromium is not installed; no automatic browser download')
    from playwright.sync_api import BrowserType
    original=BrowserType.launch;launches=[]
    def launch(self,*a,**kw):
        kw['executable_path']=executable
        launches.append(threading.get_ident())
        return original(self,*a,**kw)
    monkeypatch.setattr(BrowserType,'launch',launch)
    renderer=PlaywrightBrowserRenderer()
    try:
        for _ in range(4):
            source=browser_documents(renderer,local_page+'/topic/123.html',timeout=15,
                                     allowed_response_urls=(local_page+'/api/data',))
            assert source.scan_complete
            docs=[d for d in source.documents if d.document_type is DocumentType.JSON]
            assert len(docs)==1 and json.loads(docs[0].text)=={'id':'123','content':'杀肖\n250期：鼠'}
        assert 1 <= len(launches) <= 2
        assert len(set(launches))==len(launches)
    except SourceFetchError as exc:
        if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(exc):
            pytest.skip("Environment policy blocks browser navigation; network integration NOT verified")
        raise
    finally:
        renderer.close()
    assert renderer._workers==()


def test_real_chromium_owner_pool_with_offline_dom_only(monkeypatch):
    executable=shutil.which('chromium')
    if not executable:
        pytest.skip('Local system Chromium is not installed')
    from playwright.sync_api import BrowserType
    original=BrowserType.launch;launches=[];owners=[]
    def launch(self,*a,**kw):
        kw['executable_path']=executable;launches.append(threading.get_ident())
        return original(self,*a,**kw)
    def offline_capture(self,browser,url,*args):
        # Deliberately mock navigation: only an about:blank offline DOM is used.
        # This verifies ownership/reuse/cleanup, NOT network source acquisition.
        owners.append(threading.get_ident())
        context=browser.new_context()
        try:
            page=context.new_page()
            page.set_content('<html><body><p>250期：鼠</p></body></html>')
            return BrowserCapture(url,page.content(),())
        finally:
            context.close()
    monkeypatch.setattr(BrowserType,'launch',launch)
    monkeypatch.setattr(PlaywrightBrowserRenderer,'_capture_page',offline_capture)
    renderer=PlaywrightBrowserRenderer()
    try:
        for _ in range(5):
            assert '250期：鼠' in renderer.capture(PAGE,timeout=15).html
        assert 1<=len(launches)<=2 and len(launches)==len(set(launches))
        assert set(owners)<=set(launches)
    finally:
        renderer.close()
    assert renderer._workers==()


class Request:
    def __init__(self,url=API): self.url=url


class Response:
    def __init__(self,body='{"id":"abc","content":"x"}',length=None,status=200):
        self.url=API;self.request=Request();self.body=body;self.status=status;self.length=length;self.reads=0
    def header_value(self,key):
        return 'application/json' if key=='content-type' else self.length
    def text(self): self.reads+=1;return self.body


class Page:
    def __init__(self,responses,finish=True,idle=True,failed=False):
        self.responses=responses;self.finish=finish;self.idle=idle;self.failed=failed;self.handlers={};self.url=PAGE
    def on(self,name,handler): self.handlers[name]=handler
    def remove_listener(self,name,handler): self.handlers.pop(name,None)
    def goto(self,*args,**kwargs):
        for response in self.responses:
            self.handlers['response'](response)
            if self.finish: self.handlers['requestfinished'](response.request)
            if self.failed: self.handlers['requestfailed'](response.request)
        return type('Navigation',(),{'status':200})()
    def wait_for_event(self,*args,**kwargs):
        from playwright.sync_api import TimeoutError
        raise TimeoutError('mock pending event')
    def wait_for_load_state(self,*args,**kwargs):
        if not self.idle:
            from playwright.sync_api import TimeoutError
            raise TimeoutError('not idle')
    def content(self): return '<p>body</p>'


class Context:
    def __init__(self,page): self.page=page;self.closed=False;self.routing=None
    def route(self,pattern,handler): self.routing=handler
    def new_page(self): return self.page
    def close(self): self.closed=True


class Browser:
    def __init__(self,context): self.context=context
    def new_context(self,**kwargs): assert kwargs['service_workers']=='block';return self.context


def capture_page(page,max_bytes=1000):
    from time import monotonic
    context=Context(page)
    renderer=PlaywrightBrowserRenderer()
    try:
        result=renderer._capture_page(Browser(context),PAGE,monotonic()+10,10,max_bytes,
                                      frozenset((API,)),frozenset((source_identity(PAGE).origin,)))
        return result,context
    finally:
        assert context.closed


def test_response_body_only_read_after_requestfinished():
    response=Response()
    result,context=capture_page(Page((response,),finish=False,idle=False))
    assert response.reads==0 and not result.scan_complete


def test_declared_oversized_body_is_rejected_before_text_read():
    response=Response(length='5000')
    with pytest.raises(SourceFetchError) as exc: capture_page(Page((response,)))
    assert exc.value.code is SourceFetchCode.TOO_LARGE and response.reads==0


def test_chunked_body_actual_size_is_checked():
    response=Response('x'*5000)
    with pytest.raises(SourceFetchError) as exc: capture_page(Page((response,)))
    assert exc.value.code is SourceFetchCode.TOO_LARGE and response.reads==1


def test_request_failure_keeps_capture_from_being_accepted():
    with pytest.raises(SourceFetchError) as exc: capture_page(Page((Response(),),finish=False,failed=True))
    assert exc.value.code is SourceFetchCode.NETWORK


def test_resource_interception_keeps_scripts_and_data():
    _,context=capture_page(Page(()))
    for kind in ('image','media','font','script','xhr','stylesheet','document'):
        events=[]
        route=type('Route',(),{'request':type('R',(),{'resource_type':kind})(),
                              'abort':lambda self:events.append('abort'),
                              'continue_':lambda self:events.append('continue')})()
        context.routing(route)
        assert events==(['abort'] if kind in {'image','media','font'} else ['continue'])
