"""306 期剩余两站浏览器验证（只读）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CASE = {
    "谈笑封侯": "https://knfoaep.ivqs8-1depw-yoirtw.xyz:29444/article/manager/6a095183291caff3edcb8a29?url=lf",
    "寒武忌": "https://uuizld.ytv5j-jva78-vglwnj.work/#/users/180502",
}
API = {
    "寒武忌": "https://uuizld.ytv5j-jva78-vglwnj.work/api/v1/users/180502/forums?per_page=10",
}


def api_rows(url: str) -> dict:
    try:
        payload = requests.get(url, headers={"User-Agent": UA}, timeout=25).json()
        if isinstance(payload, list):
            return {
                "count": len(payload),
                "rows": [{k: r.get(k) for k in ("id", "draw", "topic", "status")} for r in payload[:6]],
            }
        return {"preview": str(payload)[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def page_text(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            text = page.inner_text("body")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            hits = [ln for ln in lines if re.search(r"30[0-9]", ln)]
            (OUT / f"text2_{url.split('/')[2]}.txt").write_text(text, encoding="utf-8")
            return {
                "status": resp.status if resp else None,
                "title": page.title(),
                "hits": hits[:12],
            }
        finally:
            browser.close()


def main() -> int:
    out = {}
    for name, url in CASE.items():
        out[name] = {"page": page_text(url)}
        if name in API:
            out[name]["api"] = api_rows(API[name])
        print(json.dumps({name: out[name]}, ensure_ascii=False), flush=True)
    (OUT / "probe2_306.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
