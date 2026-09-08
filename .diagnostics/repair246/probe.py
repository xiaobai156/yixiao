from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from zodiac_v2.cli import _runtime
from zodiac_v2.contracts import RunMode
from zodiac_v2.output import output_paths


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
NAMES = {
    "极乐世界", "博彩爆庄", "创财之星", "王木木儿涂涂", "寒武忌", "富贵当头"
}
OUTPUTS = output_paths(246, ROOT.parent / "七类数据统一归纳", ROOT.parent / "七类数据统一归纳失败")
PROTECTED = (
    ROOT / "sites.json",
    ROOT / "recent_10_cache.json",
    OUTPUTS.existing_success,
    OUTPUTS.new_success,
    OUTPUTS.existing_failure,
    OUTPUTS.new_failure,
)


def hashes():
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        for path in PROTECTED
    }


def main():
    before = hashes()
    sites, scraper = _runtime(ROOT / "sites.json")
    targets = tuple(site for site in sites if site.name in NAMES)
    assert len(targets) == len(NAMES)
    results = scraper.scrape_sites(targets, 246, RunMode.READ_ONLY, workers=3)
    for result in results:
        data = asdict(result)
        if not result.documents and result.site.api_url:
            try:
                data["unbound_bundle"] = asdict(scraper._fetch(result.site, 30))
            except Exception as exc:
                data["unbound_error"] = f"{type(exc).__name__}: {exc}"
        (EVIDENCE / f"{result.site.name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(result.site.name, result.candidate.zodiac if result.ok else result.reason, flush=True)
    assert hashes() == before, "只读验证期间正式文件发生变化"
    (EVIDENCE / "protected_hashes.json").write_text(
        json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("READ_ONLY_HASHES_UNCHANGED")


if __name__ == "__main__":
    main()
