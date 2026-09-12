from __future__ import annotations

import ssl

import truststore

from zodiac_v2.source import http as http_module
from zodiac_v2.source.http import RequestsTransport, UrllibTransport


class _Response:
    status = 200
    headers = {"Content-Type": "text/plain; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return b"ok"

    def geturl(self):
        return "https://example.test/"


def test_urllib_transport_uses_verified_system_trust_context(monkeypatch):
    captured = {}

    def fake_urlopen(request, *, timeout, context):
        captured["context"] = context
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    transport = UrllibTransport()
    result = transport.request("https://example.test/", timeout=3, max_bytes=100)
    assert result.status == 200
    assert captured["context"] is transport.ssl_context
    assert isinstance(transport.ssl_context, truststore.SSLContext)
    assert transport.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert transport.ssl_context.check_hostname is True
    assert captured["timeout"] == 3


def test_urllib_transport_keeps_explicit_verified_context(monkeypatch):
    captured = {}
    explicit = ssl.create_default_context()

    def fake_urlopen(request, *, timeout, context):
        captured["context"] = context
        return _Response()

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    transport = UrllibTransport(ssl_context=explicit)
    transport.request("https://example.test/", timeout=2, max_bytes=100)
    assert captured["context"] is explicit
    assert explicit.verify_mode == ssl.CERT_REQUIRED
    assert explicit.check_hostname is True


def test_requests_transport_uses_verified_system_trust_context():
    transport = RequestsTransport()
    assert isinstance(transport.ssl_context, truststore.SSLContext)
    assert transport.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert transport.ssl_context.check_hostname is True


def test_requests_transport_reuses_session_until_closed(monkeypatch):
    class Response:
        status_code = 200
        url = "https://example.test/"
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        class Raw:
            decode_content = True

            def read(self, _limit):
                return b"ok"

        raw = Raw()

    class Session:
        def __init__(self):
            self.mounts = []
            self.headers = {}
            self.urls = []
            self.closed = False

        def mount(self, prefix, adapter):
            self.mounts.append((prefix, adapter))

        def get(self, url, **kwargs):
            self.urls.append((url, kwargs))
            return Response()

        def close(self):
            self.closed = True

    sessions = []

    def make_session():
        session = Session()
        sessions.append(session)
        return session

    monkeypatch.setattr(http_module.requests, "Session", make_session)
    transport = RequestsTransport()

    transport.request("https://example.test/one", timeout=1, max_bytes=100)
    transport.request("https://example.test/two", timeout=1, max_bytes=100)

    assert len(sessions) == 1
    assert [url for url, _ in sessions[0].urls] == [
        "https://example.test/one",
        "https://example.test/two",
    ]
    assert sessions[0].urls[0][1]["verify"] is True
    transport.close()
    transport.close()
    assert sessions[0].closed
