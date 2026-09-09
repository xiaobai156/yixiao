"""One-shot reviewed patch, restricted to the recorded baseline and explicit files.

Used only on the isolated repair branch; removed after the tested source commit.
No live crawling, production cache mutation, or main-branch push is performed.
"""
from __future__ import annotations
import ast
import json
import subprocess
from pathlib import Path
import textwrap

CHANGED = []
PREIMAGES = {
 'src/zodiac_v2/cli.py': '959a0ab826ab65948d46882385c2361dc2399fd6',
 'src/zodiac_v2/output.py': 'e1b516fddd0609aa239d0cb9189e644df79a253e',
 'src/zodiac_v2/cache.py': '3f2a83bffff1300f305648c3e31859fc97090f4b',
 'src/zodiac_v2/config.py': 'b8987a93b6f7bca74e39692cf4f80bcbce6f7c63',
 'src/zodiac_v2/contracts.py': '337f27caceba520f9d73cc0d1fa4934ac971587a',
 'src/zodiac_v2/services/scrape.py': '037728f6e14770a97ea0bc6e24a10632d13607fc',
 'src/zodiac_v2/services/repair.py': 'd6be1bba9eda73a70d3483be1f137dd093f8621e',
 'src/zodiac_v2/parsers/families.py': '622ec8761573c97f92c0aa69069acef1a95a1c50',
 'src/zodiac_v2/validation/conflicts.py': '8fc0e4e486a143165db67b7a92191fc79417fe00',
 'src/zodiac_v2/validation/evidence.py': 'acc35c53c5b462d32b7e1ad0ff1c660b75a01447',
 'src/zodiac_v2/source/http.py': 'c71d5b2728191a7d774bccda833c0fc6746ab0f5',
 'src/zodiac_v2/source/browser.py': '932a3e1900e57991b5558f7924e443e599bf9b21',
 'src/zodiac_v2/source/documents.py': 'fe0c41278c8a0dec6974146eccd77ee99ec6f116',
}


def put(path, content):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8', newline='\n')
    if path not in CHANGED:
        CHANGED.append(path)


def substitute(path, old, new, count=1):
    text = Path(path).read_text(encoding='utf-8')
    if text.count(old) != count:
        raise RuntimeError(f'Unexpected patch context: {path}: {old[:80]!r}: {text.count(old)}')
    put(path, text.replace(old, new))


def replace_function(path, qualname, source):
    text = Path(path).read_text(encoding='utf-8')
    node = ast.parse(text)
    for name in qualname.split('.'):
        found = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == name]
        if len(found) != 1:
            raise RuntimeError(f'Expected exactly one {qualname} in {path}')
        node = found[0]
    lines = text.splitlines(keepends=True)
    first = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
    replacement = textwrap.indent(textwrap.dedent(source).strip() + '\n', ' ' * node.col_offset)
    put(path, ''.join(lines[:first]) + replacement + ''.join(lines[node.end_lineno:]))


for path, expected in PREIMAGES.items():
    actual = subprocess.run(['git', 'rev-parse', 'HEAD:' + path], check=True, text=True, capture_output=True).stdout.strip()
    if actual != expected:
        raise RuntimeError(f'Review baseline changed: {path}: {actual}')

out = 'src/zodiac_v2/output.py'
substitute(out, 'from zodiac_v2.contracts import FailureCode, ScrapeResult, SiteSection, WritePermit',
    'from zodiac_v2.contracts import FailureCode, ScrapeResult, SiteSection, WritePermit\nfrom zodiac_v2.storage import atomic_batch_write, locked_paths, path_key')
substitute(out, '    if any(result.ok and not result.validator_issued for result in materialized):',
    '''    if not materialized:
        raise ValueError("正式输出结果为空，拒绝覆盖")
    identities = [result.site.identity for result in materialized]
    if len(set(identities)) != len(identities):
        raise ValueError("正式输出包含重复站点，禁止同站多值")
    output_files = (paths.existing_success, paths.new_success, paths.existing_failure, paths.new_failure)
    if len({path_key(path) for path in output_files}) != 4:
        raise PermissionError("四类输出路径不能重复")
    if any(result.ok and not result.validator_issued for result in materialized):''')
