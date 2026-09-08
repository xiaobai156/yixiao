import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
VALUES = {
    "延颈企踵": "鼠",
    "千差万别": "龙",
    "碁布星罗": "蛇",
    "嘟嘟哝哝": "龙",
    "埋头苦干": "蛇",
    "高手资料": "羊",
    "不绝于耳": "兔",
    "赤光旅行": "猴",
    "山川落笔": "龙",
    "神机图": "龙",
    "马会传真": "蛇",
    "主持人": "虎",
    "奶香萌男": "猴",
    "爱情微凉": "龙",
    "放声大笑": "鸡",
    "爱里嚣张": "猴",
}
NORMAL = {"碁布星罗", "高手资料"}
CONFIRMED_DUPLICATE_EXCEPTION = {"延颈企踵"}


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_approved_batch_is_in_existing_sites_with_validated_history() -> None:
    sites = {site["name"]: site for site in _read("sites.json") if site["name"] in VALUES}
    cached = {
        site["name"]: site
        for site in _read("recent_10_cache.json")["sites"]
        if site["name"] in VALUES
    }

    assert sites.keys() == VALUES.keys()
    assert cached.keys() == VALUES.keys()
    for name, zodiac in VALUES.items():
        assert sites[name]["section"] == "已有站点"
        assert cached[name]["section"] == "已有站点"
        assert cached[name]["records"][0] == {"period": 240, "zodiac": zodiac}
        assert [record["period"] for record in cached[name]["records"]] == list(
            range(240, 230, -1)
        )
        if name in NORMAL:
            assert "onboarding_exception" not in cached[name]
        else:
            assert cached[name]["onboarding_exception"] == {
                "target_period": 240,
                "exception": (
                    "用户批准连续6期以上确定重复特例"
                    if name in CONFIRMED_DUPLICATE_EXCEPTION
                    else "用户批准连续3至5期疑似重复特例"
                ),
                "validated_periods": list(range(240, 230, -1)),
            }
