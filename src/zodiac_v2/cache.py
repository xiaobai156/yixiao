from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from zodiac_v2.contracts import ZODIACS, CacheRecord, Direction, SiteSection, WritePermit

from zodiac_v2.storage import atomic_write_bytes, locked_paths

CACHE_WINDOW = 10
_CACHE_TOKEN = object()
CacheIdentity = tuple[str, str, Direction, SiteSection]


def _cache_digest(data: Mapping[str, object]) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _CacheWriteData(dict[str, object]):
    __slots__ = ("_token", "_digest")

    def __init__(self, data: Mapping[str, object]) -> None:
        super().__init__(data)
        self._token = _CACHE_TOKEN
        self._digest = _cache_digest(self)


def _section(value: object) -> SiteSection:
    normalized = str(value or "").strip()
    if not normalized:
        return SiteSection.EXISTING
    try:
        return SiteSection(normalized)
    except ValueError as exc:
        raise ValueError(f"缓存目录分类非法：{value!r}") from exc


def _direction(value: object) -> Direction:
    try:
        direction = Direction(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"缓存方向非法：{value!r}") from exc
    if direction is Direction.LEFT:
        raise ValueError(f"缓存方向非法：{value!r}")
    return direction


def _identity(site: Mapping[str, object]) -> tuple[str, str, Direction, SiteSection]:
    name = str(site.get("name") or "").strip()
    url = str(site.get("url") or "").strip()
    if not name or not url:
        raise ValueError("缓存目录必须包含非空 name 和 url")
    return (name, url, _direction(site.get("pick") or site.get("region")), _section(site.get("section")))


def _validated_records(site: Mapping[str, object]) -> list[tuple[int, str]]:
    raw = site.get("records", [])
    if not isinstance(raw, list):
        raise ValueError("缓存目录 records 必须是数组")
    if len(raw) > CACHE_WINDOW:
        raise ValueError("缓存有效记录不能超过 10 条")
    records: list[tuple[int, str]] = []
    periods: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("缓存 records 项必须是对象")
        period = item.get("period")
        if isinstance(period, bool) or not isinstance(period, int) or not 1 <= period <= 9999:
            raise ValueError(f"缓存期数非法：{period!r}")
        zodiac = str(item.get("zodiac") or "").strip()
        if len(zodiac) != 1 or zodiac not in ZODIACS:
            raise ValueError(f"缓存生肖非法：{zodiac!r}")
        if period in periods:
            raise ValueError(f"缓存目录 {_identity(site)[0]} 存在重复期号 {period}")
        periods.add(period)
        records.append((period, zodiac))
    if records != sorted(records, reverse=True):
        raise ValueError(f"缓存目录 {_identity(site)[0]} 的 records 必须按期数倒序")
    fingerprint = site.get("fingerprint")
    expected = "".join(zodiac for _period, zodiac in records)
    if fingerprint is not None and str(fingerprint) != expected:
        raise ValueError(f"缓存目录 {_identity(site)[0]} 的 fingerprint 与 records 不一致")
    provenance = site.get("record_provenance")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("record_provenance 必须是对象")
    if records and not isinstance(provenance, dict):
        raise ValueError("record_provenance 必须与 records 完整对应")
    if isinstance(provenance, dict):
        record_periods = {str(period) for period, _zodiac in records}
        if set(provenance) != record_periods:
            raise ValueError("record_provenance 必须与 records 完整对应")
        for period, value in provenance.items():
            if period not in record_periods or not isinstance(value, dict):
                raise ValueError(f"record_provenance 期数或记录非法：{period!r}")
            if value.get("validation_status") != "validated":
                raise ValueError(f"record_provenance {period} 缺少 validated 状态")
            source_id = str(value.get("source_id") or "").strip()
            source_url = str(value.get("source_url") or "").strip()
            evidence_sha256 = str(value.get("evidence_sha256") or "").strip()
            if not source_id or not source_url:
                raise ValueError(f"record_provenance {period} 缺少来源身份")
            parsed_source = urlsplit(source_url)
            if (
                parsed_source.scheme not in {"http", "https"}
                or not parsed_source.netloc
                or parsed_source.username
                or parsed_source.password
            ):
                raise ValueError(f"record_provenance {period} 的 source_url 非法")
            if re.fullmatch(r"[0-9a-fA-F]{64}", evidence_sha256) is None:
                raise ValueError(f"record_provenance {period} 的 evidence_sha256 非法")
            raw_record_id = value.get("record_id")
            if raw_record_id is not None and (
                isinstance(raw_record_id, bool)
                or not isinstance(raw_record_id, (str, int))
                or not str(raw_record_id).strip()
            ):
                raise ValueError(f"record_provenance {period} 的 record_id 非法")
    return records


