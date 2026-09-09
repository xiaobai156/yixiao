from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {text.count(old)}")
    return text.replace(old, new, 1)


# 1. Resolve same-document repeated target periods by configured TOP/BOTTOM position.
path = Path("src/zodiac_v2/validation/conflicts.py")
text = path.read_text(encoding="utf-8")
start = text.index("    for window in windows.values():\n        conflict = _window_conflict(window, target_period)")
end = text.index("\n\ndef validate_period_presence", start)
new_tail = '''    selected_by_document: dict[str, Candidate] = {}
    for document_id, window in windows.items():
        matched = tuple(candidate for candidate in window if candidate.period == target_period)
        if site.direction is Direction.LEFT:
            conflict = _window_conflict(matched, target_period)
            if conflict is not None:
                return conflict
            selected = matched[0]
        else:
            selected = matched[-1] if site.direction is Direction.BOTTOM else matched[0]
        selected_by_document[document_id] = selected

    zodiacs: list[str] = []
    for candidate in selected_by_document.values():
        if candidate.zodiac not in zodiacs:
            zodiacs.append(candidate.zodiac)
    if len(zodiacs) > 1:
        return ValidationDecision.failure(
            FailureCode.CONFLICT,
            f"来源冲突：按 {site.direction.value} 位置解析后，指定 {target_period}期不同来源仍存在多个值："
            f"{'/'.join(zodiacs)}",
        )

    documents = {document.source_id: document for document in bundle.documents}
    selected_document_id = min(
        selected_by_document,
        key=lambda document_id: (
            documents[document_id].priority,
            documents[document_id].page_order,
        ),
    )
    return ValidationDecision.success(selected_by_document[selected_document_id])
'''
text = text[:start] + new_tail + text[end:]
presence_start = text.index("def validate_period_presence")
new_presence = '''def validate_period_presence(site, bundle, candidates, target_period):
    """Check target-period presence while honoring configured positional semantics."""
    if not bundle.scan_complete:
        return ValidationDecision.failure(FailureCode.BOUNDARY, "来源扫描未完成")
    grouped = {}
    for candidate in candidates:
        grouped.setdefault(candidate.document_id, []).append(candidate)
    selected_by_document = {}
    for document_id, group in grouped.items():
        matched = tuple(
            candidate
            for candidate in _active_candidates(tuple(group), site.direction)
            if candidate.period == target_period
            and "record-status:incomplete" not in candidate.evidence
        )
        if not matched:
            continue
        if site.direction is Direction.LEFT:
            conflict = _window_conflict(matched, target_period)
            if conflict is not None:
                return conflict
            selected = matched[0]
        else:
            selected = matched[-1] if site.direction is Direction.BOTTOM else matched[0]
        selected_by_document[document_id] = selected
    if not selected_by_document:
        return ValidationDecision.failure(FailureCode.PERIOD, f"候选中未找到指定 {target_period}期")
    lines_cache = {}
    for candidate in selected_by_document.values():
        decision = validate_candidate_evidence(candidate, bundle, _lines_cache=lines_cache)
        if not decision.ok:
            return decision
    zodiacs = tuple(dict.fromkeys(candidate.zodiac for candidate in selected_by_document.values()))
    if len(zodiacs) > 1:
        return ValidationDecision.failure(
            FailureCode.CONFLICT,
            f"来源冲突：按 {site.direction.value} 位置解析后，指定 {target_period}期不同来源仍存在多个值：{'/'.join(zodiacs)}",
        )
    documents = {document.source_id: document for document in bundle.documents}
    selected_document_id = min(
        selected_by_document,
        key=lambda document_id: (
            documents[document_id].priority,
            documents[document_id].page_order,
        ),
    )
    return ValidationDecision.success(selected_by_document[selected_document_id])
'''
text = text[:presence_start] + new_presence
path.write_text(text, encoding="utf-8")


