"""老大指名特例：俊少 306 期按人工确认写「虎」（源站原文为「306.杀虎狗」双肖）。

自动验证器会因「双肖」拒绝写入，因此这里按授权做定点人工写入：
  * 先回源确认 306 行仍含「虎」，并把原文行哈希留档；
  * 成功 TXT / 失败 TXT 复用项目自身格式化函数，走 locked_paths + atomic_batch_write；
  * 缓存按项目 update_recent_cache/write_recent_cache 正常写入。
不修改解析器、不改变「双肖即失败」的通用规则。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from zodiac_v2.cache import load_recent_cache, update_recent_cache, write_recent_cache  # noqa: E402
from zodiac_v2.contracts import (  # noqa: E402
    CacheRecord,
    Direction,
    SiteSection,
    WritePermit,
)
from zodiac_v2.output import (  # noqa: E402
    _failure_name_key,
    _failure_rows,
    _format_failure_rows,
    _format_success_rows,
    _success_extra_names,
    _success_rows,
    _validate_existing_success_text,
)
from zodiac_v2.storage import atomic_batch_write, locked_paths  # noqa: E402

BASE = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集")
SUCCESS_TXT = BASE / "七类数据统一归纳" / "306期-肖-新增.txt"
FAILURE_TXT = BASE / "七类数据统一归纳失败" / "306期-肖-失败-新增.txt"
CACHE = ROOT / "recent_10_cache.json"
API = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/api/v1/users/133911/forums?per_page=20"
SITE_URL = "https://qvuuqqs.8imf7-hteuh-ylwuqv.xyz/#/users/133911"
NAME = "俊少"
PERIOD = 306
ZODIAC = "虎"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def source_line() -> tuple[str, str]:
    resp = requests.get(API, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    target = next((row for row in rows if row.get("draw") == PERIOD), None)
    if target is None:
        raise SystemExit("源站 API 未找到 306 期帖子，终止写入")
    content = str(target.get("content") or "")
    # 正文是一整行带 <div> 的 HTML，行内用「306.杀X」这种写法，不能按行首匹配。
    match = re.search(rf"(?<![0-9]){PERIOD}\.(杀[^<\s]*)", content)
    if match is None:
        raise SystemExit(f"306 期正文未找到「{PERIOD}.杀…」行，终止写入")
    line = f"{PERIOD}.{match.group(1).strip()}"
    if ZODIAC not in line:
        raise SystemExit(f"源站 306 行不含「{ZODIAC}」：{line!r}，终止写入")
    return line, str(target.get("id"))


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return "无\n"


def main() -> int:
    line, post_id = source_line()
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    print(f"源站 306 行：{line}  帖子ID={post_id}  sha256={digest[:16]}…")

    permit = WritePermit.formal_single(PERIOD)

    success_text = read(SUCCESS_TXT)
    _validate_existing_success_text(success_text)
    rows = _success_rows(success_text)
    extras = _success_extra_names(success_text)
    existing = {name for _zodiac, name in rows}
    if NAME not in existing:
        rows.append((ZODIAC, NAME))
    success_payload = _format_success_rows(rows, SiteSection.NEW, extra_names=extras)

    failure_text = read(FAILURE_TXT)
    kept = [
        row
        for row in _failure_rows(failure_text)
        if _failure_name_key(row) != NAME
    ]
    failure_payload = _format_failure_rows(kept)

    payload = {
        SUCCESS_TXT: success_payload.encode("utf-8"),
        FAILURE_TXT: None if failure_payload is None else failure_payload.encode("utf-8"),
    }
    with locked_paths((SUCCESS_TXT, FAILURE_TXT, CACHE)):
        atomic_batch_write(payload)

        record = CacheRecord(
            name=NAME,
            url=SITE_URL,
            direction=Direction.BOTTOM,
            section=SiteSection.NEW,
            period=PERIOD,
            zodiac=ZODIAC,
            source_id=f"post:{post_id}",
            source_url=API,
            evidence_sha256=digest,
            record_id=str(post_id),
        )
        data = load_recent_cache(CACHE)
        updated = update_recent_cache(data, (record,), current_period=PERIOD, permit=permit)
        write_recent_cache(CACHE, updated, permit)

    print(f"已写入：{SUCCESS_TXT.name}（{NAME} {ZODIAC}）")
    print(f"失败清单已移除 {NAME}，剩余：{[_failure_name_key(row) for row in kept]}")
    print("缓存已写入 306 期", NAME, ZODIAC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
