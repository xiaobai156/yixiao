from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from zodiac_v2.contracts import Direction, SiteConfig, SiteSection


class ConfigError(ValueError):
    pass


_ALLOWED_FIELDS = frozenset(
    {
        "name",
        "url",
        "pick",
        "direction",
        "section",
        "parser_id",
        "source_policy",
        "api_url",
        "article_keyword",
    }
)
_DIRECTION_ALIASES = {
    "top": Direction.TOP,
    "顶部": Direction.TOP,
    "上": Direction.TOP,
    "bottom": Direction.BOTTOM,
    "尾部": Direction.BOTTOM,
    "底部": Direction.BOTTOM,
    "下": Direction.BOTTOM,
}
_SECTION_ALIASES = {
    "": SiteSection.EXISTING,
    "existing": SiteSection.EXISTING,
    "old": SiteSection.EXISTING,
    "已有": SiteSection.EXISTING,
    "已有站点": SiteSection.EXISTING,
    "new": SiteSection.NEW,
    "新增": SiteSection.NEW,
    "新增站点": SiteSection.NEW,
    "新增的站点": SiteSection.NEW,
}


def _text(data: dict[str, Any], field: str, index: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"第 {index} 个站点缺少有效 {field}")
    return value.strip()


def _url(value: str, field: str, index: int) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ConfigError(f"第 {index} 个站点的 {field}/URL 非法：{value!r}")
    return value


def _direction(data: dict[str, Any], index: int) -> Direction:
    if "pick" in data and "direction" in data:
        raise ConfigError(f"第 {index} 个站点不能同时配置 pick 和 direction")
    field = "pick" if "pick" in data else "direction"
    value = data.get(field)
    if not isinstance(value, str) or value.strip() not in _DIRECTION_ALIASES:
        raise ConfigError(f"第 {index} 个站点的 pick/方向非法：{value!r}")
    return _DIRECTION_ALIASES[value.strip()]


def _section(value: object, index: int) -> SiteSection:
    if value is None:
        return SiteSection.EXISTING
    if not isinstance(value, str) or value.strip() not in _SECTION_ALIASES:
        raise ConfigError(f"第 {index} 个站点的 section 非法：{value!r}")
    return _SECTION_ALIASES[value.strip()]


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ConfigError(f"无法读取站点配置：{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"站点配置不是有效 JSON：{path}: {exc}") from exc


def load_sites(
    path: Path,
    *,
    parser_ids: Collection[str],
    source_policies: Collection[str],
) -> tuple[SiteConfig, ...]:
    raw = _read_json(path)
    if not isinstance(raw, list) or not raw:
        raise ConfigError("站点配置根节点必须是非空数组")

    known_parsers = frozenset(parser_ids)
    known_policies = frozenset(source_policies)
    sites: list[SiteConfig] = []
    names: set[str] = set()
    identities: set[tuple[str, str, Direction, SiteSection]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"第 {index} 个站点必须是对象")
        unknown = sorted(set(item) - _ALLOWED_FIELDS)
        if unknown:
            raise ConfigError(f"第 {index} 个站点包含未知字段：{', '.join(unknown)}")

        name = _text(item, "name", index)
        url = _url(_text(item, "url", index), "url", index)
        direction = _direction(item, index)
        section = _section(item.get("section"), index)
        parser_id = _text(item, "parser_id", index)
        source_policy = _text(item, "source_policy", index)
        if parser_id not in known_parsers:
            raise ConfigError(f"第 {index} 个站点使用未知解析器：{parser_id}")
        if source_policy not in known_policies:
            raise ConfigError(f"第 {index} 个站点使用未知取源策略：{source_policy}")

        api_url_value = item.get("api_url")
        api_url = None
        if api_url_value is not None:
            if not isinstance(api_url_value, str) or not api_url_value.strip():
                raise ConfigError(f"第 {index} 个站点的 api_url 必须是非空字符串")
            api_url = _url(api_url_value.strip(), "api_url", index)
        article_keyword_value = item.get("article_keyword")
        article_keyword = None
        if article_keyword_value is not None:
            if not isinstance(article_keyword_value, str) or not article_keyword_value.strip():
                raise ConfigError(f"第 {index} 个站点的 article_keyword 必须是非空字符串")
            article_keyword = article_keyword_value.strip()
        if source_policy == "http_period_keyword_article" and article_keyword is None:
            raise ConfigError(f"第 {index} 个站点的期数关键字详情策略缺少 article_keyword")
        identity = (name, url, direction, section)
        if identity in identities:
            raise ConfigError(f"第 {index} 个站点存在重复身份：{identity}")
        if name in names:
            raise ConfigError(f"第 {index} 个站点存在重复站名：{name}")
        names.add(name)
        identities.add(identity)
        sites.append(
            SiteConfig(
                name,
                url,
                direction,
                section,
                parser_id,
                source_policy,
                api_url,
                article_keyword,
            )
        )

    return tuple(sites)
