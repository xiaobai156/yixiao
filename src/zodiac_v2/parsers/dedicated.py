# ruff: noqa: E501

from __future__ import annotations

import json
import re
from typing import Protocol
from urllib.parse import urlsplit

from zodiac_v2.contracts import Candidate, DocumentType, SiteConfig, SourceBundle
from zodiac_v2.parsers.common import TextLine, decoded_script_fragments, document_lines, normalize_space, text_lines
from zodiac_v2.parsers.families import (
    AnchoredSectionFamilyParser,
    AnchoredSectionSpec,
    RegexFamilyParser,
    StrictArticleFamilyParser,
    StrictArticleSpec,
    TitleAuthorParser,
)


class Parser(Protocol):
    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]: ...


def _document_record_id(document) -> str | None:
    if document.record_id is not None:
        return document.record_id
    try:
        payload = json.loads(document.text)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, dict):
        raw_id = payload.get("id")
        if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) and str(raw_id).strip():
            return str(raw_id).strip()
    match = re.search(r"/(?:article/(?:admin|manager)|api/proxy/(?:admin-articles|manager-articles))/([a-z0-9]+)(?:/|$)", document.final_url, re.IGNORECASE)
    return match.group(1) if match else None

PATTERN_SETS: dict[str, tuple[str, ...]] = {'1139adaae11e': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*〖\\s*盛世繁华\\s*〗\\s*[^期\\r\\n]*?绝杀①肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '11ec50746468': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*《\\s*滔滔如财\\s*》\\s*[^期\\r\\n]*?绝杀①肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '1499096f9117': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀一肖\\s*❁\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*❁',),
 '284ff014bc0f': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 '293d215e6b71': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?致富大将[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '29e8867d6c32': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '2ec20f5eb80f': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*创财之星\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 '2fdfe136fb00': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?澳天空彩[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '34db1b460b8a': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*☞杀肖杀尾☞杀\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*肖\\s*[【\\[]\\s*\\d+\\s*[】\\]]\\s*尾',),
 '39c053cb1cb4': ('^第?\\s*(\\d{2,4})\\s*期.*?《杀肖杀码》\\s*☆\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[-—]+\\s*\\d+\\s*☆',),
 '411046ff8e56': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【〖\\[]\\s*吾与谁归\\s*[】〗\\]]\\s*.*?绝杀一肖.*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '41e524284174': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?天伦之乐[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '486d5a9325a8': ('^第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*绝版杀肖\\s*[】\\]]\\s*[【\\[]\\s*杀([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖\\s*[】\\]]',),
 '523828ad36a6': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?不可多得[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '56b2d65ed323': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '57d370855131': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?专家爆密[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '61f4f21fc0c9': ('^第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*☛\\s*绝杀一肖\\s*☚\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '67f8d43c8540': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?栩栩如生[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '6afcc06d6a79': ('^第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*【\\s*万山深处\\s*】\\s*✨?\\s*绝杀一肖\\s*✨?\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*(?:开|開)\\s*[:：]?\\s*[^期\\r\\n]*$',),
 '6e45ed2f6aad': ('^第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]\\s*[【\\[]\\s*杀([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '6ec114aab94b': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?解报宝彩[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '77c04b58b098': ('^第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*精准杀肖\\s*[】\\]]\\s*[【\\[]\\s*杀([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖\\s*[】\\]]',),
 '785116731e84': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?青衫如故[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '7c721c1006a0': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*[【\\[]\\s*无错杀肖\\s*[】\\]]\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '7cbd1905ca25': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*紫气东来\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 '8157de91c03b': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?谈笑封侯[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '8518cfd230ea': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?天运王道[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '86a7042b2c5a': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^\\n]{0,80}?(?:绝杀一肖|絕殺一肖|稳杀一肖|穩殺一肖|禁一肖|杀一肖|殺一肖|杀一頭|杀一头|杀肖|殺肖|禁肖)\\s*[^鼠牛虎兔龙蛇马羊猴鸡狗猪\\n]{0,24}([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:肖)?',
                  '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^\\n]{0,40}?[【\\[\\(（『「〖]\\s*(?:绝杀一肖|絕殺一肖|稳杀一肖|穩殺一肖|禁一肖|杀一肖|殺一肖|杀肖|殺肖|禁肖)\\s*[】\\]\\)）』」〗]\\s*[【\\[\\(（『「〖]?\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])',
                  '第?\\s*(\\d{2,4})\\s*期[^\\n]{0,50}?(?:绝杀|禁|杀)\\s*[【\\[\\(（『「〖]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*(?:肖)?',
                  '第?\\s*(\\d{2,4})\\s*期\\s*[（(]\\s*(?:绝杀一肖|絕殺一肖|稳杀一肖|穩殺一肖|杀一肖|殺一肖|禁一肖)\\s*[）)]\\s*[:：]?\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*肖?',
                  '第?\\s*(\\d{2,4})\\s*期\\s*杀\\s*[（(]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[）)]'),
 '8700a101dd7a': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*杀掉一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 '87afe82bc927': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*绝杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '8a357905c356': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*国际目标\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 '8fff6a364fdf': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【无错杀肖】\\s*[〖【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*[〗】\\]]',),
 '93f4cea3983a': ('^第?\\s*(\\d{2,4})\\s*期\\s*必禁一肖\\s*《\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*》',),
 '96dca145c3a1': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*天悯人五\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 '9756ab13f295': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?福星来临[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '9baefff48c76': ('^第?\\s*(\\d{2,4})\\s*期\\s*杀肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 '9df76ea238c5': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀1肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 '9ec3e2152276': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【无错杀肖】\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*[】\\]]',),
 'a4f83f737df5': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*花前月下\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 'a74424668b77': ('第?\\s*(\\d{2,4})\\s*期\\s*精杀特一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 'a85526e0f9a4': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*杀肖杀尾\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[＋+]\\s*\\d+\\s*尾\\s*[】\\]]',),
 'ad9487c71cc0': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀壹肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 'b48e088386ff': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?浅笑嫣然[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'b9d285155216': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*浮光掠影\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 'bab274f23caf': ('^第?\\s*(\\d{2,4})\\s*期\\s*绝杀1[.]肖1[.]尾\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖[.]?\\d+\\s*尾\\s*[】\\]]',),
 'bae6281d0674': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*能者为师\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 'bfa58888d585': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?百花争春[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'c436a6ea1091': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?精准至尊[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'c5e6d5564473': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?同仇敌忾[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'c81b12da46b3': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*无错杀肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'cadafe4ccbe9': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*[【\\[]\\s*杀肖杀尾\\s*[】\\]]\\s*[【\\[]\\s*杀([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖杀\\d+\\s*尾\\s*[】\\]]',),
 'cd5b9a908268': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*遇事生风\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 'd31a4c5e8f07': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【〖\\[]\\s*逍遥神仙\\s*[】〗\\]]\\s*.*?绝杀①肖.*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'd368d2f382dc': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀①肖\\s*❁\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*❁',),
 'd42fa3c9c766': ('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【《『「〖]?\\s*祥风时雨\\s*[】》』」〗]?[^\\r\\n]{0,80}?绝杀(?:一|①)肖[^\\r\\n]{0,50}?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开',),
 'd5257b10e4fa': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*〖绝杀一肖〗\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'd6dc7b3c6bf0': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?港澳神童[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'dd226b27489a': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?马经乾坤[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'e4fe8fec3bfe': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?六龙玩庄[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'eb57d04ab584': ('第?\\s*(\\d{2,4})\\s*期\\s*【澳门亡肖】\\s*《\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*》',),
 'ec9a72a8b671': ('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*[【\\[]\\s*稳杀一肖\\s*[】\\]]\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'ed33d8f61942': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?荒野孤狼[^期\\r\\n]*?绝杀一肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'edc581979125': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*Δ绝杀①肖Δ\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】',),
 'f1d8f336776e': ('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀①肖\\s*❁\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*❁',),
 'f2361cbe5126': ('^第?\\s*(\\d{2,4})\\s*期\\s*绝杀1[.]肖1[.]尾\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖[.]?\\d+尾\\s*[】\\]]',),
 'f5627854fd3b': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[^期\\r\\n]*?阿旺年华[^期\\r\\n]*?绝杀(?:一|①)肖[^期\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',),
 'f9d1956abcd0': ('第?\\s*(\\d{2,4})\\s*期[:：]?[^\\n]{0,50}?投怀送抱[^\\n]{0,30}?绝杀①肖[^\\n]{0,20}?[【《]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】》]',),
 'fc1ff5a3d08c': ('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【绝杀一肖】\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]',)}

ANCHOR_ALIASES: dict[str, str] = {'吉祥熊蕊': '吉祥雄蕊',
 '妞妞女神': '妮妮女神',
 '张青': '张 青',
 '拥挤编蓝': '拥挤编篮',
 '李四': '李 四',
 '澳门宝码第一': '不买也看看绝对赚',
 '澳门宝码第三': '创造，六合界奇迹',
 '澳门宝码第二': '超时代的六合世界',
 '白大姐': '白小姐禁一肖',
 '白胜': '白 胜',
 '葵花宝典新': '葵花宝典',
 '投怀送抱新': '投怀送抱'}

COMMON_PATTERN_ID = '86a7042b2c5a'
PATTERN_SETS[COMMON_PATTERN_ID] = (*PATTERN_SETS[COMMON_PATTERN_ID], r'第?\s*(\d{2,4})\s*期[:：]?\s*[^\n]{0,80}?(?:绝杀|絕殺|稳杀|穩殺|禁|杀|殺)\s*①肖[^鼠牛虎兔龙蛇马羊猴鸡狗猪\n]{0,24}([鼠牛虎兔龙蛇马羊猴鸡狗猪])')

STRICT_ARTICLE_SPECS: dict[str, StrictArticleSpec] = {
    '小聋人': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期.*?小龙人.*?干掉㊣一肖.*?已更新', '第?\\s*(\\d{2,4})\\s*期\\s*小龙人『干掉㊣一肖』杀\\s*[:：]?\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '穷年尽气': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*穷年尽气【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖〖\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2)*\\s*〗'),
    '意料之外': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【意料之外】（绝杀一肖）已公开', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*意料之外'),
    '十日之饮': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*十日之饮'),
    '老奇人第一版': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【老奇人】精杀一肖已公开', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【精杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', allow_pending_title=True),
    '老奇人第二版': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【老奇人】铁杀㈠肖已公开', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀㈠肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '老奇人第三版': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【老奇人】绝杀壹肖已公开', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*〖绝杀壹肖〗【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '妄下雌黄': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期\\s*绝杀一肖（\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*）', '作者[:：]\\s*妄下雌黄'),
    '无边无际': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【杀特一肖】无边无际', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*杀特一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '嘻嘻哈哈': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*嘻嘻哈哈\\s*$'),
    '金牌谜语': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【稳杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【稳杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '白小姐禁一肖': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*49官网-【白小姐禁一肖】-长期发表', '第?\\s*(\\d{2,4})\\s*期\\s*禁一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2)*\\s*】'),
    '踏雪无痕网': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*踏雪无痕网【精杀一肖】788840[a-z]\\.com(?:$|\\s)', '第?\\s*(\\d{2,4})\\s*期【精杀一肖】->\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*<-', '788840[a-z]\\.com\\s+发表于.*$'),
    '直播开奖': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[︰:：]?\\s*【绝杀一肖】\\s*☆☆祝您早日发财❀', '第?\\s*(\\d{2,4})\\s*期\\s*绝杀一肖\\s*[:：]?\\s*[【\\[]\\s*杀\\s*[:：]?\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*[开開]'),
    '狂魔乱杀': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*狂魔乱杀精准杀料【铁杀一肖】', '第?\\s*(\\d{2,4})\\s*期\\s*铁杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '隔岸观火': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*隔岸观火精准杀料【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*☛绝杀一肖☚【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '仁者能仁': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?【仁者能仁】（绝杀一肖）（已更新）', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖（\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*）', '作者[:：]\\s*仁者能仁'),
    '心有灵犀': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?【心有灵犀】（绝杀一肖）（已更新）', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*杀①肖（\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*）', '作者[:：]\\s*心有灵犀'),
    '我的人生': StrictArticleSpec('(?:1)?(\\d{3})\\s*期[:：]?【我的人生☆绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*我的人生'),
    '驷马仰秣': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*驷马仰秣『绝杀一肖』', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【绝杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*驷马仰秣'),
    '是长是短': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*‡绝杀一肖‡【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*是长是短'),
    '千王之王': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【千王之王】（绝杀一肖）已公开', '第?\\s*(\\d{2,4})\\s*期（绝杀一肖）[:：]?\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])肖'),
    '推陈出新': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【杀肖杀码】\\s*$', '第?\\s*(\\d{2,4})\\s*期《杀肖杀码》☆\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*-{2,3}\\s*\\d+☆', '推陈出新\\s+发表于'),
    '前仆后继': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]\\s*前仆后继【绝杀一肖】\\s*$', '第?\\s*(\\d{2,4})\\s*期[:：]\\s*前仆后继【绝杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】'),
    '防晒情欲': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【绝杀一肖】稳稳稳\\s*$', '第?\\s*(\\d{2,4})\\s*期【绝杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '防晒情欲\\s+发表于'),
    '自由自在': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?【绝杀一肖】自由自在\\s*$', '第?\\s*(\\d{2,4})\\s*期【绝杀一肖】【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2)*\\s*】', '自由自在\\s+发表于'),
    '怨声载路': StrictArticleSpec('热?第?\\s*(\\d{2,4})\\s*期【绝杀一肖】专业料', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*怨声载路'),
    '老奇人肖尾': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【老奇人】绝杀肖尾已公开\\s*$', '第?\\s*(\\d{2,4})\\s*期\\s*绝杀1\\.肖1\\.尾【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*肖\\s*[.。]?\\s*\\d+\\s*尾\\s*】'),
    '钧天广乐': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【\\[]?强杀①肖[】\\]]?', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀1肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '钧天广乐\\s+(?:发表于|作者)', allow_pending_title=True),
    '恩重如山': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*恩重如山〖准杀壹肖〗166605[a-z]\\.com', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*\\{杀壹肖\\}\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*166605[a-z]\\.com'),
    '素雪怜影': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【绝杀①肖】〓\\s*发财之道', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【素雪怜影】\\s*🎉?绝杀①肖🎉?【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*素雪怜影'),
    '马到成功': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【绝杀一肖】已公开', '第?\\s*(\\d{2,4})\\s*期\\s*绝杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*马到成功'),
    '红颜知己': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]\\s*澳利澳论坛【铁杀一肖】长期免费', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀一肖→\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\2\\2←', '红颜知己\\s+发表于'),
    '一鼻子灰': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]【绝杀一肖】连准中', '第?\\s*(\\d{2,4})\\s*期\\s*精杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*一鼻子灰'),
    '鸡鸣狗盗': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【绝杀一肖】免费公开', '第?\\s*(\\d{2,4})\\s*期\\s*:\\s*♠绝杀一肖♠【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*鸡鸣狗盗'),
    '子书梨落': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]【绝杀一肖】准准准', '第?\\s*(\\d{2,4})\\s*期[:：]\\s*绝杀1肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '子书梨落\\s+发表于'),
    '一尘不染': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?一尘不染〖绝杀一肖〗166605[a-z]\\.com', '第?\\s*(\\d{2,4})\\s*期[:：]\\s*绝杀1肖【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】', '作者[:：]\\s*166605[a-z]\\.com'),
    '六合兵团': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期【六合兵团】（绝杀一肖）已公开', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖（\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*）', '作者[:：]\\s*六合兵团'),
    '另眼看戏': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【\\[]?禁杀①肖[】\\]]?', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]?绝杀一肖[】\\]]?\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]', '另眼看戏\\s+(?:发表于|作者)', allow_pending_title=True),
    '澳门宝码第一': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*【\\s*稳杀一肖\\s*】\\s*不买也看看绝对赚$', '^第?\\s*(\\d{2,4})\\s*期[:：]\\s*稳杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*[开開][^期]{0,24}(?:准|错)$'),
    '澳门宝码第二': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*【\\s*绝杀一肖\\s*】\\s*超时代的六合世界$', '^第?\\s*(\\d{2,4})\\s*期[:：]\\s*绝杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*[开開][^期]{0,24}(?:准|错)$'),
    '澳门宝码第三': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期[:：]\\s*【\\s*绝杀一肖\\s*】\\s*创造[，,]\\s*六合界奇迹$', '^第?\\s*(\\d{2,4})\\s*期[:：]\\s*绝杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*[开開][^期]{0,24}(?:准|错)$'),
    '白大姐': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期\\s*【\\s*白小姐禁一肖\\s*】$', '^第?\\s*(\\d{2,4})\\s*期[:：]\\s*禁一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*[开開][^期]{0,24}(?:准|错)$'),
    '准杀一肖': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【\\s*准杀一肖\\s*】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【\\s*准杀一肖\\s*】\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*[開开][:：]?', '发表于'),
    '忘川之畔': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]\\s*各显神通', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '忘川之畔.*(?:发表于|作者)'),
    '听天委命': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【\\[]\\s*精杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期\\s*精杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '作者\\s*[:：]\\s*听天委命'),
    '群魔乱舞': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*绝杀1肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '作者\\s*[:：]\\s*群魔乱舞'),
    '西东字宙': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[〖【]\\s*[\\u200b-\\u200d\\ufeff]*西东字宙\\s*[〗】]\\s*【\\s*绝杀一肖\\s*】', '第?\\s*(\\d{2,4})\\s*期\\s*[:：]?\\s*@?绝杀一肖‡\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '[\\u200b-\\u200d\\ufeff]*西东字宙\\s+发表于.*'),
    '黄大仙': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*黄大仙\\s*【\\s*绝杀一肖\\s*】\\s*稳赚不赔$', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*肖\\s*】\\s*开', allow_pending_title=True),
    '天天发财': StrictArticleSpec('^(?:网红帖\\s*)?第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【\\s*绝杀一肖\\s*】$', '第?\\s*(\\d{2,4})\\s*期\\s*【\\s*绝杀一肖\\s*】\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*开', '^作者\\s*[:：]\\s*天天发财$'),
    '发财之道': StrictArticleSpec('^第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀高手\\s*【\\s*精杀一肖\\s*】\\s*发财之道$', '第?\\s*(\\d{2,4})\\s*期\\s*【\\s*精杀一肖\\s*】\\s*《\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*》\\s*开', '^绝杀高手\\s+发表于(?:\\s+.*)?$'),
    '精杀一肖': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*精杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期\\s*精杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '作者\\s*[:：]\\s*艳绝千秋'),
    '行走天下': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*杀一肖\\s*[】\\]]\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '作者\\s*[:：]\\s*行走天下'),
    '门庭若市': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*铁杀一肖\\s*[】\\]]\\s*稳赢策略', '第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*铁杀一肖\\s*[】\\]]\\s*一\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '门庭若市\\s+发表于.*'),
    '小小丸子': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*小小丸子\\s*【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*绝杀一肖\\s*[〖【]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){0,2}\\s*[〗】]'),
    '小村春光': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]\\s*〓\\s*天天中奖', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*小村春光\\s*🕯\\s*绝杀一肖\\s*🕯\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开', '作者\\s*[:：]\\s*小村春光'),
    '六合稳杀': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*稳杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[【\\[]\\s*稳杀一肖\\s*[】\\]]\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*[开開]', allow_pending_title=True),
    '高风亮节': StrictArticleSpec(
        '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*高风亮节[\\u200b-\\u200d\\ufeff]*\\s*【绝杀肖尾】',
        '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【绝杀1肖1尾】\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*♥\\s*\\d+尾\\s*】',
        '作者[:：]\\s*高风亮节[\\u200b-\\u200d\\ufeff]*',
    ),
    '阿拉搓克': StrictArticleSpec(
        r'\[绝杀一肖\]\s*(\d{2,4})\s*期[:：]?\s*【\s*阿拉搓克\s*━\s*手机论坛\s*】',
        r'第?\s*(\d{2,4})\s*期[:：]?\s*【绝杀一肖】\s*《\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2){2}\s*》\s*开',
        r'作者[:：]\s*阿拉搓克',
    ),
    '瓜娃之光': StrictArticleSpec(
        r'\[绝杀一肖\]\s*(\d{2,4})\s*期[:：]?\s*【\s*瓜娃之光\s*━\s*手机论坛\s*】',
        r'第?\s*(\d{2,4})\s*期[:：]?\s*绝杀1肖\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】\s*开',
        r'作者[:：]\s*瓜娃之光',
    ),
    '雷猴烧酒': StrictArticleSpec(
        r'\[绝杀一肖\]\s*(\d{2,4})\s*期[:：]?\s*【\s*雷猴烧酒\s*━\s*手机论坛\s*】',
        r'第?\s*(\d{2,4})\s*期[:：]?\s*☛绝杀一肖☚\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】\s*开',
        r'作者[:：]\s*雷猴烧酒',
    ),
    '智能铁杀': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*铁杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*铁杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*[开開]'),
    '赛码会': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*[【\\[]\\s*精杀一肖\\s*[】\\]]\\s*谨记网址', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*精杀一肖\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开'),
    '门庭若市新': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*门庭若市\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]', "第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[『']\\s*门庭若市\\s*[』']\\s*[^\\r\\n]*?绝杀一肖[^\\r\\n]*?[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开"),
    '二本万利': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期\\s*一本万利\\s*[【\\[]\\s*绝杀一肖\\s*[】\\]]', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*[≮<]\\s*绝杀一肖\\s*[≯>]\\s*[【\\[]\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*[】\\]]\\s*开'),
    '妞头码面': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【精杀一肖】\\s*牛头马面', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*【精杀一肖】\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*开'),
    '浅浅一笑': StrictArticleSpec('第?\\s*(\\d{2,4})\\s*期[:：]?\\s*浅浅一笑《精杀一肖》已更新', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*精杀一肖\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\\2){2}\\s*】\\s*开'),
    '乘风转舵': StrictArticleSpec('杀料专区\\s*(\\d{2,4})\\s*期[:：]?\\s*【绝杀一肖】', '第?\\s*(\\d{2,4})\\s*期[:：]?\\s*☛绝杀一肖☚\\s*【\\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\\s*】\\s*开', '乘风转舵\\s*发表于'),
}

