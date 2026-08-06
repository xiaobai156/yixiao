from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from zodiac_v2.contracts import ZODIACS, CacheRecord, Direction, SiteSection, WritePermit

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
    return SiteSection.NEW if str(value or "").strip() == SiteSection.NEW.value else SiteSection.EXISTING


def _direction(value: object) -> Direction:
    try:
        return Direction(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"缓存方向非法：{value!r}") from exc


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
    return records


def _validated_cache_root(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("recent_10_cache.json 根节点必须是对象")
    if data.get("window_back_periods", CACHE_WINDOW) != CACHE_WINDOW:
        raise ValueError("recent_10_cache.json 的 window_back_periods 必须固定为 10")
    latest = data.get("latest_period")
    if latest is not None and (isinstance(latest, bool) or not isinstance(latest, int) or latest <= 0):
        raise ValueError("latest_period 必须是正整数或 null")
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
        _validated_records(site)
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
                continue
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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