# 2. Generalize exact user-post selection: when multiple target-period posts exist,
# TOP picks the first and BOTTOM picks the last before validation.
path = Path("src/zodiac_v2/parsers/dedicated.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        if site.name not in {"福禄寿喜财", "连中谎言"}:\n            return None\n',
    '        if site.direction is Direction.LEFT:\n            return None\n',
    "user selector allowlist",
)
text = replace_once(
    text,
    '''        if len(record_ids) > 1:
            zodiacs = {candidate.zodiac for candidate in target_candidates}
            if len(zodiacs) != 1 or site.direction is Direction.LEFT:
                return None
            selected_candidate = (
                target_candidates[0]
                if site.direction is Direction.TOP
                else target_candidates[-1]
            )
            record_ids = {selected_candidate.record_id}
''',
    '''        if len(record_ids) > 1:
            selected_candidate = (
                target_candidates[0]
                if site.direction is Direction.TOP
                else target_candidates[-1]
            )
            record_ids = {selected_candidate.record_id}
''',
    "multi-post positional selection",
)
text = replace_once(
    text,
    '            record_ids_by_period: dict[int, set[str]] = {}\n            values_by_period: dict[int, set[str]] = {}\n',
    '',
    "ambiguous maps",
)
text = replace_once(
    text,
    '''                record_ids_by_period.setdefault(semantic_period, set()).add(record_id_text)
                values_by_period.setdefault(semantic_period, set()).update(
                    match.group(2)
                    for _line_index, _line, match in selected_matches
                    if int(match.group(1)) == semantic_period
                )
''',
    '',
    "ambiguous tracking",
)
text = replace_once(
    text,
    '''            ambiguous_periods = {
                period
                for period, record_ids in record_ids_by_period.items()
                if len(record_ids) > 1 and len(values_by_period.get(period, ())) != 1
            }
            candidates.extend(
                candidate
                for candidate in document_candidates
                if candidate.period not in ambiguous_periods
            )
''',
    '            candidates.extend(document_candidates)\n',
    "ambiguous filtering",
)
path.write_text(text, encoding="utf-8")


# 3. Derive the exact same-user API for browser_user sites and fetch it over
# verified HTTPS. This is more deterministic than waiting for a browser XHR.
path = Path("src/zodiac_v2/source/api.py")
text = path.read_text(encoding="utf-8")
marker = "\n\ndef bind_user_forum_target(\n"
if marker not in text or "def fetch_user_forum_api(" in text:
    raise RuntimeError("user API insertion point invalid")
addition = '''

def derived_user_forum_api_url(page_url: str, *, per_page: int = 100) -> str | None:
    if isinstance(per_page, bool) or not isinstance(per_page, int) or not 1 <= per_page <= 100:
        raise ValueError("per_page 必须是 1 到 100 的整数")
    identity = source_identity(page_url)
    if identity.user_id is None:
        return None
    parsed = urlsplit(page_url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{identity.user_id}/forums?per_page={per_page}"
    validate_related_url(page_url, api_url, require_matching_id=True)
    return api_url


def fetch_user_forum_api(
    transport: HttpTransport,
    *,
    page_url: str,
    timeout: float = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
    per_page: int = 100,
) -> SourceBundle:
    api_url = derived_user_forum_api_url(page_url, per_page=per_page)
    if api_url is None:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "用户主页 URL 缺少用户 ID", url=page_url)
    try:
        document = fetch_http_document(
            transport,
            api_url,
            timeout=timeout,
            max_bytes=max_bytes,
            document_type=DocumentType.JSON,
            source_id=f"user-api:{source_identity(page_url).user_id}",
        )
        validate_related_url(page_url, document.final_url, require_matching_id=True)
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=api_url) from exc
    return SourceBundle(
        (document,),
        (f"user-api:200:per_page={per_page}", "scan_complete:1"),
        scan_complete=True,
    )
'''
text = text.replace(marker, addition + marker, 1)
path.write_text(text, encoding="utf-8")