ANCHORED_SECTION_SPECS: dict[str, AnchoredSectionSpec] = {
    '何仙姑': AnchoredSectionSpec(
        r'绝杀一肖\s*984440c[.]com',
        r'(?<!\d)(\d{2,4})\s*期\s*杀一肖\s*[:：]?\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]',
        r'984440c[.]com',
    ),
    '心胸开阔': AnchoredSectionSpec(r'心胸开阔', r'第?\s*(\d{2,4})\s*期[:：]?\s*心胸开阔\s*.*?绝杀一肖.*?[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]', include_anchor_line=True),
    '无地自容': AnchoredSectionSpec(r'无地自容【绝杀一肖】资料已公开', r'第?\s*(\d{2,4})\s*期[:：]?\s*绝杀一肖\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】\s*开', r'看完资料,观赏一下美女'),
    '金多宝': AnchoredSectionSpec(r'金多宝【绝杀一肖】资料已公开', r'第?\s*(\d{2,4})\s*期[:：]?\s*绝杀一肖\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*开', r'看完资料,观赏一下美女'),
    '刘伯温咯': AnchoredSectionSpec(r'刘伯温《杀1肖1尾》', r'第?\s*(\d{2,4})\s*期\s*绝杀1\s*[.．]?\s*肖1\s*[.．]?\s*尾\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*肖\s*[.．]\s*\d+\s*尾\s*】', r'刘伯温《'),
    '天高地下': AnchoredSectionSpec(r'作者\s*[:：]\s*天高地下', r'第?\s*(\d{2,4})\s*期[:：]?\s*[【\[]\s*绝杀一肖\s*[】\]]\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]'),
    '水果奶奶咯': AnchoredSectionSpec(r'水果奶奶『绝杀一肖一尾』', r'第?\s*(\d{2,4})\s*期\s*绝杀\s*『\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*\+\s*\d+\s*尾\s*』'),
    '胡言乱语': AnchoredSectionSpec(r'胡言乱语\s*(?:发表于|作者)', r'第?\s*(\d{2,4})\s*期[:：]?\s*[【\[]\s*绝杀一肖\s*[】\]]\s*❁\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2)*\s*❁'),
    '极乐世界': AnchoredSectionSpec(r'极乐世界「绝杀一肖」', r'第?\s*(\d{2,4})\s*期\s*「绝杀一肖」\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2)*\s*[】\]]'),
    '满堂规律': AnchoredSectionSpec(r'^\d{2,4}\s*期\s*[:：]\s*【\s*精杀一肖\s*】$', r'第?\s*(\d{2,4})\s*期(?:[^\n]{0,80}?[Tt]\s*\d{1,2}\s*=|[^\n]{0,80}?杀一肖\s*[:：]?)\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '七月未时': AnchoredSectionSpec(r'七月未时', r'第?\s*(\d{2,4})\s*期(?:\s*杀\s*|\b.*?T\d{1,2}\s*\+\s*08\s*=\s*)([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '香水有毒': AnchoredSectionSpec(r'香水有毒', r'第?\s*(\d{2,4})\s*期[:：]?\s*[【\[]\s*绝杀1肖码\s*[】\]]\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '智能禁肖': AnchoredSectionSpec(r'九宫禁肖', r'第?\s*(\d{2,4})\s*期[:：]?\s*☆九宫禁肖☆\s*\(\(\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*\)\)', include_anchor_line=True),
    '寄往的信': AnchoredSectionSpec(r'寄往的信【殺殺一肖】', r'第?\s*(\d{2,4})\s*期[:：]?\s*杀\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2){2}'),
    '白衫学长': AnchoredSectionSpec(r'\d{2,4}\s*期[^\n]{0,40}白衫学长', r'第?\s*(\d{2,4})\s*期[:：]?[^\n]{0,80}?(?:绝杀一肖|杀一肖|杀肖)[^鼠牛虎兔龙蛇马羊猴鸡狗猪\n]{0,24}([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '痴意少年': AnchoredSectionSpec(r'痴意少年', r'第?\s*(\d{2,4})\s*期[:：]?[^\n]{0,80}?(?:=\s*平二\s*\+\s*1\s*=\s*|杀\s*)([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '澳门公式': AnchoredSectionSpec(r'澳门公式', r'第?\s*(\d{2,4})\s*期[:：]?[^\n]{0,80}?(?:\+\s*2\s*=\s*杀\s*|杀\s*)([鼠牛虎兔龙蛇马羊猴鸡狗猪])'),
    '祸乱天下': AnchoredSectionSpec(r'祸乱天下', r'第?\s*(\d{2,4})\s*期[:：]?\s*稳杀一肖\s*[【\[]?\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2)+'),
    '顾喵喵': AnchoredSectionSpec(r'顾喵喵', r'第?\s*(\d{2,4})\s*期[:：]?\s*绝杀1肖\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]'),
}


class MacauNamedArticleParser:
    _record_aliases = {"澳门百晓生": "澳门百晓生", "澳门彩库网": "澳彩彩库网"}
    _title = re.compile(r"^第?\s*(\d{2,4})\s*期[:：]\s*绝杀一肖$")
    _period = re.compile(r"第?\s*\d{2,4}\s*期[:：]?")
    _zodiac = re.compile(r"[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]")

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        record_alias = self._record_aliases.get(site.name)
        if record_alias is None:
            return ()
        author_pattern = re.compile(rf"^作者[:：]\s*{re.escape(site.name)}$")
        record_head = re.compile(
            rf"第?\s*(\d{{2,4}})\s*期[:：]?\s*{re.escape(record_alias)}\s*☆绝杀一肖☆"
        )
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for author_index, line in enumerate(lines):
                if author_pattern.fullmatch(line.text) is None:
                    continue
                titles = [
                    (int(match.group(1)), index, title_line.text)
                    for index, title_line in enumerate(lines[:author_index])
                    if (match := self._title.fullmatch(title_line.text)) is not None
                ]
                if not titles:
                    continue
                title_period, title_index, title_text = titles[-1]
                block_end = next(
                    (
                        index
                        for index in range(author_index + 1, len(lines))
                        if lines[index].text.startswith("作者")
                    ),
                    len(lines),
                )
                article_lines = [item.text for item in lines[author_index + 1 : block_end]]
                article = normalize_space(" ".join(article_lines))
                records = list(record_head.finditer(article))
                line_starts: list[int] = []
                offset = 0
                for article_line in article_lines:
                    line_starts.append(offset)
                    offset += len(article_line) + 1
                candidates: list[Candidate] = []
                for record in records:
                    next_period = self._period.search(article, record.end())
                    segment = article[record.end() : next_period.start() if next_period else len(article)]
                    zodiac_matches = tuple(self._zodiac.finditer(segment))
                    if len(zodiac_matches) != 1:
                        continue
                    zodiac_match = zodiac_matches[0]
                    period = int(record.group(1).lstrip("0") or "0")
                    line_offset = max(
                        index
                        for index, line_start in enumerate(line_starts)
                        if line_start <= record.start()
                    )
                    period_pattern = re.compile(rf"(?<!\d){period}\s*期(?!\d)")
                    line_offset = next(
                        (
                            index
                            for index in range(line_offset, len(article_lines))
                            if period_pattern.search(article_lines[index])
                        ),
                        line_offset,
                    )
                    record_end = record.end() + zodiac_match.end()
                    record_line_offset = max(
                        index
                        for index, line_start in enumerate(line_starts)
                        if line_start <= record_end
                    )
                    next_line_offset = min(len(article_lines), record_line_offset + 1)
                    source_line_index = author_index + 1 + line_offset
                    raw_line = normalize_space(
                        " ".join(article_lines[line_offset:next_line_offset])
                    )
                    candidates.append(
                        Candidate(
                            period,
                            zodiac_match.group(1),
                            raw_line,
                            document.source_id,
                            document.page_order * 1_000_000 + source_line_index,
                            (
                                f"title-text:{normalize_space(title_text)}",
                                f"title-period:{title_period}",
                                f"title-line:{title_index}",
                                f"article-range:{title_index}-{block_end}",
                                f"author:{site.name}",
                                f"author-line:{author_index}",
                                f"record-name:{record_alias}",
                            ),
                            record_id=_document_record_id(document),
                        )
                    )
                if any(candidate.period == title_period for candidate in candidates):
                    all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class A828797NamedArticleParser:
    _specs = {
        "澳门中彩": ("一肖特杀", "准"),
        "高手杀料": ("绝杀一肖", "准"),
        "云楚官人": ("绝杀①肖", "准"),
        "富奇秦准": ("稳杀一肖", "准"),
        "皇帝猛料": ("一肖杀特", "准"),
        "旺角传真": ("只杀一肖", "准"),
        "福星金牌": ("绝杀一肖", "准"),
        "贵宾准料": ("杀一生肖", "对"),
    }

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        spec = self._specs.get(site.name)
        if spec is None:
            return ()
        column, verdict = spec
        title = re.compile(
            rf"^第?\s*(\d{{2,4}})\s*期[:：]\s*{re.escape(column)}\s*\[祝您期期大中\]$"
        )
        author = re.compile(rf"^作者\s*[:：]\s*{re.escape(site.name)}$")
        record = re.compile(
            rf"第?\s*(\d{{2,4}})\s*期[:：]?\s*{re.escape(site.name)}\s*"
            rf"☆\s*{re.escape(column)}\s*☆\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]\s*"
            rf"开\s*(?:\?\?|\d{{2}}[鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*{re.escape(verdict)}"
        )
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for title_index, title_line in enumerate(lines):
                title_match = title.fullmatch(title_line.text)
                if title_match is None:
                    continue
                author_index = next(
                    (
                        index
                        for index in range(title_index + 1, min(len(lines), title_index + 5))
                        if author.fullmatch(lines[index].text) is not None
                    ),
                    None,
                )
                if author_index is None:
                    continue
                block_end = next(
                    (
                        index
                        for index in range(author_index + 1, len(lines))
                        if lines[index].heading or lines[index].text.startswith(("上一篇", "下一篇", "作者"))
                    ),
                    len(lines),
                )
                body_lines = [item.text for item in lines[author_index + 1 : block_end]]
                article = " ".join(body_lines)
                line_starts: list[int] = []
                offset = 0
                for body_line in body_lines:
                    line_starts.append(offset)
                    offset += len(body_line) + 1
                candidates = tuple(
                    Candidate(
                        int(match.group(1).lstrip("0") or "0"),
                        match.group(2),
                        normalize_space(match.group(0)),
                        document.source_id,
                        document.page_order * 1_000_000
                        + author_index
                        + 1
                        + max(
                            index
                            for index, line_start in enumerate(line_starts)
                            if line_start <= match.start()
                        ),
                        (
                            f"title-text:{normalize_space(title_line.text)}",
                            f"title-period:{title_match.group(1)}",
                            f"title-line:{title_index}",
                            f"article-range:{title_index}-{block_end}",
                            f"author:{site.name}",
                            f"author-line:{author_index}",
                            f"record-name:{site.name}",
                        ),
                        record_id=_document_record_id(document),
                    )
                    for match in record.finditer(article)
                )
                title_period = int(title_match.group(1).lstrip("0") or "0")
                if any(candidate.period == title_period for candidate in candidates):
                    all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class KuangfengBaoyuParser:
    _title = re.compile(r"^第?\s*(\d{2,4})\s*期[:：]?\s*狂风暴雨\s*【\s*绝杀一肖\s*】\s*〓\s*抓住机会$")
    _record = re.compile(
        r"第?\s*(\d{2,4})\s*期[:：]?\s*〖\s*狂风暴雨\s*〗\s*👈\s*绝杀一肖\s*👈\s*"
        r"【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】\s*开"
    )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            title_periods = [
                int(match.group(1))
                for line in lines
                if (match := self._title.fullmatch(line.text)) is not None
            ]
            if not title_periods:
                continue
            records: list[tuple[int, str, str, int]] = []
            for index, line in enumerate(lines):
                records.extend(
                    (int(match.group(1)), match.group(2), line.text, index)
                    for match in self._record.finditer(line.text)
                )
            cycles: list[list[tuple[int, str, str, int]]] = []
            current: list[tuple[int, str, str, int]] = []
            for record in records:
                if current and current[-1][0] >= 300 and record[0] <= 20:
                    cycles.append(current)
                    current = []
                current.append(record)
            if current:
                cycles.append(current)
            title_period = title_periods[-1]
            matching = [cycle for cycle in cycles if cycle and cycle[-1][0] == title_period]
            if not matching:
                continue
            for cycle in matching:
                all_candidates.extend(
                    Candidate(
                        period,
                        zodiac,
                        line,
                        document.source_id,
                        document.page_order * 1_000_000 + index,
                        ("title:狂风暴雨/绝杀一肖", "cycle:current"),
                        record_id=document.record_id,
                    )
                    for period, zodiac, line, index in cycle
                )
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class TopicArticleCycleParser:
    _title = re.compile(r"^『\s*(?P<name>.+?)\s*-\s*绝杀一肖\s*』")
    _record = re.compile(
        r"^第?\s*(\d{2,4})\s*期\s*[:：]?\s*绝杀一肖\s*[【\[]\s*"
        r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]"
    )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for title_index, line in enumerate(lines):
                title_match = self._title.match(line.text)
                if title_match is None or title_match.group("name") != site.name:
                    continue
                article_end = next(
                    (
                        index
                        for index in range(title_index + 1, len(lines))
                        if self._title.match(lines[index].text) is not None
                    ),
                    len(lines),
                )
                records: list[tuple[int, str, str, int]] = []
                for index in range(title_index + 1, article_end):
                    records.extend(
                        (int(match.group(1)), match.group(2), lines[index].text, index)
                        for match in self._record.finditer(lines[index].text)
                    )
                cycles: list[list[tuple[int, str, str, int]]] = []
                current: list[tuple[int, str, str, int]] = []
                previous_period: int | None = None
                for record in records:
                    period = record[0]
                    reset = previous_period is not None and (
                        (previous_period >= 300 and period <= 20)
                        or (previous_period <= 20 and period >= 300)
                    )
                    if reset and current:
                        cycles.append(current)
                        current = []
                    current.append(record)
                    previous_period = period
                if current:
                    cycles.append(current)
                for cycle_index, cycle in enumerate(cycles):
                    cycle_start = cycle[0][3]
                    cycle_end = cycle[-1][3] + 1
                    evidence = (
                        f"title:{site.name}/绝杀一肖",
                        f"title-line:{title_index}",
                        f"article-range:{title_index}-{article_end}",
                        f"record-cycle:{title_index}-{cycle_index}",
                        f"block-range:{cycle_start}-{cycle_end}",
                    )
                    all_candidates.extend(
                        Candidate(
                            period,
                            zodiac,
                            raw_line,
                            document.source_id,
                            document.page_order * 1_000_000 + index,
                            evidence,
                            record_id=document.record_id,
                        )
                        for period, zodiac, raw_line, index in cycle
                    )
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class XinzhuForumParser:
    _item = re.compile(
        r"<div\b[^>]*onclick\s*=\s*['\"][^'\"]*tabTuku07ToggleItemsV22\(\s*(\d+)\s*,[^)]*\)"
        r"[^'\"]*['\"][^>]*>(.*?)</div>",
        re.IGNORECASE | re.DOTALL,
    )
    _content_start = re.compile(
        r"<div\b[^>]*class\s*=\s*['\"][^'\"]*\btab_tuku07Content(\d+)\b[^'\"]*['\"][^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    _period = re.compile(r"(\d{2,4})\s*期")
    _zodiac = re.compile(r"【\s*绝杀一肖\s*】\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)")

    @staticmethod
    def _text(source: str) -> str:
        return " ".join(line.text for line in text_lines(source))

    def _sections(self, site: SiteConfig, source: str) -> tuple[str, ...]:
        sections: list[str] = []
        if site.name in source and "青龙精解图" in source and "tabTuku07ToggleItemsV22" in source:
            sections.append(source)

        fragments = decoded_script_fragments(source, preserve_duplicates=True)
        fragment_texts = tuple(self._text(fragment) for fragment in fragments)
        for start in range(len(fragments)):
            if site.name not in fragment_texts[start]:
                continue
            header = self._text("".join(fragments[start : start + 3]))
            if "青龙精解图" not in header:
                continue
            end = len(fragments)
            for index in range(start + 1, len(fragments)):
                if site.name not in fragment_texts[index]:
                    continue
                following = self._text("".join(fragments[index : index + 3]))
                if "★" in following and "青龙精解图" not in following:
                    end = index
                    break
            sections.append("".join(fragments[start:end]))
        return tuple(sections)

    @staticmethod
    def _document_period_line_index(
        lines: tuple[str, ...],
        period: int,
        zodiac: str,
        start: int,
    ) -> int | None:
        """Locate the actual article row, not the hidden tab's period list.

        Xinzhu pages repeat every period in a navigation list before the
        decoded article rows.  A bare substring search therefore commonly
        binds a candidate to that list.  The real row is the period line
        whose small block also contains both the named column and the
        single-zodiac record.
        """
        period_pattern = re.compile(rf"(?<!\d){period}\s*期(?!\d)")
        for index in range(start, len(lines)):
            if period_pattern.search(lines[index]) is None:
                continue
            window = lines[index : min(len(lines), index + 12)]
            joined = normalize_space(" ".join(window))
            if "正版青龙图精解" in joined and "绝杀一肖" in joined and zodiac in joined:
                return index
        return None

    @staticmethod
    def _block_bounds(lines: tuple[str, ...], position: int) -> tuple[int, int]:
        marker = "正版青龙图精解"
        marker_indexes = [
            index
            for index in range(max(0, position - 8), min(len(lines), position + 2))
            if marker in lines[index]
        ]
        start = marker_indexes[-1] if marker_indexes else position
        next_marker = next(
            (
                index
                for index in range(start + 1, len(lines))
                if marker in lines[index]
            ),
            None,
        )
        end = next_marker if next_marker is not None else min(len(lines), position + 12)
        return start, max(position + 1, end)

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            document_source_lines = tuple(line.text for line in document_lines(document))
            document_cursor = 0
            for source in self._sections(site, document.text):
                items: list[tuple[int, int]] = []
                for match in self._item.finditer(source):
                    period_match = self._period.search(self._text(match.group(2)))
                    if period_match is not None:
                        items.append((int(match.group(1)), int(period_match.group(1))))

                content_matches = tuple(self._content_start.finditer(source))
                contents: dict[int, list[str]] = {}
                for index, match in enumerate(content_matches):
                    end = content_matches[index + 1].start() if index + 1 < len(content_matches) else len(source)
                    contents.setdefault(int(match.group(1)), []).append(source[match.end() : end])

                candidates: list[Candidate] = []
                for content_id, period in items:
                    for body in contents.get(content_id, []):
                        body_text = self._text(body)
                        if "正版青龙图精解" not in body_text:
                            continue
                        body_position: int | None = None
                        body_block: tuple[int, int] | None = None
                        body_raw_line = ""
                        for match in self._zodiac.finditer(body_text):
                            repeated = match.group(1)
                            if len(set(repeated)) != 1:
                                continue
                            zodiac = repeated[0]
                            if body_position is None:
                                body_position = self._document_period_line_index(
                                    document_source_lines,
                                    period,
                                    zodiac,
                                    document_cursor,
                                )
                                if body_position is None:
                                    continue
                                document_cursor = max(document_cursor, body_position + 1)
                                body_block = self._block_bounds(
                                    document_source_lines,
                                    body_position,
                                )
                                body_raw_line = normalize_space(
                                    " ".join(
                                        document_source_lines[
                                            body_position : min(body_block[1], body_position + 8)
                                        ]
                                    )
                                )
                            position = body_position
                            block_start, block_end = body_block or (position, position + 1)
                            candidates.append(
                                Candidate(
                                    period,
                                    zodiac,
                                    body_raw_line,
                                    document.source_id,
                                    document.page_order * 1_000_000 + position,
                                    (
                                        f"tab-content:{content_id}",
                                        "column:正版青龙图精解",
                                        "column:绝杀一肖",
                                        f"anchor-line:{block_start}",
                                        f"block-range:{block_start}-{block_end}",
                                    ),
                                    record_id=document.record_id,
                                )
                            )
                if candidates:
                    all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class GongzhengchuTableParser:
    _headers = ("期数", "杀一肖", "杀半波", "杀一尾", "杀一头", "开奖结果")
    _period = re.compile(r"^(\d{2,4})\s*期$")
    _zodiac = re.compile(r"^[（(]?\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[）)]?$")

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for anchor_index, line in enumerate(lines):
                if "澳门公证处【综合绝杀】" not in line.text:
                    continue
                header_index = next(
                    (
                        index
                        for index in range(anchor_index + 1, len(lines) - len(self._headers) + 1)
                        if tuple(item.text for item in lines[index : index + len(self._headers)])
                        == self._headers
                    ),
                    None,
                )
                if header_index is None:
                    continue
                candidates: list[Candidate] = []
                index = header_index + len(self._headers)
                table_end = index
                while index + 5 < len(lines):
                    period_match = self._period.fullmatch(lines[index].text)
                    zodiac_match = self._zodiac.fullmatch(lines[index + 1].text)
                    if period_match is None or zodiac_match is None:
                        table_end = index
                        break
                    record_end = index + 2
                    candidates.append(
                        Candidate(
                            int(period_match.group(1)),
                            zodiac_match.group(1),
                            normalize_space(f"{lines[index].text} {lines[index + 1].text}"),
                            document.source_id,
                            document.page_order * 1_000_000 + index,
                            (
                                f"section:{normalize_space(lines[anchor_index].text)}",
                                f"anchor-line:{anchor_index}",
                                f"section-range:{anchor_index}-{max(table_end, record_end)}",
                                "table-columns:期数/杀一肖/杀半波/杀一尾/杀一头/开奖结果",
                            ),
                            record_id=document.record_id,
                        )
                    )
                    index += 6
                    table_end = index
                if candidates:
                    all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class KaijiangFacaiTableParser:
    _site_name = "开奖发财"
    _anchor_text = "开奖发财【综合杀料】11447.COM"
    _headers = ("期数", "杀尾", "杀肖", "杀合", "杀波", "开奖")
    _anchor = re.compile(
        r'<div\b[^>]*\bclass=["\'][^"\']*\blist-title\b[^"\']*["\'][^>]*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    _table = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
    _row = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    _cell = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    _period = re.compile(r"^(\d{2,4})\s*期$")
    _zodiac = re.compile(r"^([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*肖$")

    @staticmethod
    def _cell_text(value: str) -> str:
        return normalize_space(" ".join(line.text for line in text_lines(value)))

    @staticmethod
    def _sequence_position(
        lines: tuple[TextLine, ...],
        values: tuple[str, ...],
        start: int,
    ) -> int | None:
        limit = len(lines) - len(values) + 1
        for index in range(start, max(start, limit)):
            if tuple(line.text for line in lines[index : index + len(values)]) == values:
                return index
        return None

    @staticmethod
    def _record_id(site: SiteConfig) -> str | None:
        fragment = urlsplit(site.url).fragment.strip()
        return fragment if re.fullmatch(r"\d+", fragment) else None

    @staticmethod
    def _same_endpoint(site: SiteConfig, document) -> bool:
        expected = urlsplit(site.url)
        actual = urlsplit(document.final_url)
        return (
            expected.scheme.lower() == actual.scheme.lower()
            and expected.netloc.lower() == actual.netloc.lower()
            and (expected.path or "/") == (actual.path or "/")
        )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        if site.name != self._site_name:
            return ()
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            if document.document_type is not DocumentType.HTML or not self._same_endpoint(site, document):
                continue
            source_lines = document_lines(document)
            source_cursor = 0
            anchors = tuple(self._anchor.finditer(document.text))
            for anchor_number, anchor_match in enumerate(anchors):
                if self._cell_text(anchor_match.group(1)) != self._anchor_text:
                    continue
                section_end_offset = (
                    anchors[anchor_number + 1].start()
                    if anchor_number + 1 < len(anchors)
                    else len(document.text)
                )
                section = document.text[anchor_match.end() : section_end_offset]
                table_match = self._table.search(section)
                if table_match is None:
                    continue
                rows = self._row.findall(table_match.group(1))
                if not rows:
                    continue
                header_cells = tuple(self._cell_text(value) for value in self._cell.findall(rows[0]))
                if header_cells != self._headers:
                    continue
                anchor_index = next(
                    (
                        index
                        for index in range(source_cursor, len(source_lines))
                        if source_lines[index].text == self._anchor_text
                    ),
                    None,
                )
                if anchor_index is None:
                    continue
                header_index = self._sequence_position(source_lines, self._headers, anchor_index + 1)
                if header_index is None:
                    continue
                parsed_rows: list[tuple[int, str, tuple[str, ...]]] = []
                for row_html in rows[1:]:
                    cells = tuple(self._cell_text(value) for value in self._cell.findall(row_html))
                    if len(cells) != len(self._headers):
                        continue
                    period_match = self._period.fullmatch(cells[0])
                    zodiac_match = self._zodiac.fullmatch(cells[2])
                    if period_match is None or zodiac_match is None:
                        continue
                    parsed_rows.append((int(period_match.group(1)), zodiac_match.group(1), cells))
                if not parsed_rows:
                    continue
                row_cursor = header_index + len(self._headers)
                table_candidates: list[tuple[int, str, tuple[str, ...], int]] = []
                for period, zodiac, cells in parsed_rows:
                    position = self._sequence_position(source_lines, cells, row_cursor)
                    if position is None:
                        table_candidates = []
                        break
                    table_candidates.append((period, zodiac, cells, position))
                    row_cursor = position + len(cells)
                if not table_candidates:
                    continue
                for record_offset, (period, zodiac, cells, position) in enumerate(table_candidates):
                    all_candidates.append(
                        Candidate(
                            period,
                            zodiac,
                            normalize_space(" ".join(cells)),
                            document.source_id,
                            document.page_order * 1_000_000 + position,
                            (
                                f"section:{self._anchor_text}",
                                f"anchor:{self._anchor_text}",
                                f"anchor-line:{anchor_index}",
                                f"section-range:{anchor_index}-{row_cursor}",
                                "table-columns:期数/杀尾/杀肖/杀合/杀波/开奖",
                                f"record-offset:{record_offset}",
                                "field:杀肖",
                                "source-fragment:234432",
                            ),
                            record_id=self._record_id(site),
                        )
                    )
                source_cursor = row_cursor
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class MacauCaixianzhiTableParser:
    _site_name = "澳门彩先知"
    _container = re.compile(
        r'<div\b[^>]*\bid=["\']con_jihuadanshuang50000qd_1["\'][^>]*>',
        re.IGNORECASE,
    )
    _table = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
    _row = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    _cell = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    _headers = ("期数", "禁肖", "禁半波", "禁1尾", "禁1头", "开奖结果")
    _period = re.compile(r"^(\d{2,4})\s*期$")
    _zodiac = re.compile(r"^([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*肖$")

    @staticmethod
    def _cell_text(value: str) -> str:
        return normalize_space(" ".join(line.text for line in text_lines(value)))

    @staticmethod
    def _sequence_position(
        lines: tuple[TextLine, ...],
        values: tuple[str, ...],
        start: int,
    ) -> int | None:
        limit = len(lines) - len(values) + 1
        for index in range(start, max(start, limit)):
            if tuple(line.text for line in lines[index : index + len(values)]) == values:
                return index
        return None

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        if site.name != self._site_name:
            return ()
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            if document.document_type is not DocumentType.SCRIPT:
                continue
            fragments = decoded_script_fragments(document.text, preserve_duplicates=True)
            source_lines = document_lines(document)
            for fragment_index, fragment in enumerate(fragments):
                container_match = self._container.search(fragment)
                if container_match is None:
                    continue
                section = fragment[container_match.start() :] + "".join(
                    fragments[fragment_index + 1 :]
                )
                source_cursor = 0
                for table_match in self._table.finditer(section):
                    rows = self._row.findall(table_match.group(1))
                    if not rows:
                        continue
                    header_cells = tuple(
                        self._cell_text(value) for value in self._cell.findall(rows[0])
                    )
                    if header_cells != self._headers:
                        continue
                    prefix_text = self._cell_text(section[: table_match.start()])
                    if "澳门彩先知官方网址" not in prefix_text:
                        continue
                    header_index = self._sequence_position(
                        source_lines,
                        self._headers,
                        source_cursor,
                    )
                    if header_index is None:
                        continue
                    anchor_index = next(
                        (
                            index
                            for index in range(header_index - 1, max(-1, header_index - 9), -1)
                            if "澳门彩先知官方网址" in source_lines[index].text
                        ),
                        None,
                    )
                    if anchor_index is None:
                        continue
                    parsed_rows: list[tuple[int, str, tuple[str, ...]]] = []
                    for row_html in rows[1:]:
                        cells = tuple(
                            self._cell_text(value) for value in self._cell.findall(row_html)
                        )
                        if len(cells) != len(self._headers):
                            continue
                        period_match = self._period.fullmatch(cells[0])
                        zodiac_match = self._zodiac.fullmatch(cells[1])
                        if period_match is None or zodiac_match is None:
                            continue
                        parsed_rows.append(
                            (int(period_match.group(1)), zodiac_match.group(1), cells)
                        )
                    if not parsed_rows:
                        continue
                    row_cursor = header_index + len(self._headers)
                    table_candidates: list[tuple[int, str, tuple[str, ...], int]] = []
                    for period, zodiac, cells in parsed_rows:
                        position = self._sequence_position(source_lines, cells, row_cursor)
                        if position is None:
                            table_candidates = []
                            break
                        table_candidates.append((period, zodiac, cells, position))
                        row_cursor = position + len(cells)
                    if not table_candidates:
                        continue
                    table_end = row_cursor
                    for record_offset, (period, zodiac, cells, position) in enumerate(
                        table_candidates
                    ):
                        all_candidates.append(
                            Candidate(
                                period,
                                zodiac,
                                normalize_space(" ".join(cells)),
                                document.source_id,
                                document.page_order * 1_000_000 + position,
                                (
                                    "section:澳门彩先知官方网址",
                                    "anchor:澳门彩先知官方网址",
                                    f"anchor-line:{anchor_index}",
                                    f"section-range:{anchor_index}-{table_end}",
                                    "table-columns:期数/禁肖/禁半波/禁1尾/禁1头/开奖结果",
                                    f"record-offset:{record_offset}",
                                    "field:禁肖",
                                ),
                                record_id=_document_record_id(document),
                            )
                        )
                    source_cursor = table_end
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class JinhutangTableParser:
    _table = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
    _row = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)
    _header = re.compile(r"<(?:th|td)\b.*?</(?:th|td)>", re.IGNORECASE | re.DOTALL)
    _cell = re.compile(r"<td\b.*?</td>", re.IGNORECASE | re.DOTALL)
    _period = re.compile(r"(?<!\d)(\d{2,4})\s*期")
    _zodiac = re.compile(r"^[鼠牛虎兔龙蛇马羊猴鸡狗猪]$")

    @staticmethod
    def _source_row(
        lines: tuple[TextLine, ...],
        period: int,
        zodiac: str,
        start: int,
    ) -> int | None:
        period_pattern = re.compile(rf"(?<!\d){period}\s*期(?!\d)")
        for index in range(start, len(lines)):
            if period_pattern.search(lines[index].text) is None:
                continue
            window = normalize_space(" ".join(item.text for item in lines[index : index + 8]))
            if zodiac in window:
                return index
        return None

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            document_url = urlsplit(document.final_url)
            site_url = urlsplit(site.url)
            exact_endpoint = (
                document_url.scheme.lower() == site_url.scheme.lower()
                and document_url.netloc.lower() == site_url.netloc.lower()
                and document_url.path.lower() == "/jsq.aspx"
            )
            if "金虎堂【绝杀区】" not in document.text and not exact_endpoint:
                continue
            candidates: list[Candidate] = []
            source_lines = document_lines(document)
            source_cursor = 0
            for _table_index, table in enumerate(self._table.findall(document.text)):
                rows = self._row.findall(table)
                if not rows:
                    continue
                headers = self._header.findall(rows[0])
                if len(headers) < 2:
                    continue
                first_header = _fragment_text(headers[0])
                second_header = _fragment_text(headers[1])
                if "期数" not in first_header or "杀肖" not in second_header:
                    continue
                for _row_index, row in enumerate(rows[1:]):
                    cells = self._cell.findall(row)
                    if len(cells) < 2:
                        continue
                    period_match = self._period.search(_fragment_text(cells[0]))
                    zodiac = _fragment_text(cells[1])
                    if period_match is None or self._zodiac.fullmatch(zodiac) is None:
                        continue
                    period = int(period_match.group(1))
                    position = self._source_row(source_lines, period, zodiac, source_cursor)
                    if position is None:
                        continue
                    source_cursor = position + 1
                    block_end = min(len(source_lines), position + 8)
                    candidates.append(
                        Candidate(
                            period,
                            zodiac,
                            normalize_space(" ".join(item.text for item in source_lines[position:block_end])),
                            document.source_id,
                            document.page_order * 1_000_000 + position,
                            (
                                "table-columns:期数",
                                "table-columns:杀肖",
                                f"block-range:{position}-{block_end}",
                            ),
                            record_id=document.record_id,
                        )
                    )
            if candidates:
                all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


def _fragment_text(value: str) -> str:
    text = normalize_space(" ".join(line.text for line in text_lines(value)))
    text = text.replace('"); document.writeln("', " ")
    return text.strip(" \t\r\n\"');")


_JSON_TEXT_FIELD_ORDER = (
    "title",
    "authorNickname",
    "author",
    "authorName",
    "nickname",
    "name",
    "html",
    "content",
    "body",
    "text",
)


def _json_line_count(value: object) -> int:
    if isinstance(value, str):
        return len(text_lines(value)) + sum(
            len(text_lines(fragment)) for fragment in decoded_script_fragments(value)
        )
    if isinstance(value, dict):
        keys = [key for key in _JSON_TEXT_FIELD_ORDER if key in value]
        keys.extend(key for key in value if key not in keys)
        return sum(_json_line_count(value[key]) for key in keys)
    if isinstance(value, list):
        return sum(_json_line_count(item) for item in value)
    return 0


def _json_field_line_offset(value: dict[str, object], field: str) -> int:
    keys = [key for key in _JSON_TEXT_FIELD_ORDER if key in value]
    keys.extend(key for key in value if key not in keys)
    return sum(_json_line_count(value[key]) for key in keys[: keys.index(field)])


class UserForumPostParser:
    _first_record_sites = frozenset(
        {
            "私人活动",
            "鼓舞诬陷",
            "不幸风",
            "陈旧兰花",
            "室内恶梦",
            "清爽凯蒂",
            "拥挤编蓝",
            "背叛亲戚",
            "体贴公园",
            "吉祥熊蕊",
        }
    )
    _nickname_aliases = {
        "妞妞女神": "妮妮女神",
        "拥挤编蓝": "拥挤编篮",
        "吉祥熊蕊": "吉祥雄蕊",
    }
    _topic_patterns = {
        "私人活动": re.compile(r"^\s*绝杀一肖\s*$"),
        "鼓舞诬陷": re.compile(r"^\s*必杀一肖\s*$"),
        "不幸风": re.compile(r"^\s*绝杀一肖\s*$"),
        "陈旧兰花": re.compile(r"^\s*绝杀一肖\s*$"),
        "室内恶梦": re.compile(r"^\s*绝杀一肖\s*$"),
        "清爽凯蒂": re.compile(r"^\s*绝杀一肖\s*$"),
        "拥挤编蓝": re.compile(r"^\s*绝杀一肖\s*$"),
        "背叛亲戚": re.compile(r"^\s*绝杀一肖\s*$"),
        "体贴公园": re.compile(r"^\s*绝杀一肖\s*$"),
        "吉祥熊蕊": re.compile(r"^\s*大杀一肖\s*$"),
        "神的传说": re.compile(r"杀一肖"),
        "妞妞女神": re.compile(r"绝杀一肖"),
        "预判晚风": re.compile(r"绝杀一肖"),
        "神之一杀": re.compile(r"杀一肖"),
        "福禄寿喜财": re.compile(r"^\s*\d{2,4}\s*期\s*$"),
        "幸运特码": re.compile(r"^\s*\d{2,4}\s*$"),
        "青云子": re.compile(r"资料杀一肖"),
        "连中谎言": re.compile(r"^\s*\d{2,4}\s+重头来过\s*$"),
        "请叫我菲菲": re.compile(r"^\s*\d{2,4}\s*$"),
        "钟哥啊": re.compile(r"稳杀一肖"),
    }
    _record_patterns = {
        "私人活动": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀\s*①肖\s*❁\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2){2}\s*❁"),
        "鼓舞诬陷": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*必\s*杀\s*一肖\s*⦥\s*[|｜]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[|｜]\s*⦤"),
        "不幸风": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀\s*1\s*肖\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】"),
        "陈旧兰花": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀一肖\s*▼\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*▼"),
        "室内恶梦": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀一肖\s*\?\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*\?"),
        "清爽凯蒂": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[（(]\s*绝杀一肖\s*[）)]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2){2}"),
        "拥挤编蓝": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀\s*1\s*肖\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】"),
        "背叛亲戚": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*绝杀一肖\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】"),
        "体贴公园": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*绝\s*杀\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】\s*杀"),
        "吉祥熊蕊": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*大\s*杀\s*一肖\s*[￥¥]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[￥¥]"),
        "神的传说": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*杀(?:一肖)?\s*[（(]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[）)]"),
        "妞妞女神": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*♥?\s*绝杀一?肖\s*[—-]+\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
        "预判晚风": re.compile(r"(?<!\d)(\d{2,4})\s*期[:：]?\s*♥?绝杀一肖♥?\s*【\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*】"),
        "神之一杀": re.compile(r"(?<!\d)(\d{2,4})\s*(?:期)?\s*杀\s*[（(]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[）)]"),
        "福禄寿喜财": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*杀\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
        "幸运特码": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*[:：]?\s*杀\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
        "青云子": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*杀\s*《\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*》"),
        "连中谎言": re.compile(r"(?<!\d)(\d{2,4})\s*绝杀一肖\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
        "请叫我菲菲": re.compile(r"(?<!\d)(\d{2,4})\s*杀\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
        "钟哥啊": re.compile(r"(?<!\d)(\d{2,4})\s*期\s*杀\s*[:：]?\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
    }

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        topic_pattern = self._topic_patterns.get(site.name)
        record_pattern = self._record_patterns.get(site.name)
        parsed_site = urlsplit(site.url)
        user_match = re.search(r"/users/(\d+)(?:/|$)", parsed_site.path + "/" + parsed_site.fragment)
        if topic_pattern is None or record_pattern is None or user_match is None:
            return ()
        expected_user_id = int(user_match.group(1))
        expected_nickname = self._nickname_aliases.get(site.name, site.name)
        candidates: list[Candidate] = []
        for document in bundle.documents:
            if document.document_type is not DocumentType.JSON:
                continue
            response_match = re.search(r"/api/v1/users/(\d+)/forums(?:[/?]|$)", urlsplit(document.final_url).path)
            if response_match is None or int(response_match.group(1)) != expected_user_id:
                continue
            try:
                rows = json.loads(document.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(rows, list):
                continue
            row_line_starts: list[int] = []
            document_line_offset = 0
            for row in rows:
                row_line_starts.append(document_line_offset)
                document_line_offset += _json_line_count(row)
            document_candidates: list[Candidate] = []
            record_ids_by_draw: dict[int, set[str]] = {}
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict) or row.get("status") != "published":
                    continue
                record_id = row.get("id")
                if (
                    isinstance(record_id, bool)
                    or not isinstance(record_id, (str, int))
                    or not str(record_id).strip()
                ):
                    continue
                record_id_text = str(record_id).strip()
                draw = row.get("draw")
                user = row.get("user")
                topic = row.get("topic")
                content = row.get("content")
                if (
                    isinstance(draw, bool)
                    or not isinstance(draw, int)
                    or not isinstance(user, dict)
                    or row.get("user_id") != expected_user_id
                    or user.get("id") != expected_user_id
                    or user.get("nickname") != expected_nickname
                    or not isinstance(topic, str)
                    or topic_pattern.search(topic) is None
                    or not isinstance(content, str)
                ):
                    continue
                record_ids_by_draw.setdefault(draw, set()).add(record_id_text)
                record_matches = [
                    (line_index, line, match)
                    for line_index, line in enumerate(text_lines(content))
                    for match in record_pattern.finditer(line.text)
                ]
                if not record_matches:
                    continue
                if site.name in self._first_record_sites:
                    line_index, line, match = record_matches[0]
                    if int(match.group(1)) != draw:
                        continue
                else:
                    draw_match = next(
                        (
                            (line_index, line, match)
                            for line_index, line, match in record_matches
                            if int(match.group(1)) == draw
                        ),
                        None,
                    )
                    if draw_match is None:
                        continue
                    line_index, line, match = draw_match
                document_candidates.append(
                    Candidate(
                        draw,
                        match.group(2),
                        line.text,
                        document.source_id,
                        document.page_order * 1_000_000
                        + row_line_starts[row_index]
                        + _json_field_line_offset(row, "content")
                        + line_index,
                        (
                            f"heading:forum-draw:{draw}",
                            f"post:{record_id_text}",
                            f"record-cycle:{record_id_text}",
                            f"record-offset:{match.start()}",
                            f"post-range:{row_line_starts[row_index]}-"
                            f"{row_line_starts[row_index] + _json_line_count(row)}",
                        ),
                        record_id=record_id_text,
                    )
                )
            ambiguous_draws = {
                draw for draw, record_ids in record_ids_by_draw.items() if len(record_ids) > 1
            }
            candidates.extend(
                candidate
                for candidate in document_candidates
                if candidate.period not in ambiguous_draws
            )
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)


class SanguaiPeriodSectionParser:
    _period = re.compile(r"第?\s*(\d{2,4})\s*期\s*杀肖统计")
    _site_names = frozenset({"关公杀一肖", "佛主禁肖图", "三怪禁肖图"})

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        if site.name not in self._site_names:
            return ()
        section = re.compile(
            rf"^{re.escape(site.name)}\s*[:：]\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]"
        )
        candidates: list[Candidate] = []
        for document in bundle.documents:
            current_period: int | None = None
            period_index: int | None = None
            lines = document_lines(document)
            for index, line in enumerate(lines):
                period_match = self._period.search(line.text)
                if period_match is not None:
                    current_period = int(period_match.group(1).lstrip("0") or "0")
                    period_index = index
                    continue
                section_match = section.search(line.text)
                if current_period is None or period_index is None or section_match is None:
                    continue
                candidates.append(
                    Candidate(
                        current_period,
                        section_match.group(1),
                        normalize_space(" ".join(item.text for item in lines[period_index : index + 1])),
                        document.source_id,
                        document.page_order * 1_000_000 + period_index,
                        ("heading:杀肖统计", f"section:{site.name}"),
                        record_id=document.record_id,
                    )
                )
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)


class TiankongShujinguangParser:
    _record = re.compile(
        r"第?\s*(\d{2,4})\s*期[:：]?\s*买\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]\s*输尽光"
    )

    @staticmethod
    def _match_location(
        lines: tuple[TextLine, ...],
        start: int,
        end: int,
        match_start: int,
    ) -> tuple[int, int]:
        cursor = 0
        for offset, item in enumerate(lines[start : min(end, start + 4)]):
            line_end = cursor + len(item.text)
            if match_start <= line_end:
                return start + offset, max(0, match_start - cursor)
            cursor = line_end + 1
        return start, match_start

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for anchor_index, line in enumerate(lines):
                if "澳门资料『输尽光』" not in line.text:
                    continue
                candidates: list[Candidate] = []
                section_end = next(
                    (
                        index
                        for index in range(anchor_index + 1, len(lines))
                        if lines[index].text.startswith("澳门资料『")
                    ),
                    len(lines),
                )
                seen: set[tuple[int, int, int, str]] = set()
                for index in range(anchor_index + 1, section_end):
                    combined = normalize_space(
                        " ".join(item.text for item in lines[index : min(section_end, index + 4)])
                    )
                    for match in self._record.finditer(combined):
                        period = int(match.group(1))
                        position, record_offset = self._match_location(
                            lines,
                            index,
                            section_end,
                            match.start(1),
                        )
                        zodiac = match.group(2)
                        key = (position, record_offset, period, zodiac)
                        if key in seen:
                            continue
                        seen.add(key)
                        raw_line = normalize_space(match.group(0))
                        candidates.append(
                            Candidate(
                                period,
                                zodiac,
                                raw_line,
                                document.source_id,
                                document.page_order * 1_000_000 + position,
                                (
                                    f"section:{normalize_space(line.text)}",
                                    "anchor:澳门资料『输尽光』",
                                    f"anchor-line:{anchor_index}",
                                    f"section-range:{anchor_index}-{section_end}",
                                    f"record-offset:{record_offset}",
                                    "field:买/输尽光",
                                ),
                                record_id=document.record_id,
                            )
                        )
                if candidates:
                    all_candidates.extend(candidates)
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class MacauJinshouzhiParser:
    _record = re.compile(
        r"第?\s*(\d{2,4})\s*期[:：]?[^\n]{0,30}?[绝絕]殺一肖\s*[（(【\[]\s*"
        r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])(?:\2)*\s*[）)】\]]",
        re.IGNORECASE,
    )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        all_candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            starts = []
            for index, line in enumerate(lines):
                heading = normalize_space(" ".join(item.text for item in lines[index : index + 2]))
                if "澳门金手指" in line.text and "综合绝杀区" in heading:
                    starts.append(index)
            for start in starts:
                end = next(
                    (
                        index
                        for index in range(start + 1, len(lines))
                        if "澳门金手指" in lines[index].text
                    ),
                    len(lines),
                )
                block = lines[start:end]
                if not any("殺一肖" in line.text or "杀一肖" in line.text for line in block):
                    continue
                anchor_text = normalize_space(lines[start].text)
                for offset, line in enumerate(block):
                    for match in self._record.finditer(line.text):
                        all_candidates.append(
                            Candidate(
                                int(match.group(1)),
                                match.group(2),
                                line.text,
                                document.source_id,
                                document.page_order * 1_000_000 + start + offset,
                                (
                                    f"section:{anchor_text}",
                                    f"anchor:{anchor_text}",
                                    f"anchor-line:{start}",
                                    f"section-range:{start}-{end}",
                                    "field:殺一肖",
                                ),
                                record_id=document.record_id,
                            )
                        )
        all_candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(all_candidates)


class TtssPeriodArticleParser:
    _title = re.compile(r"^(\d{2,4})期\s*[:：]\s*(.+)$")
    _record = re.compile(
        r"^(\d{2,4})期.*?[：:]\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]"
    )
    _result = re.compile(r"^\s*[【\[]\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]")
    _dynamic_record = re.compile(
        r"^(\d{2,4})期.*?绝杀(?:一|①)肖.*?[【\[]\s*"
        r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]"
    )
    _script_record = re.compile(
        r"^(\d{2,4})期\s*[:：].*?[\u3016【\[]\s*绝杀(?:一|①)肖\s*[\u3017】\]]\s*"
        r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])"
    )

    @staticmethod
    def _candidate(
        document,
        period: int,
        zodiac: str,
        raw_line: str,
        page_index: int,
        evidence: tuple[str, ...],
    ) -> Candidate:
        return Candidate(
            period,
            zodiac,
            raw_line,
            document.source_id,
            document.page_order * 1_000_000 + page_index,
            evidence,
            record_id=document.record_id,
        )

    def _parse_static(
        self,
        site: SiteConfig,
        document,
        lines,
        titles: list[tuple[int, re.Match[str]]],
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        for title_position, (title_index, title_match) in enumerate(titles):
            end_index = (
                titles[title_position + 1][0]
                if title_position + 1 < len(titles)
                else len(lines)
            )
            title_line = lines[title_index].text
            for index in range(title_index + 1, end_index):
                result_match = self._result.match(lines[index].text)
                if result_match is None:
                    continue
                candidates.append(
                    self._candidate(
                        document,
                        int(title_match.group(1)),
                        result_match.group(1),
                        normalize_space(f"{title_line} {lines[index].text}"),
                        title_index,
                        (
                            "block:0",
                            f"title-line:{title_index}",
                            f"title-period:{title_match.group(1)}",
                            f"title-text:{site.article_keyword}",
                            "field:杀一肖",
                        ),
                    )
                )
                break
        return candidates

    def _parse_manager_json(self, site: SiteConfig, document, lines) -> list[Candidate]:
        author_indexes = [
            index
            for index, line in enumerate(lines)
            if line.text == f"作者:{site.article_keyword}"
        ]
        if len(author_indexes) != 1:
            return []
        author_index = author_indexes[0]
        title_candidates = [
            (index, match)
            for index, line in enumerate(lines[:author_index])
            if (match := self._title.fullmatch(line.text)) is not None
        ]
        if len(title_candidates) != 1:
            return []
        title_index, title_match = title_candidates[0]
        if re.search(r"绝杀(?:一|①)肖", lines[title_index].text) is None:
            return []
        candidates: list[Candidate] = []
        for index in range(author_index + 1, len(lines)):
            record_match = self._dynamic_record.search(lines[index].text)
            if record_match is None:
                continue
            candidates.append(
                self._candidate(
                    document,
                    int(record_match.group(1)),
                    record_match.group(2),
                    lines[index].text,
                    index,
                    (
                        "block:0",
                        f"title-line:{title_index}",
                        f"title-period:{title_match.group(1)}",
                        f"author:{site.article_keyword}",
                        f"author-line:{author_index}",
                        "field:杀一肖",
                    ),
                )
            )
        return candidates

    def _parse_script(self, site: SiteConfig, document, lines) -> list[Candidate]:
        author_indexes = [
            index
            for index, line in enumerate(lines)
            if line.text == f"作者:{site.article_keyword}"
        ]
        if len(author_indexes) != 1:
            return []
        author_index = author_indexes[0]
        title_candidates = [
            (index, match)
            for index, line in enumerate(lines[:author_index])
            if (match := self._title.fullmatch(line.text)) is not None
            and site.article_keyword in match.group(2)
        ]
        if len(title_candidates) != 1:
            return []
        title_index, title_match = title_candidates[0]
        if re.search(r"绝杀(?:一|①)肖", lines[title_index].text) is None:
            return []

        content_end = next(
            (
                index
                for index in range(author_index + 1, len(lines))
                if lines[index].text.startswith("作者:")
                or "上一篇" in lines[index].text
                or "下一篇" in lines[index].text
            ),
            len(lines),
        )
        candidates: list[Candidate] = []
        for index in range(author_index + 1, content_end):
            record_match = self._script_record.search(lines[index].text)
            if record_match is None:
                continue
            candidates.append(
                self._candidate(
                    document,
                    int(record_match.group(1)),
                    record_match.group(2),
                    lines[index].text,
                    index,
                    (
                        "block:0",
                        "source-type:script",
                        f"title-line:{title_index}",
                        f"title-period:{title_match.group(1)}",
                        f"title-text:{site.article_keyword}",
                        f"author:{site.article_keyword}",
                        f"author-line:{author_index}",
                        f"section-range:{author_index + 1}-{content_end}",
                        "field:杀一肖",
                    ),
                )
            )
        return candidates

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        if site.article_keyword is None:
            return ()
        candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            if document.document_type is DocumentType.JSON:
                candidates.extend(self._parse_manager_json(site, document, lines))
                continue
            if document.document_type is DocumentType.SCRIPT:
                candidates.extend(self._parse_script(site, document, lines))
                continue
            titles = [
                (index, match)
                for index, line in enumerate(lines)
                if (match := self._title.fullmatch(line.text)) is not None
                and site.article_keyword in match.group(2)
            ]
            if not titles:
                continue
            if len(titles) != 1 or not any("不保留大量往期记录" in line.text for line in lines):
                candidates.extend(self._parse_static(site, document, lines, titles))
                continue
            title_index, title_match = titles[0]
            content_start = next(
                (index + 1 for index in range(title_index + 1, len(lines)) if "不保留大量往期记录" in lines[index].text),
                None,
            )
            if content_start is None:
                continue
            content_end = next(
                (index for index in range(content_start, len(lines)) if "上一篇" in lines[index].text),
                len(lines),
            )
            for index in range(content_start, content_end):
                line = lines[index]
                match = self._record.search(line.text)
                if match is None:
                    continue
                candidates.append(
                    self._candidate(
                        document,
                        int(match.group(1)),
                        match.group(2),
                        line.text,
                        index,
                        (
                            "block:0",
                            f"title-line:{title_index}",
                            f"title-period:{title_match.group(1)}",
                            f"title-text:{site.article_keyword}",
                            "field:杀一肖",
                        ),
                    )
                )
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)


