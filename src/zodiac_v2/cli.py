from __future__ import annotations

import argparse
import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

from zodiac_v2.cache import cache_records, load_recent_cache
from zodiac_v2.config import load_sites
from zodiac_v2.contracts import Direction, RunMode, SiteConfig, SiteSection, WritePermit
from zodiac_v2.duplicate import find_duplicate_matches
from zodiac_v2.output import output_paths
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.services.onboarding import validate_new_site
from zodiac_v2.services.persistence import CachePersistenceError, commit_targeted_formal_single
from zodiac_v2.services.repair import repair_sites, sites_from_failure_text
from zodiac_v2.services.scrape import DEFAULT_SITE_TIMEOUT, DefaultSourceGateway, ScrapeService, commit_formal_single

SOURCE_POLICIES = frozenset(
    {
        "http_documents",
        "http_consensus",
        "http_named_topic",
        "http_period_keyword_article",
        "api_then_http",
        "browser",
        "browser_user",
        "http_then_browser",
    }
)
DEFAULT_SUCCESS_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳")
DEFAULT_FAILURE_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败")


def _period(value: str) -> int:
    try:
        period = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("期数必须是整数") from exc
    if not 1 <= period <= 9999:
        raise argparse.ArgumentTypeError("期数必须在 1 到 9999 之间")
    return period


def _positive_workers(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("workers 必须为正整数")
    return result


def _positive_timeout(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("timeout 必须为有限正数")
    return result


def _positive_bytes(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("字节上限必须为正整数") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("字节上限必须为正整数")
    return result


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sites-file", type=Path, default=Path("sites.json"))
    parser.add_argument("--cache-file", type=Path, default=Path("recent_10_cache.json"))
    parser.add_argument("--timeout", type=_positive_timeout, default=DEFAULT_SITE_TIMEOUT)
    parser.add_argument("--workers", type=_positive_workers, default=8)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="杀肖 V2 模块化抓取器")
    commands = parser.add_subparsers(dest="command", required=True)

    single = commands.add_parser("single", help="手动指定单期抓取")
    _common(single)
    single.add_argument("--period", "--issue", type=_period, required=True)
    single.add_argument("--formal", action="store_true", help="明确授权写正式缓存和四类 TXT")
    single.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    single.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)

    retry = commands.add_parser("retry", help="按失败清单限定复抓，只读验证")
    _common(retry)
    retry.add_argument("--period", "--issue", type=_period, required=True)
    retry.add_argument("--retry-errors", type=Path, action="append", required=True)
    retry.add_argument("--formal", action="store_true", help="验证通过后正式更新 TXT 和缓存")
    retry.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    retry.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)

    duplicate = commands.add_parser("duplicate", help="仅使用 recent_10_cache.json 判重")
    _common(duplicate)
    duplicate.add_argument("--period", "--issue", type=_period, required=True)
    duplicate.add_argument("--periods", type=int, choices=(10,), default=10)

    onboard = commands.add_parser("onboard", help="新增站点只读验收")
    _common(onboard)
    onboard.add_argument("--name", required=True)
    onboard.add_argument("--url", required=True)
    onboard.add_argument("--api-url")
    onboard.add_argument("--article-keyword")
    onboard.add_argument("--embedded-max-bytes", type=_positive_bytes)
    onboard.add_argument(
        "--pick",
        choices=(Direction.TOP.value, Direction.BOTTOM.value),
        default=Direction.TOP.value,
    )
    onboard.add_argument(
        "--section",
        choices=tuple(section.value for section in SiteSection),
        default=SiteSection.NEW.value,
    )
    onboard.add_argument("--parser-id", default="family.strict_article")
    onboard.add_argument("--source-policy", choices=tuple(sorted(SOURCE_POLICIES)), default="http_documents")
    onboard.add_argument("--period", "--issue", type=_period, required=True)
    onboard.add_argument("--allow-short-history", action="store_true")

    repair = commands.add_parser("repair", help="已有失败站八阶段只读修复验证")
    _common(repair)
    repair.add_argument("--period", "--issue", type=_period, required=True)
    repair.add_argument("--retry-errors", type=Path, action="append", required=True)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _runtime(sites_file: Path) -> tuple[tuple[SiteConfig, ...], ScrapeService]:
    registry = build_registry()
    sites = load_sites(
        sites_file,
        parser_ids=registry.parser_ids,
        source_policies=SOURCE_POLICIES,
    )
    return sites, ScrapeService(DefaultSourceGateway(), registry)


def _print_results(results) -> None:
    for result in results:
        if result.ok and result.candidate is not None:
            print(f"{result.site.name} {result.candidate.zodiac}")
        else:
            print(
                f"{result.site.name} {result.site.direction.value} {result.site.url} "
                f"原因：[{result.failure_code.value if result.failure_code else 'other'}] {result.reason}"
            )
    success = sum(result.ok for result in results)
    print(f"完成：成功 {success}，失败 {len(results) - success}")