path = Path("src/zodiac_v2/services/scrape.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from zodiac_v2.source.api import bind_user_forum_target, derived_article_api_urls, fetch_api_then_page\n",
    "from zodiac_v2.source.api import (\n    bind_user_forum_target,\n    derived_article_api_urls,\n    fetch_api_then_page,\n    fetch_user_forum_api,\n)\n",
    "source api imports",
)
text = replace_once(
    text,
    "    def browser(self, site: SiteConfig, timeout: float) -> SourceBundle: ...\n\n    def article_api(self, site: SiteConfig, timeout: float) -> tuple[SourceBundle, ...]: ...\n",
    "    def browser(self, site: SiteConfig, timeout: float) -> SourceBundle: ...\n\n    def browser_user(self, site: SiteConfig, timeout: float) -> SourceBundle: ...\n\n    def article_api(self, site: SiteConfig, timeout: float) -> tuple[SourceBundle, ...]: ...\n",
    "gateway protocol",
)
browser_method = '''    def browser(self, site: SiteConfig, timeout: float) -> SourceBundle:
        allowed = (site.api_url,) if site.api_url else ()
        return browser_documents(
            self.renderer,
            site.url,
            timeout=timeout,
            max_chars=site.embedded_max_bytes or DEFAULT_MAX_BYTES,
            allowed_response_urls=allowed,
        )
'''
if browser_method not in text:
    raise RuntimeError("browser method insertion point invalid")
text = text.replace(
    browser_method,
    browser_method
    + '''
    def browser_user(self, site: SiteConfig, timeout: float) -> SourceBundle:
        return fetch_user_forum_api(
            self.transport,
            page_url=site.url,
            timeout=timeout,
            max_bytes=site.embedded_max_bytes or EMBEDDED_MAX_BYTES,
            per_page=100,
        )
''',
    1,
)
text = replace_once(
    text,
    '        if site.source_policy == "browser_user":\n            return self.gateway.browser(site, timeout)\n',
    '        if site.source_policy == "browser_user":\n            direct_user_api = getattr(self.gateway, "browser_user", None)\n            if callable(direct_user_api):\n                return direct_user_api(site, timeout)\n            return self.gateway.browser(site, timeout)\n',
    "browser user route",
)
path.write_text(text, encoding="utf-8")


# 4. Regression expectations for the authorized position rule.
path = Path("tests/test_conflict_scope.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "def test_target_period_conflict_outside_old_window_is_not_hidden() -> None:\n",
    "def test_top_position_selects_first_target_value_when_same_document_repeats_period() -> None:\n",
    "conflict test name",
)
text = replace_once(
    text,
    '    assert decision.failure_code is FailureCode.CONFLICT\n    assert "猴/狗" in decision.reason\n',
    '    assert decision.ok\n    assert decision.candidate is not None\n    assert decision.candidate.zodiac == "猴"\n',
    "conflict test expectation",
)
text += '''

def test_bottom_position_selects_last_target_value_when_same_document_repeats_period() -> None:
    rows = ((224, "猴"), (223, "马"), (222, "虎"), (221, "兔"), (220, "龙"), (224, "狗"))
    candidates = tuple(
        Candidate(
            period,
            zodiac,
            f"{period}期：{zodiac}",
            "script:test",
            position,
            ("section:杀肖", "block:0", "block-range:0-7"),
        )
        for position, (period, zodiac) in enumerate(rows, start=1)
    )
    site = SiteConfig(
        "测试站",
        "https://example.test/topic/1.html",
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "test",
        "http_documents",
    )
    decision = validate_candidates(site, _bundle(*(candidate.raw_line for candidate in candidates)), candidates, 224)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "狗"


def test_left_mode_still_rejects_ambiguous_same_period_values() -> None:
    candidates = (_candidate(224, "猴", 1), _candidate(224, "狗", 2))
    site = SiteConfig(
        "测试站",
        "https://example.test/topic/1.html",
        Direction.LEFT,
        SiteSection.EXISTING,
        "test",
        "http_documents",
    )
    decision = validate_candidates(site, _bundle(*(candidate.raw_line for candidate in candidates)), candidates, 224)
    assert decision.failure_code is FailureCode.CONFLICT
'''
path.write_text(text, encoding="utf-8")


