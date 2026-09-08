from __future__ import annotations

import pytest

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import YizhixiaArticleParser
from zodiac_v2.source.documents import SourceIdentityError, source_identity, validate_final_url

_URL = "https://4.48kk49.com:1888/Article/ar_content/id/1480/tid/82.html"


def _site() -> SiteConfig:
    return SiteConfig(
        name="一只狎",
        url=_URL,
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="special.yizhixia_article",
        source_policy="http_documents",
        article_keyword="一只狎",
    )


def _bundle(url: str = _URL, record_id: str | None = "1480") -> SourceBundle:
    rows = [
        "225期: 一只狎经原创《绝杀一肖》",
        "温馨提示:为了提高网速，部分连错期数记录已删除",
        "225期 原创绝杀一肖 :【猴】 开 ?? 准",
        "224期 原创绝杀一肖 :【鸡】 开 09,狗 准",
        "223期 原创绝杀一肖 :【龙】 开 23,猴 准",
        "222期 原创绝杀一肖 :【兔】 开 26,蛇 准",
        "221期 原创绝杀一肖 :【猴】 开 01,马 准",
        "220期 原创绝杀一肖 :【兔】 开 48,羊 准",
        "219期 原创绝杀一肖 :【虎】 开 43,鼠 准",
        "218期 原创绝杀一肖 :【龙】 开 17,虎 准",
        "217期 原创绝杀一肖 :【鸡】 开 26,蛇 准",
        "216期 原创绝杀一肖 :【鼠】 开 37,马 准",
        "上一篇：225期: 代王精英高手【36码中特】",
    ]
    document = SourceDocument(
        "\n".join(rows),
        url,
        DocumentType.HTML,
        0,
        f"html:{url}",
        0,
        record_id,
    )
    return SourceBundle((document,), ("scan_complete:1",), scan_complete=True)


def test_source_identity_binds_ar_content_article_id() -> None:
    assert source_identity(_URL).article_id == "1480"
    with pytest.raises(SourceIdentityError):
        validate_final_url(_URL, _URL.replace("id/1480", "id/1484"))


def test_yizhixia_parser_returns_same_block_history() -> None:
    candidates = YizhixiaArticleParser().parse(_site(), _bundle())

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (225, "猴"),
        (224, "鸡"),
        (223, "龙"),
        (222, "兔"),
        (221, "猴"),
        (220, "兔"),
        (219, "虎"),
        (218, "龙"),
        (217, "鸡"),
        (216, "鼠"),
    ]
    assert all(candidate.record_id == "1480" for candidate in candidates)
    assert all("title-semantic:一只狎经原创绝杀一肖" in candidate.evidence for candidate in candidates)


def test_yizhixia_parser_rejects_wrong_article_document() -> None:
    wrong_url = _URL.replace("id/1480", "id/1484")

    assert YizhixiaArticleParser().parse(_site(), _bundle(wrong_url, "1484")) == ()


def test_yizhixia_parser_accepts_dynamic_current_title_period() -> None:
    rows = [
        "227期: 一只狎经原创《绝杀一肖》",
        "227期 原创绝杀一肖 :【狗】 开 16,兔 准",
        "226期 原创绝杀一肖 :【羊】 开 17,虎 准",
        "225期 原创绝杀一肖 :【猴】 开 01,马 准",
        "上一篇：225期: 代王精英高手【36码中特】",
    ]
    document = SourceDocument(
        "\n".join(rows),
        _URL,
        DocumentType.HTML,
        0,
        f"html:{_URL}",
        0,
        "1480",
    )

    candidates = YizhixiaArticleParser().parse(
        _site(),
        SourceBundle((document,), ("scan_complete:1",), scan_complete=True),
    )

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (227, "狗"),
        (226, "羊"),
        (225, "猴"),
    ]
    assert all("title-period:227" in candidate.evidence for candidate in candidates)