substitute(out, '    counter: Counter[str] = Counter(zodiac for zodiac, _name in all_rows)\n',
    '    counter: Counter[str] = Counter(zodiac for zodiac, _name in all_rows)\n    ranks = {count: rank for rank, count in enumerate(sorted(set(counter.values()), reverse=True), 1)}\n')
substitute(out, '            "生肖次数排行榜",\n', '            "内容\\t次数\\t排名",\n')
substitute(out, 'f"{zodiac} {counter[zodiac]}次"', 'f"{zodiac}\\t{counter[zodiac]}\\t{ranks[counter[zodiac]]}"')
replace_function(out, 'write_output_payloads', '''
def write_output_payloads(payloads: _OutputPayloads, permit: WritePermit) -> None:
    if not isinstance(payloads, _OutputPayloads) or payloads._token is not _OUTPUT_TOKEN:
        raise PermissionError("输出载荷必须由统一验证器签发")
    permit.require_formal_single(payloads._target_period)
    if any(not path.name.startswith(f"{permit.target_period}期-") for path in payloads):
        raise PermissionError("输出文件期数与正式单期写入许可不一致")
    atomic_batch_write({path: text.encode("utf-8") if text is not None else None for path, text in payloads.items()})
''')
substitute(out, 'def merge_formal_single_result_output(', 'def build_merged_result_payloads(')
substitute(out, '    allow_existing_value_correction: bool = False,\n) -> None:',
    '    allow_existing_value_correction: bool = False,\n    texts: Mapping[Path, str] | None = None,\n) -> _OutputPayloads:')
substitute(out, '    existing_success_text = _read_output_text(success_path)',
    '    read_text = _read_output_text if texts is None else lambda path: texts[path]\n    existing_success_text = read_text(success_path)')
substitute(out, '    failure_rows = _failure_rows(_read_output_text(failure_path))',
    '    failure_rows = _failure_rows(read_text(failure_path))')
substitute(out, '        success_rows = [row for row in success_rows if _output_name_key(row[1]) != target_name_key]\n        trailing_success_rows = [row for row in trailing_success_rows if _output_name_key(row[1]) != target_name_key]\n', '')
substitute(out, '    write_output_payloads(payloads, permit)\n',
    '''    if not result.ok:
        # Do not even normalize an existing success file after a failed retry.
        return _OutputPayloads({failure_path: payloads[failure_path]}, target_period=result.target_period, token=_OUTPUT_TOKEN)
    return payloads


def merge_formal_single_result_output(result, paths, permit, *, allow_existing_value_correction=False) -> None:
    pair = (paths.new_success, paths.new_failure) if result.site.section is SiteSection.NEW else (paths.existing_success, paths.existing_failure)
    with locked_paths(pair):
        payloads = build_merged_result_payloads(result, paths, permit, allow_existing_value_correction=allow_existing_value_correction)
        write_output_payloads(payloads, permit)
''')
substitute(out, 'or period <= 0:', 'or not 1 <= period <= 9999:')
substitute(out, 'and parts[0] in ZODIAC_ORDER:', 'and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER:', count=2)

cache = 'src/zodiac_v2/cache.py'
substitute(cache, 'CACHE_WINDOW = 10', 'from zodiac_v2.storage import atomic_write_bytes, locked_paths\n\nCACHE_WINDOW = 10')
replace_function(cache, '_atomic_write', '''
def _atomic_write(path: Path, text: str) -> None:
    with locked_paths((path,)):
        atomic_write_bytes(path, text.encode('utf-8'))
''')
contracts = 'src/zodiac_v2/contracts.py'
substitute(contracts, '            "source_policy": site.source_policy,', '            "source_policy": site.source_policy,\n            "api_url": site.api_url,')
conflicts = 'src/zodiac_v2/validation/conflicts.py'
substitute(conflicts, '    matched = tuple(candidate for candidate in window if candidate.period == target_period)',
    '''    if not window:
        return window, ValidationDecision.failure(FailureCode.BOUNDARY, "过滤未完成记录后没有可用于方向验证的完整候选")
    matched = tuple(candidate for candidate in window if candidate.period == target_period)''')