def parser_entries() -> tuple[tuple[str, Parser], ...]:
    entries: list[tuple[str, Parser]] = [
        (
            f"regex.{identifier}",
            RegexFamilyParser(patterns, anchor_aliases=ANCHOR_ALIASES),
        )
        for identifier, patterns in PATTERN_SETS.items()
    ]
    entries.extend(
        (
            ("family.anchored_section", AnchoredSectionFamilyParser(ANCHORED_SECTION_SPECS)),
            ("family.strict_article", StrictArticleFamilyParser(STRICT_ARTICLE_SPECS)),
            (
                "special.demon_title_author",
                TitleAuthorParser(
                    r"第?\s*(\d{2,4})\s*期.*?(599983[a-g]\.com)",
                    r"第?\s*(\d{2,4})\s*期[:：]?\s*[【\[]\s*绝杀一肖\s*[】\]]\s*[【\[]\s*"
                    r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[】\]]",
                ),
            ),
            (
                "special.guangdong_title_author",
                TitleAuthorParser(
                    r"第?\s*(\d{2,4})\s*期.*?(94245[a-g]\.com)",
                    r"第?\s*(\d{2,4})\s*期[:：]?[^\n]{0,20}?必杀一肖[^鼠牛虎兔龙蛇马羊猴鸡狗猪\n]{0,12}"
                    r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])",
                ),
            ),
            ("special.macau_jinshouzhi", MacauJinshouzhiParser()),
            ("special.macau_named_article", MacauNamedArticleParser()),
            ("special.a828797_named_article", A828797NamedArticleParser()),
            ("special.kuangfeng_baoyu", KuangfengBaoyuParser()),
            ("special.article_40783e", TopicArticleCycleParser()),
            ("special.xinzhu_forum", XinzhuForumParser()),
            ("special.macau_caixianzhi_table", MacauCaixianzhiTableParser()),
            ("special.kaijiang_facai_table", KaijiangFacaiTableParser()),
            ("special.ttss_period_article", TtssPeriodArticleParser()),
            ("special.jinhutang_table", JinhutangTableParser()),
            ("special.gongzhengchu_table", GongzhengchuTableParser()),
            ("special.sanguai_period_section", SanguaiPeriodSectionParser()),
            ("special.user_forum_post", UserForumPostParser()),
            ("special.tiankong_shujinguang", TiankongShujinguangParser()),
            (
                "special.feng_named_home",
                RegexFamilyParser(
                    (
                        r"第?\s*(\d{2,4})\s*期[^\n]{0,20}?绝杀\s*1\s*[.．]\s*肖"
                        r"[^鼠牛虎兔龙蛇马羊猴鸡狗猪\n]{0,12}([鼠牛虎兔龙蛇马羊猴鸡狗猪])",
                    ),
                    anchor_aliases=ANCHOR_ALIASES,
                ),
            ),
        )
    )
    return tuple(entries)
