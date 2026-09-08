"""Commit only the two independently verified 246 repairs."""
from contextlib import ExitStack
import json
import msvcrt
from pathlib import Path
import tempfile

from probe import EVIDENCE, OUTPUTS, ROOT, hashes
from verify import EXPECTED
from zodiac_v2.cache import update_recent_cache, write_recent_cache
from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode, WritePermit
from zodiac_v2.output import merge_formal_single_result_output, output_paths
from zodiac_v2.services.scrape import cache_record_from_result


def _prefix(text: str) -> str:
    return text.replace("\r\n", "\n").split("内容\t次数\t排名", 1)[0].rstrip()


def main():
    verified = json.loads((EVIDENCE / "verification.json").read_text(encoding="utf-8"))
    assert {row["site"]: row["zodiac"] for row in verified if "zodiac" in row} == EXPECTED
    before_fetch = hashes()
    sites, scraper = _runtime(ROOT / "sites.json")
    targets = tuple(site for site in sites if site.name in EXPECTED)
    assert len(targets) == 2
    results = scraper.scrape_sites(targets, 246, RunMode.FORMAL_SINGLE, workers=2)
    assert len(results) == 2
    for result in results:
        assert result.ok and result.candidate is not None
        assert result.writable and result.validator_issued
        assert result.candidate.zodiac == EXPECTED[result.site.name]
        print("FORMAL", result.site.name, result.candidate.zodiac)
    assert hashes() == before_fetch, "正式重跑期间输出或缓存发生变化"

    permit = WritePermit.formal_single(246)
    touched = (OUTPUTS.new_success, OUTPUTS.new_failure, ROOT / "recent_10_cache.json")
    with ExitStack() as stack:
        for path in touched:
            lock = stack.enter_context(path.with_name(path.name + ".lock").open("a+b"))
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)

        original_success = OUTPUTS.new_success.read_bytes()
        original_failure = OUTPUTS.new_failure.read_bytes()
        original_cache = (ROOT / "recent_10_cache.json").read_bytes()
        with tempfile.TemporaryDirectory(prefix="repair246-", dir=EVIDENCE) as temporary:
            staged = output_paths(246, Path(temporary), Path(temporary))
            staged.new_success.write_bytes(original_success)
            staged.new_failure.write_bytes(original_failure)
            for result in results:
                merge_formal_single_result_output(result, staged, permit)
            old_text = original_success.decode("utf-8-sig")
            new_text = staged.new_success.read_text(encoding="utf-8")
            assert _prefix(new_text).startswith(_prefix(old_text))
            added = [f"{result.candidate.zodiac} {result.site.name}" for result in results
                     if f"{result.candidate.zodiac} {result.site.name}" not in _prefix(old_text).splitlines()]
            assert _prefix(new_text)[len(_prefix(old_text)):].split() == " ".join(added).split()
            old_failure_rows = [line for line in original_failure.decode("utf-8-sig").splitlines() if " 原因：" in line]
            new_failure_rows = [line for line in staged.new_failure.read_text(encoding="utf-8").splitlines() if " 原因：" in line]
            assert new_failure_rows == [line for line in old_failure_rows
                                        if not any(line.startswith(result.site.name + " ") for result in results)]
            assert OUTPUTS.new_success.read_bytes() == original_success
            assert OUTPUTS.new_failure.read_bytes() == original_failure
            for result in results:
                merge_formal_single_result_output(result, OUTPUTS, permit)
            assert OUTPUTS.new_success.read_bytes() == staged.new_success.read_bytes()
            assert OUTPUTS.new_failure.read_bytes() == staged.new_failure.read_bytes()

        cache_path = ROOT / "recent_10_cache.json"
        assert cache_path.read_bytes() == original_cache
        old_cache = json.loads(original_cache)
        updated = update_recent_cache(
            old_cache,
            [cache_record_from_result(result) for result in results],
            current_period=246,
            permit=permit,
        )
        unchanged_fragments = []
        for old, new in zip(old_cache["sites"], updated["sites"]):
            assert old["name"] == new["name"]
            if old["name"] not in EXPECTED:
                assert old == new
                fragment = ("    " + json.dumps(old, ensure_ascii=False, indent=2).replace("\n", "\n    ")).encode()
                assert fragment in original_cache
                unchanged_fragments.append(fragment)
            else:
                assert new["records"][0] == {"period": 246, "zodiac": EXPECTED[old["name"]]}
                assert new["records"][1:] == old["records"][:9]
        assert len(old_cache["sites"]) == len(updated["sites"])
        assert {key: value for key, value in old_cache.items() if key != "sites"} == {
            key: value for key, value in updated.items() if key != "sites"
        }
        write_recent_cache(cache_path, updated, permit)
        written = cache_path.read_bytes()
        assert json.loads(written) == updated
        assert all(fragment in written for fragment in unchanged_fragments)

    after = hashes()
    assert after[str(OUTPUTS.existing_success)] == before_fetch[str(OUTPUTS.existing_success)]
    assert after[str(OUTPUTS.existing_failure)] == before_fetch[str(OUTPUTS.existing_failure)]
    report = {
        "period": 246,
        "updated": EXPECTED,
        "unrelated_cache_entries_unchanged": len(unchanged_fragments),
        "hashes": after,
    }
    (EVIDENCE / "commit-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