put(conflicts, Path(conflicts).read_text(encoding='utf-8') + '''

def validate_period_presence(site, bundle, candidates, target_period):
    """Check existence/conflicts in each active source cycle, independently of its edge."""
    if not bundle.scan_complete:
        return ValidationDecision.failure(FailureCode.BOUNDARY, "来源扫描未完成")
    grouped = {}
    for candidate in candidates:
        grouped.setdefault(candidate.document_id, []).append(candidate)
    matched = tuple(
        candidate for group in grouped.values()
        for candidate in _active_candidates(tuple(group), site.direction)
        if candidate.period == target_period
    )
    if not matched:
        return ValidationDecision.failure(FailureCode.PERIOD, f"候选中未找到指定 {target_period}期")
    lines_cache = {}
    for candidate in matched:
        decision = validate_candidate_evidence(candidate, bundle, _lines_cache=lines_cache)
        if not decision.ok:
            return decision
    conflict = _window_conflict(matched, target_period)
    return conflict if conflict is not None else ValidationDecision.success(matched[0])
''')
evidence = 'src/zodiac_v2/validation/evidence.py'
substitute(evidence, '    document = documents[0]\n', '''    document = documents[0]
    if candidate.record_id is not None and document.record_id is not None and candidate.record_id != document.record_id:
        return ValidationDecision.failure(FailureCode.SOURCE_IDENTITY, "候选记录 ID 与来源文档记录 ID 不一致")
''')
substitute(evidence, '    for prefix, start, end in evidence_ranges:\n', '''    if evidence_ranges:
        block_end = min(end for _prefix, _start, end in evidence_ranges)
        bounded_source = _normalize_space(" ".join(lines[local_position:min(local_position + 8, block_end)]))
        if expected not in bounded_source:
            return ValidationDecision.failure(FailureCode.BOUNDARY, "候选原始行跨越了已证明的区块结束边界")
    for prefix, start, end in evidence_ranges:
''')
families = 'src/zodiac_v2/parsers/families.py'
replace_function(families, 'AnchoredSectionFamilyParser.parse', '''
def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
    spec = self.specs.get(site.name)
    if spec is None:
        return ()
    candidates = []
    seen = set()
    for document in bundle.documents:
        lines = document_lines(document)
        for anchor_index, anchor_line in enumerate(lines):
            if spec.anchor_pattern.search(anchor_line.text) is None:
                continue
            first = anchor_index if spec.include_anchor_line else anchor_index + 1
            end = len(lines)
            for index in range(first, len(lines)):
                if (spec.stop_pattern is not None and spec.stop_pattern.search(lines[index].text)) or (index > anchor_index and spec.anchor_pattern.search(lines[index].text)):
                    end = index
                    break
            for index in range(first, end):
                record_text = normalize_space(" ".join(item.text for item in lines[index:min(index + spec.record_window_lines, end)]))
                for match in spec.record_pattern.finditer(record_text):
                    period = int(match.group(1).lstrip("0") or "0")
                    zodiac = match.group(2)
                    key = _physical_match_key(document.source_id, index, match.start(1), period, zodiac)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(Candidate(period, zodiac, record_text, document.source_id,
                        document.page_order * 1_000_000 + index,
                        (f"section:{normalize_space(anchor_line.text)}", f"anchor:{normalize_space(anchor_line.text)}",
                         f"anchor-line:{anchor_index}", f"section-range:{anchor_index}-{end}", f"record-offset:{match.start(1)}"),
                        record_id=document.record_id))
    return tuple(sorted(candidates, key=lambda candidate: candidate.page_order))
''')
scrape = 'src/zodiac_v2/services/scrape.py'
substitute(scrape, 'from zodiac_v2.validation.conflicts import _active_candidates, validate_candidates',
    'from zodiac_v2.validation.conflicts import _active_candidates, validate_candidates, validate_period_presence')
