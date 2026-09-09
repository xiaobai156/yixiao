from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# 1. Only the two confirmed multi-year regex pages get annual-cycle tagging.
# The validator remains strict: conflicts inside the selected cycle still fail.
path = Path("src/zodiac_v2/parsers/dedicated.py")
text = path.read_text(encoding="utf-8")
needle = "DIRECTIONAL_CYCLE_REGEX_SITES = frozenset(\n    {\n"
if needle not in text:
    raise RuntimeError("directional cycle set not found")
text = text.replace(
    needle,
    needle + "        '不幸蒂芥', '息息相关',\n",
    1,
)

# 2. For user forums, choose the target-period POST by configured TOP/BOTTOM.
# Parse each row independently so a conflict inside one chosen post is still
# preserved and rejected later by validate_candidates.
class_start = text.index("class UserForumPostParser:")
select_start = text.index("    def select_source(\n", class_start)
parse_start = text.index("\n    def parse(", select_start)
new_selector = '''    def select_source(
        self,
        site: SiteConfig,
        bundle: SourceBundle,
        target_period: int,
    ) -> SourceBundle | None:
        if site.direction is Direction.LEFT:
            return None
        expected_user_match = re.search(
            r"/users/(\\d+)(?:/|$)",
            urlsplit(site.url).path + "/" + urlsplit(site.url).fragment,
        )
        if expected_user_match is None:
            return None
        expected_user_id = int(expected_user_match.group(1))

        matching_rows: list[tuple[dict[str, object], object]] = []
        seen_rows: dict[str, str] = {}
        for document in bundle.documents:
            if document.document_type is not DocumentType.JSON:
                continue
            response_match = re.search(
                r"/api/v1/users/(\\d+)/forums(?:[/?]|$)",
                urlsplit(document.final_url).path,
            )
            if response_match is None or int(response_match.group(1)) != expected_user_id:
                continue
            try:
                rows = json.loads(document.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                record_id = row.get("id")
                if (
                    isinstance(record_id, bool)
                    or not isinstance(record_id, (str, int))
                    or not str(record_id).strip()
                ):
                    continue
                record_id_text = str(record_id).strip()
                row_json = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                previous = seen_rows.get(record_id_text)
                if previous is not None:
                    if previous != row_json:
                        return None
                    continue
                seen_rows[record_id_text] = row_json

                selected_user = row.get("user")
                if not isinstance(selected_user, dict) or not isinstance(selected_user.get("nickname"), str):
                    continue
                projected_row = dict(row)
                projected_row["authorNickname"] = selected_user["nickname"]
                row_document = type(document)(
                    json.dumps([projected_row], ensure_ascii=False, separators=(",", ":")),
                    document.final_url,
                    DocumentType.JSON,
                    document.priority,
                    f"user:{expected_user_id}:record:{record_id_text}",
                    0,
                    record_id_text,
                )
                row_bundle = SourceBundle((row_document,), bundle.diagnostics, scan_complete=True)
                if any(candidate.period == target_period for candidate in self.parse(site, row_bundle)):
                    matching_rows.append((projected_row, document))

        if not matching_rows:
            return None
        row, source = matching_rows[0] if site.direction is Direction.TOP else matching_rows[-1]
        record_id = str(row["id"]).strip()
        selected_document = type(source)(
            json.dumps([row], ensure_ascii=False, separators=(",", ":")),
            source.final_url,
            DocumentType.JSON,
            source.priority,
            f"user:{expected_user_id}:record:{record_id}",
            0,
            record_id,
        )
        return SourceBundle(
            (selected_document,),
            (
                *bundle.diagnostics,
                f"user-forum-parser-target:{target_period}",
                f"user-forum-record:{record_id}",
                f"user-forum-position:{site.direction.value}",
            ),
            scan_complete=True,
        )
'''
text = text[:select_start] + new_selector + text[parse_start:]
path.write_text(text, encoding="utf-8")


# 3. browser_user: derive the exact same-user API and use verified HTTPS.
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


# 4. Update only the old multi-POST expectation; same-record conflicts stay unchanged.
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


# 5. Exercise actual registry cycle tagging for the two live sites.
path = Path("tests/test_regex_directional_cycles.py")
text = path.read_text(encoding="utf-8")
text += '''

def test_buxing_dijie_top_uses_first_annual_cycle_position() -> None:
    from zodiac_v2.parsers.registry import build_registry

    site = SiteConfig(
        "不幸蒂芥",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.EXISTING,
        "regex.86a7042b2c5a",
        "http_documents",
    )
    bundle = _bundle(
        "不幸蒂芥\\n"
        "252期：绝杀一肖【兔】\\n251期：绝杀一肖【虎】\\n001期：绝杀一肖【龙】\\n"
        "365期：绝杀一肖【牛】\\n253期：绝杀一肖【蛇】\\n252期：绝杀一肖【猴】"
    )
    decision = validate_candidates(site, bundle, build_registry().parse(site, bundle), 252)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "兔"


def test_xixixiangguan_bottom_uses_last_annual_cycle_position() -> None:
    from zodiac_v2.parsers.registry import build_registry

    site = SiteConfig(
        "息息相关",
        "https://example.test/topic/1.html",
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "regex.86a7042b2c5a",
        "http_documents",
    )
    bundle = _bundle(
        "息息相关\\n"
        "252期：绝杀一肖【鸡】\\n251期：绝杀一肖【虎】\\n001期：绝杀一肖【龙】\\n"
        "365期：绝杀一肖【牛】\\n253期：绝杀一肖【马】\\n252期：绝杀一肖【蛇】"
    )
    decision = validate_candidates(site, bundle, build_registry().parse(site, bundle), 252)
    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "蛇"
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
