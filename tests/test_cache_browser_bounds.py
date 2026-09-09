from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from zodiac_v2.contracts import Candidate, Direction, DocumentType, SiteConfig, SiteSection, SourceDocument, WritePermit
from zodiac_v2.output import output_paths
from zodiac_v2.services.persistence import CachePersistenceError, commit_targeted_formal_single
from zodiac_v2.source.browser import PlaywrightBrowserRenderer
from zodiac_v2.source.http import SourceFetchCode, SourceFetchError


def _validated_result(period: int = 252):
    from zodiac_v2.contracts import ScrapeResult

    site = SiteConfig(
        "缓存状态测试站",
        "https://example.test/topic/252.html",
        Direction.TOP,
        SiteSection.EXISTING,
        "test",
        "http_documents",
    )
    document = SourceDocument(
        f"{period}期：鼠",
        site.url,
        DocumentType.HTML,
        0,
        "html:test",
        0,
        "252",
    )
    candidate = Candidate(
        period,
        "鼠",
        f"{period}期：鼠",
        document.source_id,
        0,
        ("section:杀肖", "block-range:0-1"),
        record_id="252",
    )
    return site, ScrapeResult._validated_success(site, period, candidate, (document,))


def test_targeted_commit_reports_cache_failure_after_txt_publication(tmp_path: Path) -> None:
    site, result = _validated_result()
    paths = output_paths(252, tmp_path / "success", tmp_path / "failure")
    paths.existing_success.parent.mkdir(parents=True, exist_ok=True)
    paths.existing_failure.parent.mkdir(parents=True, exist_ok=True)
    paths.existing_success.write_text("无\n", encoding="utf-8")
    paths.existing_failure.write_text("无\n", encoding="utf-8")
    cache_path = tmp_path / "recent_10_cache.json"
    cache_path.write_text("{broken-json", encoding="utf-8")

    with pytest.raises(CachePersistenceError, match="正式 TXT 已写入"):
        commit_targeted_formal_single(
            (result,),
            expected_sites=(site,),
            cache_path=cache_path,
            paths=paths,
            permit=WritePermit.formal_single(252),
        )

    assert "鼠 缓存状态测试站" in paths.existing_success.read_text(encoding="utf-8")
    assert cache_path.read_text(encoding="utf-8") == "{broken-json"


class _ChunkedJsonHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    payload = b'{"id":1,"content":"ok"}'

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            body = b"<html><body><script>fetch('/api').then(r=>r.json()).then(x=>document.body.dataset.id=x.id)</script></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for offset in range(0, len(self.payload), 128):
                chunk = self.payload[offset:offset + 128]
                try:
                    self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                    self.wfile.write(chunk + b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") != "true", reason="Real Chromium streaming guard runs in CI")
def test_browser_streams_chunked_json_without_content_length() -> None:
    server = _serve(_ChunkedJsonHandler)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        capture = PlaywrightBrowserRenderer().capture(
            base + "/",
            timeout=10,
            allowed_response_urls=(base + "/api",),
        )
    finally:
        server.shutdown()
        server.server_close()
    assert len(capture.responses) == 1
    assert json.loads(capture.responses[0].body)["id"] == 1


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") != "true", reason="Real Chromium streaming guard runs in CI")
def test_browser_aborts_chunked_json_over_stream_limit(monkeypatch) -> None:
    import zodiac_v2.source.browser as browser

    class LargeHandler(_ChunkedJsonHandler):
        payload = b'{"data":"' + b"x" * 8192 + b'"}'

    monkeypatch.setattr(browser, "MAX_BROWSER_RESPONSE_BYTES", 512)
    monkeypatch.setattr(browser, "MAX_BROWSER_TOTAL_BYTES", 1024)
    server = _serve(LargeHandler)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with pytest.raises(SourceFetchError) as caught:
            PlaywrightBrowserRenderer().capture(
                base + "/",
                timeout=10,
                allowed_response_urls=(base + "/api",),
            )
    finally:
        server.shutdown()
        server.server_close()
    assert caught.value.code is SourceFetchCode.TOO_LARGE
    assert "流式正文超过字节上限" in str(caught.value)


def test_cli_formal_returns_3_when_cache_persistence_fails(monkeypatch, tmp_path: Path) -> None:
    import zodiac_v2.cli as cli

    site, result = _validated_result()

    class FakeScraper:
        def scrape_sites(self, *args, **kwargs):
            return (result,)

    monkeypatch.setattr(cli, "_runtime", lambda sites_file: ((site,), FakeScraper()))

    def fail_commit(*args, **kwargs):
        raise CachePersistenceError("正式 TXT 已写入，但缓存失败")

    monkeypatch.setattr(cli, "commit_formal_single", fail_commit)

    code = cli.main((
        "single", "--period", "252", "--formal",
        "--sites-file", str(tmp_path / "sites.json"),
        "--cache-file", str(tmp_path / "cache.json"),
        "--success-dir", str(tmp_path / "success"),
        "--failure-dir", str(tmp_path / "failure"),
    ))

    assert code == 3
