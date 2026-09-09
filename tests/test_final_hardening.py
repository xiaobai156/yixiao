from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from zodiac_v2.cache import backfill_recent_cache_records, cache_records, validate_cache_data
from zodiac_v2.cli import main as cli_main
from zodiac_v2.config import ConfigError, append_site_configs, load_sites
from zodiac_v2.contracts import (
    CacheRecord,
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    RunMode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
    WritePermit,
)
from zodiac_v2.output import merge_formal_single_result_output, output_paths
from zodiac_v2.services.scrape import DefaultSourceGateway, ScrapeService
from zodiac_v2.source.browser import PlaywrightBrowserRenderer
from zodiac_v2.source.documents import SourceIdentityError, source_identity, validate_final_url
from zodiac_v2.source.http import HttpResponse, SourceFetchCode, SourceFetchError
from zodiac_v2.validation.conflicts import validate_period_presence


# Keep helpers intentionally small: every assertion here is a regression for the
# final hardening pass, not another parser implementation.
def _site(name: str = "目标站", *, policy: str = "http_documents", direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(name, f"https://example.test/topic/{name}.html", direction, SiteSection.NEW, "test", policy)


def _bundle(text: str, configured: SiteConfig | None = None) -> SourceBundle:
    configured = configured or _site()
    return SourceBundle(
        (SourceDocument("栏目：杀肖\n" + text, configured.url, DocumentType.HTML, 0, "doc", 0),),
        ("scan_complete:1",),
        scan_complete=True,
    )


class _Parser:
    def parse(self, configured: SiteConfig, bundle: SourceBundle):
        rows = []
        for document in bundle.documents:
            for index, line in enumerate(document.text.splitlines()):
                match = re.search(r"(\d+)期：([鼠牛虎兔龙蛇马羊猴鸡狗猪])", line)
                if match:
                    rows.append(
                        Candidate(
                            int(match[1]),
                            match[2],
                            match[0],
                            document.source_id,
                            index,
                            ("section:杀肖", "anchor-line:0", f"block-range:0-{len(document.text.splitlines())}"),
                            record_id=document.record_id,
                        )
                    )
        return tuple(rows)


def test_final_url_rejects_same_origin_wrong_unidentified_page() -> None:
    with pytest.raises(SourceIdentityError, match="页面边界不匹配"):
        validate_final_url("https://example.test/path/a.html", "https://example.test/path/b.html")


def test_final_url_canonicalizes_query_order_and_default_document() -> None:
    validate_final_url(
        "https://example.test/list.aspx?id=79&page=1",
        "https://example.test/list.aspx?page=1&id=79",
    )
    validate_final_url("https://example.test/", "https://example.test/index.html")


def test_query_and_static_record_ids_are_bound() -> None:
    assert source_identity("https://example.test/bbs/topic.php?id=22743").topic_id == "22743"
    assert source_identity("https://example.test/read.php?tid=520").topic_id == "520"
    assert source_identity("https://example.test/art_zhuanqu/9803.html").article_id == "9803"
    with pytest.raises(SourceIdentityError, match="ID 边界不匹配"):
        validate_final_url(
            "https://example.test/bbs/topic.php?id=22743",
            "https://example.test/bbs/topic.php?id=22744",
        )
    with pytest.raises(SourceIdentityError, match="记录类型"):
        validate_final_url(
            "https://example.test/art_zhuanqu/9803.html",
            "https://example.test/art_gsb/9803.html",
        )


def _formal_success(configured: SiteConfig, period: int = 224, zodiac: str = "鼠"):
    document = SourceDocument(
        f"栏目：杀肖\n{period}期：{zodiac}", configured.url, DocumentType.HTML, 0, "doc", 0,
    )
    return ScrapeService(
        SimpleNamespace(http=lambda site, timeout: SourceBundle((document,), scan_complete=True),
                        embedded=lambda site, bundle, timeout: bundle),
        _Parser(),
    ).scrape_site(configured, period, RunMode.FORMAL_SINGLE)


def test_targeted_merge_reads_utf8_bom_without_losing_first_row(tmp_path: Path) -> None:
    configured = _site("修复站")
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    paths.new_success.parent.mkdir(parents=True)
    paths.new_failure.parent.mkdir(parents=True)
    paths.new_success.write_bytes("\ufeff牛 其他站\n红色\n\n内容\t次数\t排名\n牛\t1\t1\n".encode("utf-8"))
    paths.new_failure.write_text("无\n", encoding="utf-8")

    merge_formal_single_result_output(_formal_success(configured), paths, WritePermit.formal_single(224))

    text = paths.new_success.read_text(encoding="utf-8")
    assert "牛 其他站" in text
    assert "鼠 修复站" in text


def test_targeted_merge_refuses_unknown_detail_line_without_touching_file(tmp_path: Path) -> None:
    configured = _site("修复站")
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    paths.new_success.parent.mkdir(parents=True)
    paths.new_failure.parent.mkdir(parents=True)
    original = "牛 其他站\n这 行 无法 识别\n红色\n\n内容\t次数\t排名\n牛\t1\t1\n"
    paths.new_success.write_text(original, encoding="utf-8")
    paths.new_failure.write_text("无\n", encoding="utf-8")

    with pytest.raises(ValueError, match="无法识别"):
        merge_formal_single_result_output(_formal_success(configured), paths, WritePermit.formal_single(224))
    assert paths.new_success.read_text(encoding="utf-8") == original


def test_targeted_success_clears_old_failure_even_if_direction_and_url_changed(tmp_path: Path) -> None:
    configured = _site("修复站", direction=Direction.TOP)
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    paths.new_success.parent.mkdir(parents=True)
    paths.new_failure.parent.mkdir(parents=True)
    paths.new_success.write_text("无\n", encoding="utf-8")
    paths.new_failure.write_text(
        "修复站 bottom https://old.example/ 原因：[方向失败] 旧配置\n\n"
        "其他站 top https://example.test/ 原因：[网络失败] 保留\n",
        encoding="utf-8",
    )
    merge_formal_single_result_output(_formal_success(configured), paths, WritePermit.formal_single(224))
    text = paths.new_failure.read_text(encoding="utf-8")
    assert "修复站" not in text
    assert "其他站" in text


def test_consensus_direction_failure_cannot_be_outvoted_by_later_successes() -> None:
    configured = _site(policy="http_consensus")
    captures = [_bundle("226期：虎\n224期：鼠", configured)] + [_bundle("224期：鼠", configured)] * 4

    class Gateway:
        def __init__(self):
            self.index = 0

        def http(self, site, timeout):
            value = captures[self.index]
            self.index += 1
            return value

        def embedded(self, site, bundle, timeout):
            return bundle

    result = ScrapeService(Gateway(), _Parser()).scrape_site(configured, 224)
    assert result.failure_code is FailureCode.DIRECTION


def test_period_presence_ignores_incomplete_next_issue() -> None:
    configured = _site()
    bundle = _bundle("224期：鼠\n225期：牛", configured)
    rows = list(_Parser().parse(configured, bundle))
    rows[1] = Candidate(
        rows[1].period,
        rows[1].zodiac,
        rows[1].raw_line,
        rows[1].document_id,
        rows[1].page_order,
        (*rows[1].evidence, "record-status:incomplete"),
        record_id=rows[1].record_id,
    )
    decision = validate_period_presence(configured, bundle, rows, 225)
    assert decision.failure_code is FailureCode.PERIOD


def _cache_entry(periods: range) -> dict[str, object]:
    records = [{"period": period, "zodiac": "鼠"} for period in periods]
    return {
        "name": "缓存站",
        "url": "https://example.test/topic/1.html",
        "pick": "top",
        "section": "已有站点",
        "records": records,
        "fingerprint": "鼠" * len(records),
        "record_provenance": {
            str(period): {
                "validation_status": "validated",
                "source_id": "doc",
                "source_url": "https://example.test/topic/1.html",
                "evidence_sha256": "a" * 64,
                "record_id": "1",
            }
            for period in periods
        },
    }


def test_cache_rejects_invalid_record_id_instead_of_silently_skipping() -> None:
    entry = _cache_entry(range(224, 223, -1))
    entry["record_provenance"]["224"]["record_id"] = False  # type: ignore[index]
    data = {"window_back_periods": 10, "latest_period": 224, "sites": [entry]}
    with pytest.raises(ValueError, match="record_id"):
        validate_cache_data(data)
    with pytest.raises(ValueError, match="record_id"):
        cache_records(data)


def test_backfill_rejects_period_outside_current_ten_issue_window() -> None:
    entry = _cache_entry(range(251, 241, -1))
    data = {"window_back_periods": 10, "latest_period": 251, "sites": [entry]}
    record = CacheRecord(
        "缓存站",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        240,
        "牛",
        "doc",
        "https://example.test/topic/1.html",
        "b" * 64,
        "1",
    )
    with pytest.raises(ValueError, match="超出当前近10期窗口"):
        backfill_recent_cache_records(data, (record,), permit=WritePermit.formal_single(240))


def test_period_keyword_accepts_di_prefix_and_leading_zero() -> None:
    from zodiac_v2.source.documents import discover_period_page_links

    html = '<a href="/article.aspx?id=8">第024期：目标关键字</a>'
    articles, _pages, periods = discover_period_page_links(
        html, "https://example.test/list.aspx?id=79&page=1", 24, "目标关键字"
    )
    assert articles == ("https://example.test/article.aspx?id=8",)
    assert periods == (24,)


def test_period_keyword_pagination_crosses_year_wrap_for_previous_cycle_target() -> None:
    base = "https://example.test/list.aspx?id=79&page="
    detail = "https://example.test/article.aspx?id=9"
    pages = {
        base + "2": '<a href="/article.aspx?id=9">365期：目标</a><a href="/list.aspx?id=79&page=3">下一页</a>',
        base + "3": '<a href="/article.aspx?id=10">364期：其他</a>',
        detail: "365期：鼠",
    }
    calls = []

    class Transport:
        def request(self, url, **kwargs):
            calls.append(url)
            text = pages[url]
            return HttpResponse(200, url, text.encode(), (("Content-Type", "text/html; charset=utf-8"),))

    configured = SiteConfig(
        "目标", base + "1", Direction.TOP, SiteSection.EXISTING,
        "test", "http_period_keyword_article", article_keyword="目标",
    )
    first = SourceBundle((SourceDocument(
        '<a href="/article.aspx?id=1">2期：其他</a><a href="/list.aspx?id=79&page=2">下一页</a>',
        configured.url, DocumentType.HTML, 0, "list", 0,
    ),))
    bundle = DefaultSourceGateway(Transport()).period_keyword_article(configured, first, 365, 10)
    assert calls == [base + "2", base + "3", detail]
    assert bundle.documents[0].final_url == detail


def test_onboard_cli_forwards_article_keyword_and_embedded_limit(tmp_path: Path, monkeypatch) -> None:
    import zodiac_v2.cli as cli

    captured = {}
    monkeypatch.setattr(cli, "_runtime", lambda path: ((), object()))
    monkeypatch.setattr(cli, "load_recent_cache", lambda path: {"latest_period": 20, "sites": []})

    def validate(scraper, candidate, existing, cache, periods, **kwargs):
        captured["candidate"] = candidate
        return SimpleNamespace(reasons=(), accepted=True)

    monkeypatch.setattr(cli, "validate_new_site", validate)
    assert cli_main((
        "onboard", "--name", "新站", "--url", "https://example.test/list.aspx?id=79&page=1",
        "--source-policy", "http_period_keyword_article", "--article-keyword", "专栏",
        "--embedded-max-bytes", "9000000", "--period", "20",
        "--cache-file", str(tmp_path / "cache.json"),
    )) == 0
    candidate = captured["candidate"]
    assert candidate.article_keyword == "专栏"
    assert candidate.embedded_max_bytes == 9_000_000


def test_config_requires_api_url_for_api_then_http(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(json.dumps([{
        "name": "x", "url": "https://example.test/#/users/7", "pick": "top",
        "section": "新增的站点", "parser_id": "test", "source_policy": "api_then_http",
    }]), encoding="utf-8")
    with pytest.raises(ConfigError, match="api_url"):
        load_sites(path, parser_ids={"test"}, source_policies={"api_then_http"})


def test_append_allows_same_period_list_when_business_keyword_differs(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    base = "https://example.test/list.aspx?id=79&page=1"
    path.write_text(json.dumps([{
        "name": "栏目甲", "url": base, "pick": "top", "section": "已有站点",
        "parser_id": "test", "source_policy": "http_period_keyword_article", "article_keyword": "甲",
    }]), encoding="utf-8")
    candidate = SiteConfig(
        "栏目乙", base, Direction.TOP, SiteSection.EXISTING, "test",
        "http_period_keyword_article", article_keyword="乙",
    )
    append_site_configs(path, (candidate,), permit=WritePermit.formal_single(224))
    loaded = load_sites(path, parser_ids={"test"}, source_policies={"http_period_keyword_article"})
    assert [site.name for site in loaded] == ["栏目甲", "栏目乙"]


def test_browser_networkidle_timeout_is_only_a_settle_hint(monkeypatch) -> None:
    import playwright.sync_api as playwright_api

    class Page:
        url = "https://example.test/"

        def on(self, *args):
            pass

        def goto(self, *args, **kwargs):
            return SimpleNamespace(status=200)

        def wait_for_load_state(self, *args, **kwargs):
            raise playwright_api.TimeoutError("polling")

        def wait_for_timeout(self, timeout):
            self.settled = timeout

        def content(self):
            return "<html>ready</html>"

    page = Page()

    class Context:
        def route(self, *args):
            pass

        def new_page(self):
            return page

    class Browser:
        def new_context(self, **kwargs):
            return Context()

        def close(self):
            pass

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(playwright_api, "sync_playwright", lambda: Manager())
    capture = PlaywrightBrowserRenderer().capture("https://example.test/", timeout=2)
    assert capture.html == "<html>ready</html>"
    assert page.settled <= 500


def test_failure_codes_distinguish_http_status_and_parser_bug() -> None:
    configured = _site()

    class HttpFail:
        def http(self, site, timeout):
            raise SourceFetchError(SourceFetchCode.HTTP_STATUS, "HTTP 404", url=site.url, status=404)

    assert ScrapeService(HttpFail(), _Parser()).scrape_site(configured, 224).failure_code is FailureCode.HTTP_STATUS

    class Gateway:
        def http(self, site, timeout):
            return _bundle("224期：鼠", configured)

    class BrokenParser:
        def parse(self, site, bundle):
            raise RuntimeError("bug")

    assert ScrapeService(Gateway(), BrokenParser()).scrape_site(configured, 224).failure_code is FailureCode.PARSER_ERROR


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") != "true", reason="Real Chromium smoke runs in CI after playwright install")
def test_real_chromium_runtime_smoke() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"<html><body>ready</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        capture = PlaywrightBrowserRenderer().capture(
            f"http://127.0.0.1:{server.server_port}/", timeout=10
        )
        assert "ready" in capture.html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