substitute(scrape, 'from urllib.parse import urlsplit', 'from urllib.parse import parse_qs, urlsplit')
substitute(scrape, '    discover_period_keyword_links,', '    discover_period_keyword_links,\n    discover_period_page_links,')
replace_function(scrape, 'commit_formal_single', '''
def commit_formal_single(results, *, cache_path, paths, permit, expected_sites=None, existing_success_extra_names=()):
    """Compatibility name for a full batch; scope must be explicitly supplied."""
    from zodiac_v2.services.persistence import commit_full_formal_single
    if expected_sites is None:
        raise ValueError("全量正式提交必须提供 expected_sites，禁止子集覆盖")
    return commit_full_formal_single(results, expected_sites=expected_sites, cache_path=cache_path, paths=paths,
        permit=permit, existing_success_extra_names=existing_success_extra_names)
''')
replace_function(scrape, 'DefaultSourceGateway.period_keyword_article', '''
def period_keyword_article(self, site, bundle, target_period, timeout):
    if not site.article_keyword:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "缺少文章关键字", url=site.url)
    if len(bundle.documents) != 1:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "栏目分页必须从唯一入口开始", url=site.url)
    deadline = monotonic() + timeout
    document = bundle.documents[0]
    seen_pages = set()
    matches = []
    scanned = 0
    while True:
        if document.final_url in seen_pages:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "栏目分页循环", url=site.url)
        seen_pages.add(document.final_url)
        scanned += 1
        article_urls, page_urls, periods = discover_period_page_links(document.text, document.final_url, target_period, site.article_keyword)
        matches.extend(article_urls)
        # Configured newest-first lists stop after a page of strictly older articles.
        if periods and max(periods) < target_period:
            break
        current_page = int(parse_qs(urlsplit(document.final_url).query).get("page", ["1"])[0])
        following = sorted({url for url in page_urls if int(parse_qs(urlsplit(url).query)["page"][0]) == current_page + 1})
        if not following:
            if page_urls and any(int(parse_qs(urlsplit(url).query)["page"][0]) > current_page for url in page_urls):
                raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "缺少连续下一页，不能证明扫描完整", url=site.url)
            break
        if len(following) != 1 or scanned >= 10:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "同栏目分页不唯一或超过安全上限 10 页", url=site.url)
        document = fetch_http_document(self.transport, following[0],
            timeout=_remaining_budget(deadline, timeout, site.url, "栏目分页取源总超时"),
            identity_url=following[0], source_id=f"period-list:{following[0]}")
    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, f"{target_period}期完整关键字 {site.article_keyword!r} 详情链接命中 {len(unique)} 个", url=site.url)
    detail = fetch_http_document(self.transport, unique[0], timeout=_remaining_budget(deadline, timeout, site.url, "文章详情取源总超时"), identity_url=unique[0], source_id=f"ttss-article:{unique[0]}")
    return self.embedded(site, SourceBundle((detail,), (f"period-list-pages:{scanned}", "period-keyword-match:1"), scan_complete=False), _remaining_budget(deadline, timeout, site.url, "文章详情取源总超时"))
''')
replace_function(scrape, 'ScrapeService._http_consensus', '''
def _http_consensus(self, site, target_period, mode, remaining):
    hits = []
    last_failure = None
    newer_values = set()
    newer_documents = ()
    for _attempt in range(HTTP_CONSENSUS_ATTEMPTS):
        try:
            bundle = self.gateway.http(site, remaining())
            bundle = self.gateway.embedded(site, bundle, remaining())
            remaining()
        except SourceFetchError as exc:
            failure = ScrapeResult.failure(site, target_period, _failure_code(exc), str(exc), ())
            if exc.code is not SourceFetchCode.NETWORK and exc.code is not SourceFetchCode.HTTP_STATUS:
                return failure
            last_failure = failure
            continue
        result = self._evaluate(site, target_period, bundle, mode)
        if result.failure_code is FailureCode.CONFLICT:
            return result
        try:
            candidates = tuple(self.registry.parse(site, bundle))
        except Exception:
            last_failure = result
            continue
        for period in (target_period, target_period + 1):
            if period > 9999:
                continue
            presence = validate_period_presence(site, bundle, candidates, period)
            if presence.failure_code is FailureCode.CONFLICT:
                return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT,
                    f"共识取源发现 {period}期明确冲突：{presence.reason}", bundle.documents)
            if presence.failure_code not in (None, FailureCode.PERIOD):
                return ScrapeResult.failure(site, target_period, presence.failure_code, presence.reason, bundle.documents)
            if period > target_period and presence.ok:
                newer_values.add(presence.candidate.zodiac)
                newer_documents = bundle.documents
        if result.ok:
            hits.append(result)
        else:
            last_failure = result
    if len(newer_values) > 1:
        return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT, "多次取源的下一期结果冲突", newer_documents)
    if newer_values:
        return ScrapeResult.failure(site, target_period, FailureCode.DIRECTION,
            f"多次取源发现更新的 {target_period + 1}期有效结果，指定期不是方向边界", newer_documents)
    values = {result.candidate.zodiac for result in hits}
    if len(values) > 1:
        return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT, f"目标期多次取源结果冲突：{sorted(values)}", hits[0].documents)
    if len(hits) >= HTTP_CONSENSUS_CONFIRMATIONS:
        return hits[0]
    if hits:
        return ScrapeResult.failure(site, target_period, FailureCode.SOURCE_IDENTITY, "多次取源有效确认不足", hits[0].documents)
    return last_failure or ScrapeResult.failure(site, target_period, FailureCode.SOURCE_IDENTITY, "多次取源未取得有效文档", ())
''')
substitute(scrape, '                browser_bundle = self.gateway.browser(site, remaining())\n                documents = browser_bundle.documents',
    '''                if not article_documents:
                    page_bundle = self.gateway.http(site, remaining())
                    page_bundle = self.gateway.embedded(site, page_bundle, remaining())
                    documents = page_bundle.documents
                    if not _bundle_is_empty_shell(page_bundle):
                        return self._evaluate(site, target_period, page_bundle, mode)
                browser_bundle = self.gateway.browser(site, remaining())
                documents = browser_bundle.documents''')
