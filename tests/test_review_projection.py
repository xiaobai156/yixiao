from __future__ import annotations

import json

import pytest

from zodiac_v2.source.documents import source_identity, SourceIdentityError
from zodiac_v2.source.projection import project_response

EXPECTED=source_identity('https://example.test/article/admin/abc')
URL='https://example.test/api/proxy/admin-articles/abc'


def test_unique_record_projected_without_other_article_or_wrapper_metadata():
    target={'id':'abc','content':'250期杀鼠'}
    body=json.dumps({'data':[target,{'id':'other','content':'250期杀牛'}],'metadata':{'content':'广告'}})
    assert json.loads(project_response(body,EXPECTED,URL))==target


@pytest.mark.parametrize('payload',[
    {'metadata':{'id':'abc'},'content':'别人的正文','id':'other'},
    {'data':[{'id':'abc','metadata':'no body'},{'id':'other','content':'别人的正文'}]},
    {'recommendations':[{'id':'abc','content':'推荐而非目标记录'}]},
    {'data':[{'id':'other','content':'别人的正文','author':{'id':'abc'}}]},
])
def test_id_in_unrelated_position_does_not_authorize_record(payload):
    assert project_response(json.dumps(payload),EXPECTED,URL) is None


def test_same_id_different_content_is_not_first_wins():
    body=json.dumps([{'id':'abc','content':'杀鼠'},{'id':'abc','content':'杀牛'}])
    with pytest.raises(SourceIdentityError,match='冲突'): project_response(body,EXPECTED,URL)


def test_identical_copies_are_deduplicated():
    row={'id':'abc','content':'杀鼠'}
    assert json.loads(project_response(json.dumps([row,row]),EXPECTED,URL))==row


def test_response_endpoint_mismatch_cannot_be_rescued_by_body():
    assert project_response('{"id":"abc","content":"杀鼠"}',EXPECTED,URL.replace('/abc','/other')) is None


def test_user_projection_preserves_only_target_users_posts():
    expected=source_identity('https://example.test/#/users/12')
    rows=[{'id':i,'user_id':u,'user':{'id':u},'content':f'{i}期杀鼠'} for i,u in [(250,12),(249,12),(248,13)]]
    result=json.loads(project_response(json.dumps({'data':rows}),expected,'https://example.test/api/v1/users/12/forums'))
    assert result==rows[:2]


def test_user_identity_must_agree_in_the_same_record():
    expected=source_identity('https://example.test/#/users/12')
    rows=[{'id':250,'user_id':12,'user':{'id':13},'content':'250期杀鼠'}]
    assert project_response(json.dumps(rows),expected,'https://example.test/api/v1/users/12/forums') is None


@pytest.mark.parametrize('value',['not json','null','42','"text"'])
def test_invalid_json_container_is_explicit_error(value):
    with pytest.raises(SourceIdentityError): project_response(value,EXPECTED,URL)
