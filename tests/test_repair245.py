import json

import pytest

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import UserForumPostParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates


def forum(name, content, topic=None, user_id=None):
    uid = 180502 if name == '寒武忌' else 166365
    url = f'https://example.test/#/users/{uid}'
    site = SiteConfig(name, url, Direction.BOTTOM, SiteSection.NEW,
                      'special.user_forum_post', 'api_then_http',
                      api_url=f'https://example.test/api/v1/users/{uid}/forums?per_page=20')
    row = dict(id=15933847, status='published', user_id=uid if user_id is None else user_id,
               draw=245, topic=topic or ('245 澳门风云' if uid == 180502 else '244 杀肖只能参考'),
               content=content, user=dict(id=uid, nickname=name))
    doc = SourceDocument(json.dumps([row], ensure_ascii=False), site.api_url,
                         DocumentType.JSON, 0, f'user:{uid}:record:15933847', 0, '15933847')
    return site, SourceBundle((doc,), (), scan_complete=True)


@pytest.mark.parametrize('name,content,zodiac', [
    ('寒武忌', '<div>244期✦杀鸡✦T〃鸡46❎</div><div>245期✦杀鼠✦T〃？00</div>', '鼠'),
    ('连中谎言', '<div>244杀羊开</div><div>245杀狗开</div>', '狗'),
])
def test_245_real_record_formats_and_boundaries(name, content, zodiac):
    site, bundle = forum(name, content)
    parser = UserForumPostParser()
    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 245)
    assert decision.ok, decision
    assert decision.candidate.zodiac == zodiac
    assert not validate_candidates(site, bundle, candidates, 244).ok
    assert not validate_candidates(site, bundle, candidates, 246).ok
    if name == '连中谎言':
        assert parser.select_source(site, bundle, 245).documents[0].record_id == '15933847'


@pytest.mark.parametrize('name,line', [('寒武忌', '245期✦杀鼠✦'), ('连中谎言', '245杀狗开')])
@pytest.mark.parametrize('fault', ['author', 'column', 'conflict', 'wrong_field', 'bottom'])
def test_forum_245_rejects_wrong_identity_field_conflict_and_direction(name, line, fault):
    content = line
    options = {}
    if fault == 'author':
        options['user_id'] = 99
    elif fault == 'column':
        options['topic'] = '245 推荐一肖'
    elif fault == 'conflict':
        content += '<div>' + line.replace('鼠', '牛').replace('狗', '牛') + '</div>'
    elif fault == 'wrong_field':
        content = line.replace('杀', '推荐')
    elif fault == 'bottom':
        content += '<div>' + line.replace('245', '246') + '</div>'
    site, bundle = forum(name, content, **options)
    assert not validate_candidates(site, bundle, UserForumPostParser().parse(site, bundle), 245).ok


def article(text, noise=''):
    site = SiteConfig('宗政云裳', 'https://example.test/topic/682743.html', Direction.TOP,
                      SiteSection.NEW, 'family.strict_article', 'http_documents')
    docs = [SourceDocument(text, site.url, DocumentType.SCRIPT, 0, 'article', 0, '682743')]
    if noise:
        docs.append(SourceDocument(noise, site.url, DocumentType.SCRIPT, 0, 'recommendations', 1))
    return site, SourceBundle(tuple(docs), (), scan_complete=True)


TITLE = '杀肖区245期: 宗政云裳「铁杀一肖」免费公开'
BODY = TITLE + '\n宗政云裳 发表于 04月30日 21:03:18\n245期铁杀一肖【马马马】开？00准\n244期铁杀一肖【虎虎虎】开鸡46准'


def test_zongzheng_real_article_excludes_recommendations():
    site, bundle = article(BODY, TITLE + '\n245期 公羊\n245期铁杀一肖【羊羊羊】开00')
    candidates = build_registry().parse(site, bundle)
    assert {(c.period, c.zodiac) for c in candidates} == {(245, '马'), (244, '虎')}
    decision = validate_candidates(site, bundle, candidates, 245)
    assert decision.ok and decision.candidate.zodiac == '马'
    assert not validate_candidates(site, bundle, candidates, 244).ok
    assert not validate_candidates(site, bundle, candidates, 246).ok


@pytest.mark.parametrize('text', [
    BODY.replace('宗政云裳 发表于', '其他作者 发表于'),
    BODY.replace('铁杀一肖', '精选一肖'),
    BODY + '\n245期铁杀一肖【羊羊羊】开00',
    TITLE + '\n245期铁杀一肖【马马马】开00',
])
def test_zongzheng_rejects_bad_anchor_field_or_real_conflict(text):
    site, bundle = article(text)
    assert not validate_candidates(site, bundle, build_registry().parse(site, bundle), 245).ok


@pytest.mark.parametrize('body,period,expected', [
    ('245期：絕殺一肖(虎）開00准\n244期：絕殺一肖(狗）開46准', 245, True),
    ('244期：絕殺一肖(狗）開00准', 245, False),
    ('245期：絕殺一尾(虎）開00准', 245, False),
    ('245期：絕殺一肖(虎）開00准\n245期：絕殺一肖(羊）開00准', 245, False),
    ('246期：絕殺一肖(牛）開00准\n245期：絕殺一肖(虎）開00准', 245, False),
])
def test_macau_jinshouzhi_versions_keep_exact_field_and_top(body, period, expected):
    site = SiteConfig('澳门金手指', 'https://example.test/', Direction.TOP,
                      SiteSection.EXISTING, 'special.macau_jinshouzhi', 'http_consensus')
    text = '澳门金手指\n『综合绝杀区』\n' + body
    doc = SourceDocument(text, site.url, DocumentType.SCRIPT, 0, 'article', 0)
    bundle = SourceBundle((doc,), (), scan_complete=True)
    assert validate_candidates(site, bundle, build_registry().parse(site, bundle), period).ok is expected