def _validated_cache_root(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("recent_10_cache.json 根节点必须是对象")
    if data.get("window_back_periods", CACHE_WINDOW) != CACHE_WINDOW:
        raise ValueError("recent_10_cache.json 的 window_back_periods 必须固定为 10")
    latest = data.get("latest_period")
    if latest is not None and (
        isinstance(latest, bool)
        or not isinstance(latest, int)
        or not 1 <= latest <= 9999
    ):
        raise ValueError("latest_period 必须是 1 到 9999 的整数或 null")
    if not isinstance(data.get("sites"), list):
        raise ValueError("recent_10_cache.json 的 sites 必须是数组")
    quarantined = data.get("quarantined_sites", [])
    if not isinstance(quarantined, list):
        raise ValueError("recent_10_cache.json 的 quarantined_sites 必须是数组")
    return data


def _quarantined_identity(item: Mapping[str, object]) -> CacheIdentity:
    raw = item.get("identity")
    if not isinstance(raw, dict):
        raise ValueError("隔离缓存目录 identity 必须是对象")
    if any(key not in raw for key in ("name", "url", "pick", "section")):
        raise ValueError("隔离缓存目录 identity 必须包含 name、url、pick 和 section")
    name = str(raw.get("name") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not name or not url:
        raise ValueError("隔离缓存目录 identity 的 name 和 url 不能为空")
    direction = _direction(raw.get("pick"))
    try:
        section = SiteSection(str(raw.get("section") or "").strip())
    except ValueError as exc:
        raise ValueError(f"隔离缓存目录分类非法：{raw.get('section')!r}") from exc
    return name, url, direction, section


def _validated_quarantined_sites(data: Mapping[str, object]) -> dict[CacheIdentity, str]:
    output: dict[CacheIdentity, str] = {}
    for item in data.get("quarantined_sites", []):
        if not isinstance(item, dict):
            raise ValueError("quarantined_sites 项必须是对象")
        identity = _quarantined_identity(item)
        if identity in output:
            raise ValueError(f"缓存存在重复隔离目录身份：{identity[0]} {identity[1]}")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"隔离缓存目录 {identity[0]} 必须包含失败原因")
        entry = item.get("entry")
        if not isinstance(entry, dict):
            raise ValueError(f"隔离缓存目录 {identity[0]} 的 entry 必须是对象")
        if _identity(entry) != identity:
            raise ValueError(f"隔离缓存目录 {identity[0]} 的 identity 与 entry 不一致")
        expected_sha256 = _cache_digest(entry)
        if str(item.get("entry_sha256") or "") != expected_sha256:
            raise ValueError(f"隔离缓存目录 {identity[0]} 的 entry_sha256 不一致")
        output[identity] = reason
    return output


def _quarantine_site(site: Mapping[str, object], identity: CacheIdentity, reason: str) -> dict[str, object]:
    entry = deepcopy(dict(site))
    return {
        "identity": {
            "name": identity[0],
            "url": identity[1],
            "pick": identity[2].value,
            "section": identity[3].value,
        },
        "reason": reason,
        "entry": entry,
        "entry_sha256": _cache_digest(entry),
    }


def validate_cache_data(data: object) -> dict[str, object]:
    validated_root = _validated_cache_root(data)
    sites = validated_root["sites"]
    identities: set[CacheIdentity] = set()
    for site in sites:
        if not isinstance(site, dict):
            raise ValueError("缓存 sites 项必须是对象")
        identity = _identity(site)
        if identity in identities:
            raise ValueError(f"缓存存在重复目录身份：{identity[0]} {identity[1]}")
        identities.add(identity)
        records = _validated_records(site)
        latest = validated_root.get("latest_period")
        if isinstance(latest, int) and any(period > latest for period, _zodiac in records):
            raise ValueError(
                f"缓存目录 {identity[0]} 存在晚于 latest_period {latest} 的记录"
            )
    quarantined = _validated_quarantined_sites(validated_root)
    overlap = identities & quarantined.keys()
    if overlap:
        identity = next(iter(overlap))
        raise ValueError(f"缓存活动目录与隔离目录身份重复：{identity[0]} {identity[1]}")
    return deepcopy(validated_root)


def _read_recent_cache(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"recent_10_cache.json 读取或 JSON 解析失败：{path}") from exc


def load_recent_cache(path: Path) -> dict[str, object]:
    return validate_cache_data(_read_recent_cache(path))


def load_recent_cache_for_commit(path: Path) -> tuple[dict[str, object], dict[CacheIdentity, str]]:
    raw = _validated_cache_root(_read_recent_cache(path))
    existing_quarantined = _validated_quarantined_sites(raw)
    seen = set(existing_quarantined)
    errors = dict(existing_quarantined)
    valid_sites: list[dict[str, object]] = []
    quarantined_sites = deepcopy(raw.get("quarantined_sites", []))
    for site in raw["sites"]:
        if not isinstance(site, dict):
            raise ValueError("缓存 sites 项必须是对象")
        identity = _identity(site)
        if identity in seen:
            raise ValueError(f"缓存存在重复目录身份：{identity[0]} {identity[1]}")
        seen.add(identity)
        try:
            _validated_records(site)
        except ValueError as exc:
            reason = str(exc)
            errors[identity] = reason
            quarantined_sites.append(_quarantine_site(site, identity, reason))
            continue
        valid_sites.append(deepcopy(site))
    isolated = deepcopy(raw)
    isolated["sites"] = valid_sites
    if quarantined_sites:
        isolated["quarantined_sites"] = quarantined_sites
    else:
        isolated.pop("quarantined_sites", None)
    return validate_cache_data(isolated), errors


def _proof(site: Mapping[str, object], period: int) -> tuple[str, str, str, str | None] | None:
    provenance_by_period = site.get("record_provenance")
    if not isinstance(provenance_by_period, dict):
        return None
    value = provenance_by_period.get(str(period))
    if not isinstance(value, dict) or value.get("validation_status") != "validated":
        return None
    source_id = str(value.get("source_id") or "").strip()
    source_url = str(value.get("source_url") or "").strip()
    evidence_sha256 = str(value.get("evidence_sha256") or "").strip()
    if not source_id or not source_url or not evidence_sha256:
        return None
    raw_record_id = value.get("record_id")
    if raw_record_id is None:
        record_id = None
    elif isinstance(raw_record_id, bool) or not isinstance(raw_record_id, (str, int)):
        return None
    else:
        record_id = str(raw_record_id).strip()
        if not record_id:
            return None
    return source_id, source_url, evidence_sha256, record_id


def cache_records(data: object) -> tuple[CacheRecord, ...]:
    validated = validate_cache_data(data)
    if validated.get("quarantined_sites"):
        raise ValueError("缓存存在隔离目录，判重未完成")
    output: list[CacheRecord] = []
    for site in validated["sites"]:
        identity = _identity(site)
        for period, zodiac in _validated_records(site):
            proof = _proof(site, period)
            if proof is None:
                raise ValueError(f"缓存目录 {identity[0]} {period}期缺少完整来源证明，判重拒绝继续")
            output.append(CacheRecord(*identity, period, zodiac, *proof))
    return tuple(output)


def update_recent_cache(
    data: object,
    records: Iterable[CacheRecord],
    *,
    current_period: int,
    permit: WritePermit,
) -> dict[str, object]:
    permit.require_formal_single(current_period)
    updated = validate_cache_data(data)
    latest = updated.get("latest_period")
    if isinstance(latest, int) and current_period < latest:
        raise ValueError(f"缓存不能从 {latest}期 回滚到 {current_period}期")
    sites: list[dict[str, Any]] = updated["sites"]  # type: ignore[assignment]
    by_identity = {_identity(site): site for site in sites}
    quarantined = _validated_quarantined_sites(updated)
    seen: set[tuple[str, str, Direction, SiteSection]] = set()
    for record in records:
        if not isinstance(record, CacheRecord):
            raise ValueError("缓存更新只能包含 CacheRecord")
        if record.period != current_period:
            raise ValueError(f"缓存写入期数边界失败：{record.period}期 不等于 {current_period}期")
        if record.identity in seen:
            raise ValueError(f"缓存写入包含重复目录身份：{record.name}")
        seen.add(record.identity)
        if record.identity in quarantined:
            raise ValueError(f"缓存目录 {record.name} 已隔离：{quarantined[record.identity]}")
        site = by_identity.get(record.identity)
        if site is None:
            site = {
                "name": record.name,
                "pick": record.direction.value,
                "url": record.url,
                "section": record.section.value,
                "error": "",
                "records": [],
                "fingerprint": "",
            }
            sites.append(site)
            by_identity[record.identity] = site
        records_by_period = dict(_validated_records(site))
        existing = records_by_period.get(current_period)
        if existing is not None and existing != record.zodiac:
            raise ValueError(
                f"缓存同期冲突：{record.name} {current_period}期旧值 {existing}，新值 {record.zodiac}"
            )
        records_by_period[current_period] = record.zodiac
        kept = sorted((period for period in records_by_period if period <= current_period), reverse=True)[:CACHE_WINDOW]
        site["records"] = [{"period": period, "zodiac": records_by_period[period]} for period in kept]
        site["fingerprint"] = "".join(records_by_period[period] for period in kept)
        site["error"] = ""
        provenance = site.get("record_provenance")
        provenance_by_period = dict(provenance) if isinstance(provenance, dict) else {}
        provenance_by_period[str(current_period)] = {
            "validation_status": "validated",
            "source_id": record.source_id,
            "source_url": record.source_url,
            "evidence_sha256": record.evidence_sha256,
        }
        if record.record_id is not None:
            provenance_by_period[str(current_period)]["record_id"] = record.record_id
        provenance_by_period = {
            str(period): proof
            for period, proof in (
                (int(key), value)
                for key, value in provenance_by_period.items()
                if str(key).isdigit()
            )
            if period in kept and isinstance(proof, dict)
        }
        site["record_provenance"] = provenance_by_period
    updated["window_back_periods"] = CACHE_WINDOW
    updated["latest_period"] = current_period
    return _CacheWriteData(validate_cache_data(updated))


def backfill_recent_cache_records(
    data: object,
    records: Iterable[CacheRecord],
    *,
    permit: WritePermit,
) -> dict[str, object]:
    """Add one validated older period without rolling back the cache window."""

    target_period = permit.target_period
    permit.require_formal_single(target_period)
    updated = validate_cache_data(data)
    latest = updated.get("latest_period")
    if not isinstance(latest, int) or target_period > latest:
        raise ValueError("缓存旧期回填目标不能晚于当前最新期")
    sites: list[dict[str, Any]] = updated["sites"]  # type: ignore[assignment]
    by_identity = {_identity(site): site for site in sites}
    quarantined = _validated_quarantined_sites(updated)
    seen: set[CacheIdentity] = set()
    for record in records:
        if not isinstance(record, CacheRecord):
            raise ValueError("缓存回填只能包含 CacheRecord")
        if record.period != target_period:
            raise ValueError(f"缓存回填期数边界失败：{record.period}期 不等于 {target_period}期")
        if record.identity in seen:
            raise ValueError(f"缓存回填包含重复目录身份：{record.name}")
        seen.add(record.identity)
        if record.identity in quarantined:
            raise ValueError(f"缓存目录 {record.name} 已隔离：{quarantined[record.identity]}")
        site = by_identity.get(record.identity)
        if site is None:
            raise ValueError(f"缓存回填目录身份不存在：{record.name}")
        records_by_period = dict(_validated_records(site))
        existing = records_by_period.get(target_period)
        if existing is not None and existing != record.zodiac:
            raise ValueError(
                f"缓存同期冲突：{record.name} {target_period}期旧值 {existing}，新值 {record.zodiac}"
            )
        records_by_period[target_period] = record.zodiac
        kept = sorted(records_by_period, reverse=True)[:CACHE_WINDOW]
        if target_period not in kept:
            raise ValueError(
                f"缓存回填目标 {record.name} {target_period}期已超出当前近{CACHE_WINDOW}期窗口，未写入缓存"
            )
        site["records"] = [
            {"period": period, "zodiac": records_by_period[period]} for period in kept
        ]
        site["fingerprint"] = "".join(records_by_period[period] for period in kept)
        provenance = site.get("record_provenance")
        provenance_by_period = dict(provenance) if isinstance(provenance, dict) else {}
        provenance_by_period[str(target_period)] = {
            "validation_status": "validated",
            "source_id": record.source_id,
            "source_url": record.source_url,
            "evidence_sha256": record.evidence_sha256,
        }
        if record.record_id is not None:
            provenance_by_period[str(target_period)]["record_id"] = record.record_id
        site["record_provenance"] = {
            str(period): provenance_by_period[str(period)]
            for period in kept
            if isinstance(provenance_by_period.get(str(period)), dict)
        }
        exception = site.get("onboarding_exception")
        if isinstance(exception, dict):
            exception = dict(exception)
            for key in ("validated_periods", "valid_periods"):
                periods = exception.get(key)
                if isinstance(periods, list) and all(isinstance(period, int) for period in periods):
                    exception[key] = sorted({*periods, target_period}, reverse=True)
            missing = exception.get("missing_periods")
            if isinstance(missing, list):
                exception["missing_periods"] = [
                    period for period in missing if period != target_period
                ]
            site["onboarding_exception"] = exception
    return _CacheWriteData(validate_cache_data(updated))


def replace_site_direction(
    data: object,
    *,
    name: str,
    url: str,
    section: SiteSection,
    direction: Direction,
    permit: WritePermit,
) -> dict[str, object]:
    """Migrate one existing cache identity when its configured direction changes."""
    permit.require_formal_single(permit.target_period)
    updated = validate_cache_data(data)
    if not name.strip() or not url.strip():
        raise ValueError("缓存方向迁移必须包含站名和 URL")
    if not isinstance(section, SiteSection) or not isinstance(direction, Direction):
        raise ValueError("缓存方向迁移的分类或方向非法")
    sites: list[dict[str, Any]] = updated["sites"]  # type: ignore[assignment]
    matches = [
        site
        for site in sites
        if isinstance(site, dict)
        and site.get("name") == name
        and site.get("url") == url
        and _section(site.get("section")) is section
    ]
    if len(matches) != 1:
        raise ValueError(f"缓存方向迁移命中 {len(matches)} 个站点：{name}")
    target = matches[0]
    old_identity = _identity(target)
    new_identity = (name, url, direction, section)
    if old_identity == new_identity:
        return _CacheWriteData(validate_cache_data(updated))
    if any(
        site is not target and isinstance(site, dict) and _identity(site) == new_identity
        for site in sites
    ):
        raise ValueError(f"缓存方向迁移目标身份已存在：{name}")
    target["pick"] = direction.value
    return _CacheWriteData(validate_cache_data(updated))


def mark_failed_sites(
    data: object,
    failures: Iterable[tuple[CacheIdentity, str]],
    *,
    current_period: int,
    permit: WritePermit,
) -> dict[str, object]:
    """Record current-period failures without exposing stale values as success."""
    permit.require_formal_single(current_period)
    updated = validate_cache_data(data)
    latest = updated.get("latest_period")
    if isinstance(latest, int) and current_period < latest:
        raise ValueError(f"缓存不能从 {latest}期 回滚到 {current_period}期")
    sites: list[dict[str, Any]] = updated["sites"]  # type: ignore[assignment]
    by_identity = {_identity(site): site for site in sites}
    quarantined = _validated_quarantined_sites(updated)
    seen: set[CacheIdentity] = set()
    for identity, reason in failures:
        if identity in seen:
            raise ValueError(f"缓存失败标记包含重复目录身份：{identity[0]}")
        seen.add(identity)
        if not reason.strip():
            raise ValueError(f"缓存失败标记缺少失败原因：{identity[0]}")
        if identity in quarantined:
            continue
        site = by_identity.get(identity)
        if site is None:
            site = {
                "name": identity[0],
                "pick": identity[2].value,
                "url": identity[1],
                "section": identity[3].value,
                "error": "",
                "records": [],
                "fingerprint": "",
            }
            sites.append(site)
            by_identity[identity] = site
        records_by_period = dict(_validated_records(site))
        records_by_period.pop(current_period, None)
        kept = sorted(
            (period for period in records_by_period if period <= current_period),
            reverse=True,
        )[:CACHE_WINDOW]
        site["records"] = [
            {"period": period, "zodiac": records_by_period[period]} for period in kept
        ]
        site["fingerprint"] = "".join(records_by_period[period] for period in kept)
        site["error"] = reason.strip()
        provenance = site.get("record_provenance")
        if isinstance(provenance, dict):
            site["record_provenance"] = {
                str(period): proof
                for period, proof in (
                    (int(key), value)
                    for key, value in provenance.items()
                    if str(key).isdigit()
                )
                if period in kept and isinstance(proof, dict)
            }
    updated["window_back_periods"] = CACHE_WINDOW
    updated["latest_period"] = current_period
    return _CacheWriteData(validate_cache_data(updated))


def _atomic_write(path: Path, text: str) -> None:
    with locked_paths((path,)):
        atomic_write_bytes(path, text.encode('utf-8'))


def write_recent_cache(path: Path, data: object, permit: WritePermit) -> None:
    validated = validate_cache_data(data)
    latest = validated.get("latest_period")
    if not isinstance(latest, int):
        raise PermissionError("正式缓存写入必须包含明确 latest_period")
    permit.require_formal_single(latest)
    if not isinstance(data, _CacheWriteData) or data._token is not _CACHE_TOKEN:
        raise PermissionError("正式缓存只接受统一验证器签发数据")
    if data._digest != _cache_digest(validated):
        raise PermissionError("正式缓存签发数据已被修改")
    _atomic_write(path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n")


def append_onboarding_records(
    data: object,
    records: Iterable[CacheRecord],
    *,
    current_period: int,
    permit: WritePermit,
    metadata: Mapping[CacheIdentity, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build signed cache data for formally accepted onboarding sites."""

    permit.require_formal_single(current_period)
    updated = validate_cache_data(data)
    grouped: dict[CacheIdentity, list[CacheRecord]] = {}
    for record in records:
        if not isinstance(record, CacheRecord):
            raise ValueError("新增站点缓存只能包含 CacheRecord")
        if record.period > current_period:
            raise ValueError(f"新增站点缓存期数不能超过基准期：{record.period}期")
        grouped.setdefault(record.identity, []).append(record)
    if not grouped:
        raise ValueError("正式新增没有可写入的缓存记录")

    existing = {_identity(site) for site in updated["sites"] if isinstance(site, dict)}
    for identity, site_records in grouped.items():
        if identity in existing:
            raise ValueError(f"缓存已有站点身份重复：{identity[0]}")
        periods = [record.period for record in site_records]
        if len(set(periods)) != len(periods):
            raise ValueError(f"新增站点缓存存在重复期号：{identity[0]}")
        ordered = sorted(site_records, key=lambda item: item.period, reverse=True)
        if len(ordered) > CACHE_WINDOW:
            raise ValueError(f"新增站点缓存超过 {CACHE_WINDOW} 期：{identity[0]}")
        entry: dict[str, object] = {
            "name": identity[0],
            "pick": identity[2].value,
            "url": identity[1],
            "section": identity[3].value,
            "error": "",
            "records": [
                {"period": record.period, "zodiac": record.zodiac} for record in ordered
            ],
            "fingerprint": "".join(record.zodiac for record in ordered),
            "record_provenance": {
                str(record.period): {
                    "validation_status": "validated",
                    "source_id": record.source_id,
                    "source_url": record.source_url,
                    "evidence_sha256": record.evidence_sha256,
                    **({"record_id": record.record_id} if record.record_id is not None else {}),
                }
                for record in ordered
            },
        }
        if metadata is not None and identity in metadata:
            entry["onboarding_exception"] = dict(metadata[identity])
        updated["sites"].append(entry)
        existing.add(identity)
    latest = updated.get("latest_period")
    if not isinstance(latest, int) or current_period > latest:
        updated["latest_period"] = current_period
    return _CacheWriteData(validate_cache_data(updated))


def write_recent_cache_backfill(path: Path, data: object, permit: WritePermit) -> None:
    """Atomically persist an onboarded site's older history without rolling back the cache window."""
    validated = validate_cache_data(data)
    latest = validated.get("latest_period")
    if not isinstance(latest, int):
        raise PermissionError("正式缓存回填必须包含明确 latest_period")
    permit.require_formal_single(permit.target_period)
    if latest < permit.target_period:
        raise PermissionError(
            f"缓存总窗口 {latest}期 早于回填目标 {permit.target_period}期，禁止前置写入"
        )
    if not isinstance(data, _CacheWriteData) or data._token is not _CACHE_TOKEN:
        raise PermissionError("正式缓存回填只接受统一验证器签发数据")
    if data._digest != _cache_digest(validated):
        raise PermissionError("正式缓存回填签发数据已被修改")
    _atomic_write(path, json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
