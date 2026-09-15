from __future__ import annotations

import base64
import json
import zlib

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import ShenyiUwuDynamicParser
from zodiac_v2.source.http import decode_kxusu_dynamic_html


def _packed_script(html: str) -> str:
    def pack(value: str) -> str:
        return base64.b64encode(zlib.compress(value.encode(), wbits=-15)).decode()

    payload = {"_v54gOM": [pack(html)], "_vt": pack("神医乌乌")}
    return "var __jGr = " + repr(json.dumps(payload, ensure_ascii=False)) + ";"


def _site() -> SiteConfig:
    return SiteConfig(
        "神医乌乌",
        "https://dh81163.2cv5a08j69.cyou/ZdKOZr7CBi.html",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.shenyi_uwu_dynamic",
        "http_kxusu_dynamic",
    )


def test_kxusu_script_decoder_reconstructs_dynamic_html() -> None:
    html = "<p>作者:神医乌乌</p><li>259期：杀肖杀码⇨【兔+48】</li>"
    assert decode_kxusu_dynamic_html(_packed_script(html)) == html


def test_shenyi_uwu_parser_reads_target_records_from_dynamic_document() -> None:
    html = (
        "<p>作者:神医乌乌</p>"
        "<li>258期：❀杀肖杀码❀⇨【狗+01】开:鸡46中</li>"
        "<li>259期：❀杀肖杀码❀⇨【兔+48】开:發00中</li>"
    )
    document = SourceDocument(
        html,
        _site().url,
        DocumentType.HTML,
        0,
        "kxusu-html:https://api.kxusu.com/js-111-10492?v=09160",
        0,
    )
    candidates = ShenyiUwuDynamicParser().parse(_site(), SourceBundle((document,)))
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(258, "狗"), (259, "兔")]