path = Path("tests/test_user_forum_special.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "def test_fulu_does_not_select_between_different_same_period_values() -> None:\n",
    "def test_fulu_bottom_selects_last_post_when_same_period_values_differ() -> None:\n",
    "fulu test name",
)
text = replace_once(
    text,
    '''    assert parser.select_source(
        _site("福禄寿喜财", 154933),
        _bundle(154933, first, second),
        238,
    ) is None
''',
    '''    selected = parser.select_source(
        _site("福禄寿喜财", 154933),
        _bundle(154933, first, second),
        238,
    )
    assert selected is not None
    assert selected.documents[0].record_id == "15886257"
''',
    "fulu test expectation",
)
text += '''

def test_zhonggea_top_selects_first_same_period_post_when_values_differ() -> None:
    first = _row(
        record_id=15975717,
        user_id=179590,
        name="钟哥啊",
        draw=252,
        topic="稳杀一肖",
        content="251期杀：兔✔️<div>252期杀：鼠（以这个为准）</div>",
    )
    second = _row(
        record_id=15972916,
        user_id=179590,
        name="钟哥啊",
        draw=252,
        topic="稳杀一肖",
        content="251期杀：兔✔️<div>252期杀：牛</div>",
    )
    site = _site("钟哥啊", 179590, direction=Direction.TOP)
    parser = UserForumPostParser()
    selected = parser.select_source(site, _bundle(179590, first, second), 252)
    assert selected is not None
    assert selected.documents[0].record_id == "15975717"
    decision = validate_candidates(site, selected, parser.parse(site, selected), 252)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "鼠"
'''
path.write_text(text, encoding="utf-8")


Path("tests/test_browser_user_direct_api.py").write_text(
    '''from __future__ import annotations

import json

from zodiac_v2.contracts import Direction, SiteConfig, SiteSection
from zodiac_v2.services.scrape import DefaultSourceGateway
from zodiac_v2.source.api import derived_user_forum_api_url
from zodiac_v2.source.http import HttpResponse


class Transport:
    def __init__(self):
        self.urls = []

    def request(self, url, *, timeout, max_bytes):
        self.urls.append(url)
        body = json.dumps(
            [{
                "id": 1,
                "status": "published",
                "user_id": 28097,
                "draw": 252,
                "topic": "绝杀一肖",
                "content": "252期（绝杀一肖) 虎虎虎",
                "user": {"id": 28097, "nickname": "清爽凯蒂"},
            }],
            ensure_ascii=False,
        ).encode()
        return HttpResponse(200, url, body, (("Content-Type", "application/json; charset=utf-8"),))


def test_fragment_user_home_derives_same_user_api():
    page = "https://example.test:12277/#/users/28097"
    assert derived_user_forum_api_url(page) == (
        "https://example.test:12277/api/v1/users/28097/forums?per_page=100"
    )


def test_browser_user_gateway_prefers_verified_same_user_http_api():
    transport = Transport()
    site = SiteConfig(
        "清爽凯蒂",
        "https://example.test:12277/#/users/28097",
        Direction.TOP,
        SiteSection.EXISTING,
        "special.user_forum_post",
        "browser_user",
    )
    bundle = DefaultSourceGateway(transport=transport).browser_user(site, 10)
    assert transport.urls == ["https://example.test:12277/api/v1/users/28097/forums?per_page=100"]
    assert bundle.scan_complete
    assert "252" in bundle.documents[0].text
''',
    encoding="utf-8",
)
