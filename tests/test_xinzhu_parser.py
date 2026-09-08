from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import XinzhuForumParser
from zodiac_v2.validation.conflicts import validate_candidates

_URL = "https://rpczmj.flzw4-yz5wn-mlrxxt.xyz/"


def _site() -> SiteConfig:
    return SiteConfig(
        name="新竹论坛",
        url=_URL,
        direction=Direction.TOP,
        section=SiteSection.NEW,
        parser_id="special.xinzhu_forum",
        source_policy="http_documents",
    )


def _bundle(*sections: str) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text="\n".join(sections),
                final_url=_URL,
                document_type=DocumentType.SCRIPT,
                priority=0,
                source_id="script:xinzhu",
                page_order=0,
            ),
        )
    )


def _section(title: str, *rows: str) -> str:
    table = "".join(f"<tr><td>{row}</td></tr>" for row in rows)
    return f'<div class="dz_title37-3"><span>{title}</span></div><table>{table}</table>'


def test_uses_semantic_jujinyixiao_section_and_keeps_top_order() -> None:
    bundle = _bundle(
        _section(
            "★绝禁一肖★",
            "224期:绝禁一肖╠鼠鼠鼠╣开0000准",
            "223期:绝禁一肖╠龙龙龙╣开猴23准",
            "222期:绝禁一肖╠牛牛牛╣开蛇26准",
            "221期:绝禁一肖╠兔兔兔╣开马01准",
            "220期:绝禁一肖╠鸡鸡鸡╣开羊48准",
        ),
        _section(
            "★绝杀一肖★",
            "224期:绝杀一肖╠鸡鸡鸡╣开0000准",
        ),
    )

    candidates = XinzhuForumParser().parse(_site(), bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (224, "鼠"),
        (223, "龙"),
        (222, "牛"),
        (221, "兔"),
        (220, "鸡"),
    ]
    assert all("column:绝禁一肖" in candidate.evidence for candidate in candidates)
    assert all("title-text:★绝禁一肖★" in candidate.evidence for candidate in candidates)
    assert all("绝杀一肖" not in candidate.raw_line for candidate in candidates)


def test_validation_accepts_224_mouse_from_same_semantic_block() -> None:
    bundle = _bundle(
        _section(
            "★绝禁一肖★",
            "224期:绝禁一肖╠鼠鼠鼠╣开0000准",
            "223期:绝禁一肖╠龙龙龙╣开猴23准",
            "222期:绝禁一肖╠牛牛牛╣开蛇26准",
            "221期:绝禁一肖╠兔兔兔╣开马01准",
            "220期:绝禁一肖╠鸡鸡鸡╣开羊48准",
        )
    )
    candidates = XinzhuForumParser().parse(_site(), bundle)

    decision = validate_candidates(_site(), bundle, candidates, 224)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (224, "鼠")


def test_section_boundary_excludes_same_period_from_next_column() -> None:
    bundle = _bundle(
        _section(
            "★绝禁一肖★",
            "224期:绝禁一肖╠鼠鼠鼠╣开0000准",
            "223期:绝禁一肖╠龙龙龙╣开猴23准",
        ),
        _section(
            "★另一个栏目★",
            "224期:绝禁一肖╠虎虎虎╣开0000准",
        ),
    )

    candidates = XinzhuForumParser().parse(_site(), bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (224, "鼠"),
        (223, "龙"),
    ]


def test_missing_semantic_title_fails_closed() -> None:
    bundle = _bundle(
        _section(
            "★绝杀一肖★",
            "224期:绝杀一肖╠鸡鸡鸡╣开0000准",
        )
    )

    assert XinzhuForumParser().parse(_site(), bundle) == ()

