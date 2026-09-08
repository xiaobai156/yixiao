from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType
from typing import Protocol

from zodiac_v2.contracts import Candidate, SiteConfig, SourceBundle


class Parser(Protocol):
    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]: ...


class RegistryError(ValueError):
    pass


class ParserRegistry:
    def __init__(self, entries: Iterable[tuple[str, Parser]]) -> None:
        parsers: dict[str, Parser] = {}
        for parser_id, parser in entries:
            if parser_id in parsers:
                raise RegistryError(f"重复解析器 ID：{parser_id}")
            parsers[parser_id] = parser
        self._parsers = MappingProxyType(parsers)

    @property
    def parser_ids(self) -> frozenset[str]:
        return frozenset(self._parsers)

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        try:
            parser = self._parsers[site.parser_id]
        except KeyError as exc:
            raise RegistryError(f"站点 {site.name} 未绑定已注册解析器：{site.parser_id}") from exc
        return parser.parse(site, bundle)

    def select_source(
        self,
        site: SiteConfig,
        bundle: SourceBundle,
        target_period: int,
    ) -> SourceBundle | None:
        try:
            parser = self._parsers[site.parser_id]
        except KeyError as exc:
            raise RegistryError(f"站点 {site.name} 未绑定已注册解析器：{site.parser_id}") from exc
        selector = getattr(parser, "select_source", None)
        if not callable(selector):
            return None
        return selector(site, bundle, target_period)


def build_registry() -> ParserRegistry:
    from zodiac_v2.parsers.dedicated import parser_entries

    return ParserRegistry(parser_entries())