substitute(scrape, '        try:\n            candidates = tuple(self.registry.parse(site, bundle))',
    '''        try:
            if sum(len(document.text.encode("utf-8")) for document in bundle.documents) > 64_000_000:
                return ScrapeResult.failure(site, target_period, FailureCode.BOUNDARY, "站点文档累计超过 64000000 字节", bundle.documents)
            candidates = tuple(self.registry.parse(site, bundle))''')
documents = 'src/zodiac_v2/source/documents.py'
substitute(documents, '        self.has_target_period_article = False', '        self.has_target_period_article = False\n        self.observed_periods: list[int] = []')
substitute(documents, '            if self.period_prefix.search(text) and valid_article:\n',
    '''            observed = re.match(r"^\\s*第?\\s*(\\d{1,4})\\s*期", text)
            if valid_article and observed:
                self.observed_periods.append(int(observed.group(1)))
            if self.period_prefix.search(text) and valid_article:
''')
put(documents, Path(documents).read_text(encoding='utf-8') + '''

def discover_period_page_links(html, base_url, period, keyword):
    source_identity(base_url)
    if not keyword.strip():
        raise ValueError("文章关键字不能为空")
    parser = _PeriodKeywordLinkParser(base_url, period, keyword)
    parser.feed(html)
    parser.close()
    return tuple(parser.article_urls), tuple(dict.fromkeys(parser.page_urls)), tuple(parser.observed_periods)
''')
substitute(documents, '        return any(left is not None and left == right for left, right in identifiers)',
    '        return all(left == right for left, right in identifiers if left is not None or right is not None)')
substitute(documents, '            depth_truncated = depth_truncated or bool(nested_resources)',
    '            depth_truncated = depth_truncated or any(nested.url not in seen for nested in nested_resources)')
substitute(documents, '    depth_truncated = False\n', '    depth_truncated = False\n    total_bytes = len(parent.text.encode("utf-8"))\n')
substitute(documents, '        validate_final_url(resource.url, fetched.final_url)\n',
    '''        validate_final_url(resource.url, fetched.final_url)
        total_bytes += len(fetched.text.encode("utf-8"))
        if total_bytes > 64_000_000:
            raise ValueError("站点内容文档累计超过 64000000 字节")
''')
http = 'src/zodiac_v2/source/http.py'
substitute(http, 'DEFAULT_INSECURE_TLS_HOSTS = frozenset({"nlafoq9v.dh5565656.xyz", "156.225.88.144"})',
    'DEFAULT_INSECURE_TLS_HOSTS: frozenset[str] = frozenset()')