def _progress_printer(start: float):
    counts = {"success": 0, "failure": 0}

    def print_progress(completed: int, total: int, result) -> None:
        if result.ok:
            counts["success"] += 1
            status = "成功"
        else:
            counts["failure"] += 1
            status = f"失败 原因：{result.reason}"
        percent = int(completed * 100 / total) if total else 100
        elapsed = monotonic() - start
        print(
            f"进度 {completed}/{total} {percent}% "
            f"成功 {counts['success']} 失败 {counts['failure']} "
            f"用时: {elapsed:.1f}s 当前: {result.site.name} {status}",
            flush=True,
        )

    return print_progress


def _run_duplicate(args: argparse.Namespace, data: object) -> int:
    records = tuple(record for record in cache_records(data) if record.period <= args.period)
    grouped = defaultdict(list)
    for record in records:
        grouped[record.identity].append(record)
    pairs: dict[tuple[tuple[object, ...], tuple[object, ...]], str] = {}
    for identity, candidate in grouped.items():
        if len(candidate) < 3 or not any(record.period == args.period for record in candidate):
            continue
        for match in find_duplicate_matches(
            candidate,
            records,
            minimum_consecutive_periods=3,
            exclude_identity=identity,
        ):
            pair = tuple(sorted((identity, match.identity), key=str))
            typed_pair = pair  # type: ignore[assignment]
            previous = pairs.get(typed_pair)
            pairs[typed_pair] = (
                "confirmed"
                if match.risk == "confirmed" or previous == "confirmed"
                else "suspected"
            )
    if not pairs:
        print("未发现重复网站")
    for index, pair in enumerate(sorted(pairs, key=str), start=1):
        label = "确定重复" if pairs[pair] == "confirmed" else "疑似重复"
        print(f"{label}组{index}")
        for identity in pair:
            print(f"{identity[0]} {identity[1]}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    sites, scraper = _runtime(args.sites_file)
    if args.command == "single":
        mode = RunMode.FORMAL_SINGLE if args.formal else RunMode.READ_ONLY
        start = monotonic()
        print(f"开始抓取：{args.period}期，共 {len(sites)} 个站点，workers={args.workers}", flush=True)
        results = scraper.scrape_sites(
            sites,
            args.period,
            mode,
            timeout=args.timeout,
            workers=args.workers,
            on_result=_progress_printer(start),
        )
        if args.formal:
            try:
                results = commit_formal_single(
                    results,
                    cache_path=args.cache_file,
                    paths=output_paths(args.period, args.success_dir, args.failure_dir),
                    permit=WritePermit.formal_single(args.period),
                    expected_sites=sites,
                )
            except CachePersistenceError:
                _print_results(results)
                print("正式 TXT 已发布，但缓存更新失败；本次命令返回状态码 3", flush=True)
                return 3
        _print_results(results)
        return 0
    if args.command in {"retry", "repair"}:
        text = "\n".join(path.read_text(encoding="utf-8-sig") for path in args.retry_errors)
        selected = sites_from_failure_text(text, sites)
        if not selected:
            print("失败清单没有匹配到任何站点，未抓取、未写入")
            return 2
        formal = args.command == "retry" and args.formal
        results = scraper.scrape_sites(selected, args.period,
            RunMode.FORMAL_SINGLE if formal else RunMode.READ_ONLY,
            timeout=args.timeout, workers=args.workers)
        if formal:
            try:
                results = commit_targeted_formal_single(results, expected_sites=selected,
                    cache_path=args.cache_file, paths=output_paths(args.period, args.success_dir, args.failure_dir),
                    permit=WritePermit.formal_single(args.period))
            except CachePersistenceError:
                _print_results(results)
                print("正式 TXT 已发布，但缓存更新失败；本次命令返回状态码 3", flush=True)
                return 3
        else:
            print("限定复抓为只读验证，未写缓存或正式 TXT")
        _print_results(results)
        return 0
    if args.command == "duplicate":
        return _run_duplicate(args, load_recent_cache(args.cache_file))
    if args.command == "onboard":
        candidate = SiteConfig(
            args.name,
            args.url,
            Direction(args.pick),
            SiteSection(args.section),
            args.parser_id,
            args.source_policy,
            args.api_url,
            args.article_keyword,
            args.embedded_max_bytes,
        )
        data = load_recent_cache(args.cache_file)
        periods = tuple(range(args.period, max(0, args.period - 10), -1))
        decision = validate_new_site(
            scraper,
            candidate,
            sites,
            data,
            periods,
            allow_short_history=args.allow_short_history,
        )
        for reason in decision.reasons:
            print(reason)
        print("新增站点验收通过" if decision.accepted else "新增站点验收拒绝")
        print("验收过程未写 sites.json、缓存或正式 TXT")
        return 0 if decision.accepted else 2
    raise RuntimeError(f"未处理命令：{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
