from __future__ import annotations

import json

import pytest

from zodiac_v2.config import _source_group_key, load_sites
from zodiac_v2.source.documents import same_source_identity


@pytest.mark.parametrize(('first', 'second'), [
    ('https://example.test/topic/12.html?noise=a', 'https://example.test:443/topic/12.html?noise=b'),
    ('https://example.test/list/', 'https://example.test/list'),
    ('https://example.test/#/users/7', 'https://example.test/api/v1/users/7/forums'),
    ('https://example.test/topic/12.html', 'https://example.test/topic/13.html'),
    ('https://example.test/list.aspx?id=1', 'https://example.test/list.aspx?id=2'),
])
def test_source_index_agrees_with_source_identity(first, second):
    assert (_source_group_key(first) == _source_group_key(second)) == same_source_identity(first, second)


def test_distinct_sources_do_not_run_quadratic_business_comparisons(tmp_path, monkeypatch):
    import zodiac_v2.config as config

    calls = []
    original = config.same_business_source

    def counted(first, second):
        calls.append((first.name, second.name))
        return original(first, second)

    monkeypatch.setattr(config, 'same_business_source', counted)
    rows = [dict(name=f'site-{index}', url=f'https://example.test/topic/{index + 1}.html',
                 pick='top', section='已有站点', parser_id='test', source_policy='http_documents')
            for index in range(500)]
    path = tmp_path / 'sites.json'
    path.write_text(json.dumps(rows), encoding='utf-8')
    assert len(load_sites(path, parser_ids={'test'}, source_policies={'http_documents'})) == 500
    assert not calls
