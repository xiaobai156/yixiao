from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "核算公式"


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_hesuan_gongshi_is_active_existing_site_with_approved_history() -> None:
    site = next(item for item in _read("sites.json") if item["name"] == NAME)
    cache = next(
        item for item in _read("recent_10_cache.json")["sites"] if item["name"] == NAME
    )

    assert site["pick"] == "bottom"
    assert site["section"] == "已有站点"
    assert site["url"].endswith("/bbs/topic.php?id=22743")
    assert cache["records"][0] == {"period": 240, "zodiac": "羊"}
    assert cache["onboarding_exception"]["exception"] == "用户批准连续3至5期疑似重复特例"