replace_function(http, 'RequestsTransport.request', '''
def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
    try:
        result = self._request(url, timeout=timeout, max_bytes=max_bytes, verify=True)
    except requests.RequestException as exc:
        raise SourceFetchError(SourceFetchCode.NETWORK, f"HTTP 请求失败（未关闭证书验证）：{exc}", url=url) from exc
    if len(result.body) > max_bytes:
        raise SourceFetchError(SourceFetchCode.TOO_LARGE, f"HTTP 响应超过 {max_bytes} 字节", url=url)
    return result
''')
substitute(http, '        with requests.Session() as session:\n',
    '        if not verify:\n            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "禁止关闭 TLS 证书验证", url=url)\n        with requests.Session() as session:\n')
config = 'src/zodiac_v2/config.py'
substitute(config, 'from zodiac_v2.source.documents import same_source_identity',
    'from zodiac_v2.source.documents import same_source_identity\nfrom zodiac_v2.storage import locked_paths')
substitute(config, '    return tuple(sites)\n', '''    for index, site in enumerate(sites):
        for previous in sites[:index]:
            if same_business_source(site, previous):
                raise ConfigError(f"不同站名重复绑定同一来源和栏目：{site.name} / {previous.name}")
    return tuple(sites)
''')
substitute(config, '    with _CONFIG_WRITE_LOCK:\n', '    with _CONFIG_WRITE_LOCK, locked_paths((path,)):\n')
put(config, Path(config).read_text(encoding='utf-8') + '''

def same_business_source(first: SiteConfig, second: SiteConfig) -> bool:
    if not same_source_identity(first.url, second.url):
        return False
    if (first.source_policy == second.source_policy == "http_period_keyword_article"
        and first.article_keyword and second.article_keyword and first.article_keyword != second.article_keyword):
        return False
    names = {"关公杀一肖", "佛主禁肖图", "三怪禁肖图"}
    if first.parser_id == second.parser_id == "special.sanguai_period_section" and first.name in names and second.name in names and first.name != second.name:
        return False
    return True
''')
cli = 'src/zodiac_v2/cli.py'
substitute(cli, 'import argparse\n', 'import argparse\nimport math\n')
substitute(cli, 'from zodiac_v2.services.onboarding import validate_new_site',
    'from zodiac_v2.services.onboarding import validate_new_site\nfrom zodiac_v2.services.persistence import commit_targeted_formal_single')
substitute(cli, 'type=float, default=DEFAULT_SITE_TIMEOUT', 'type=_positive_timeout, default=DEFAULT_SITE_TIMEOUT')
substitute(cli, 'type=int, default=8', 'type=_positive_workers, default=8')
substitute(cli, '                permit=WritePermit.formal_single(args.period),\n',
    '                permit=WritePermit.formal_single(args.period),\n                expected_sites=sites,\n', count=2)
old = '''        reports = repair_sites(scraper, selected, args.period)
        results = tuple(report.result for report in reports)
        if args.command == "retry" and args.formal:
            results = commit_formal_single(
                results,
                cache_path=args.cache_file,
                paths=output_paths(args.period, args.success_dir, args.failure_dir),
                permit=WritePermit.formal_single(args.period),
                expected_sites=sites,
            )
        else:
            print("限定复抓为只读验证，未写缓存或正式 TXT")'''
new = '''        if not selected:
            print("失败清单没有匹配到任何站点，未抓取、未写入")
            return 2
        formal = args.command == "retry" and args.formal
        results = scraper.scrape_sites(selected, args.period,
            RunMode.FORMAL_SINGLE if formal else RunMode.READ_ONLY,
            timeout=args.timeout, workers=args.workers)
        if formal:
            results = commit_targeted_formal_single(results, expected_sites=selected,
                cache_path=args.cache_file, paths=output_paths(args.period, args.success_dir, args.failure_dir),
                permit=WritePermit.formal_single(args.period))
        else:
            print("限定复抓为只读验证，未写缓存或正式 TXT")'''
substitute(cli, old, new)
substitute(cli, '        periods = tuple(range(args.period, args.period - 10, -1))',
    '        periods = tuple(range(args.period, max(0, args.period - 10), -1))')
substitute(cli, 'def _common(parser: argparse.ArgumentParser) -> None:', '''def _positive_workers(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("workers 必须为正整数")
    return result


def _positive_timeout(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("timeout 必须为有限正数")
    return result


def _common(parser: argparse.ArgumentParser) -> None:''')
repair = 'src/zodiac_v2/services/repair.py'
substitute(repair, 'from zodiac_v2.contracts import RunMode, ScrapeResult, SiteConfig',
    'from zodiac_v2.contracts import RunMode, ScrapeResult, SiteConfig\nfrom zodiac_v2.source.documents import same_source_identity')
