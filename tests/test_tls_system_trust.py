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