replace_function(repair, 'sites_from_failure_text', '''
def sites_from_failure_text(text: str, sites: Iterable[SiteConfig]) -> tuple[SiteConfig, ...]:
    known = {site.name: site for site in sites}
    selected = []
    for line in text.splitlines():
        if URL_PATTERN.search(line) is None:
            continue
        match = re.match(r"^(?P<name>.+?)\\s+(?P<pick>top|bottom)\\s+(?P<url>https?://\\S+)", line.strip())
        if match is None:
            raise ValueError(f"失败清单行缺少明确站名/方向：{line}")
        name = re.sub(r"[\\u200b-\\u200d\\ufeff]", "", match['name']).strip()
        site = known.get(name)
        if site is None or site.direction.value != match['pick'] or not same_source_identity(site.url, match['url']):
            raise ValueError(f"失败清单身份与当前配置不一致，拒绝扩大复抓范围：{name}")
        if site not in selected:
            selected.append(site)
    return tuple(selected)
''')

# Install the separately reviewed replacement modules, not generated runtime monkeypatches.
for name, target in {
    'storage.py': 'src/zodiac_v2/storage.py',
    'persistence.py': 'src/zodiac_v2/services/persistence.py',
    'identity_records.py': 'src/zodiac_v2/source/identity_records.py',
    'browser.py': 'src/zodiac_v2/source/browser.py',
    'test_review_regressions.py': 'tests/test_review_regressions.py',
}.items():
    put(target, (Path('tools/_review_sources') / name).read_text(encoding='utf-8'))

substitute('pyproject.toml', 'dependencies = ["requests>=2.31", "playwright>=1.61,<2"]',
    'dependencies = ["requests>=2.31", "playwright>=1.61,<2", "filelock>=3.15,<4"]')
put('pyproject.toml', Path('pyproject.toml').read_text(encoding='utf-8') + '''

[project.optional-dependencies]
dev = ["pytest>=8,<10", "ruff>=0.6,<1"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["historical_snapshot: requires matching historical production cache/config/TXT; opt in explicitly"]
''')
ignore = Path('.gitignore').read_text(encoding='utf-8') if Path('.gitignore').exists() else ''
put('.gitignore', ignore + '''
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
.venv/
*.egg-info/
*.tmp
.*.lock
recent_10_cache.json.lock
.zodiac-txn-*.json
.*.bak
.diagnostics/
.review-changed-files.json
''')
# Keep all existing project requirements, and explicitly document the authorized new entry point.
put('AGENTS.md', Path('AGENTS.md').read_text(encoding='utf-8') + '''

## 2026-09-09 正式复抓入口修订

本节细化此前“retry只读”的描述：未加 `--formal` 的 retry 与 repair 仍完全只读；用户显式 `retry --formal` 只授权失败清单唯一匹配的站点/指定期，使用 `commit_targeted_formal_single` 定点合并，禁止调用全量输出接口。定点失败保留已有成功行与缓存，只更新失败诊断；定点成功不套用全批次85%门禁。`single --formal` 仍遵守完整目标集合与严格大于85%的批次缓存门禁。所有成功必须由统一验证器正式签发，禁止把只读对象改为可写。

多进程正式写入必须从读取旧文件到最终写入持有 `storage.locked_paths`；发现未完成TXT事务应拒绝继续覆盖并显式恢复。配置、缓存和正式TXT不得作为自动化测试临时数据。历史238/240/241期生产快照测试保留原断言，单独以 `--historical-snapshots` 启用，不为使历史断言通过而回滚当前数据。
''')

# Syntax-check the exact resulting files before the workflow installs/runs tests.
for path in CHANGED:
    if path.endswith('.py'):
        compile(Path(path).read_text(encoding='utf-8'), path, 'exec')
Path('.review-changed-files.json').write_text(json.dumps(CHANGED, ensure_ascii=False, indent=2), encoding='utf-8')
print('REVIEWED_CHANGED_FILES', json.dumps(CHANGED, ensure_ascii=False))
