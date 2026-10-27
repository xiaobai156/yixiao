from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    ScrapeResult,
    SiteConfig,
    SiteSection,
    SourceDocument,
    WritePermit,
)
from zodiac_v2.output import (
    _format_success_rows,
    build_output_payloads,
    merge_formal_single_result_output,
    output_paths,
    write_output_payloads,
)
from zodiac_v2.services.persistence import CachePersistenceError, commit_targeted_formal_single

_URL = "https://rpczmj.flzw4-yz5wn-mlrxxt.xyz/"


def _site() -> SiteConfig:
    return SiteConfig(
        name="新竹论坛",
        url=_URL,
        direction=Direction.TOP,
        section=SiteSection.NEW,
        parser_id="special.xinzhu_forum",
        source_policy="http_documents",
    )


def _document() -> SourceDocument:
    return SourceDocument(
        "★绝禁一肖★\n224期:绝禁一肖╠鼠鼠鼠╣开0000准",
        _URL,
        DocumentType.SCRIPT,
        0,
        "script:xinzhu",
        0,
    )


def _success() -> ScrapeResult:
    candidate = Candidate(
        224,
        "鼠",
        "224期:绝禁一肖╠鼠鼠鼠╣开0000准",
        "script:xinzhu",
        1,
        ("column:绝禁一肖", "title-line:0", "title-text:★绝禁一肖★"),
    )
    return ScrapeResult._validated_success(_site(), 224, candidate, (_document(),))


def _existing_success() -> ScrapeResult:
    site = SiteConfig(
        name="已有目标站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        parser_id="test",
        source_policy="http_documents",
    )
    document = SourceDocument(
        "224期：鼠",
        site.url,
        DocumentType.HTML,
        0,
        "html:existing",
        0,
        "1",
    )
    candidate = Candidate(
        224,
        "鼠",
        "224期：鼠",
        document.source_id,
        0,
        ("section:杀肖", "block-range:0-1"),
        record_id="1",
    )
    return ScrapeResult._validated_success(site, 224, candidate, (document,))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_merges_success_without_erasing_other_site_rows(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "猴 其他新增站点\n红色\n\n生肖次数排行榜\n猴 1次\n\n前一期失败统计\n无\n")
    _write(paths.new_failure, "无\n")

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    assert "猴 其他新增站点" in paths.new_success.read_text(encoding="utf-8")
    success_text = paths.new_success.read_text(encoding="utf-8")
    assert "鼠 新竹论坛" in success_text
    assert "红色" not in success_text
    assert success_text.index("猴 其他新增站点") < success_text.index("鼠 新竹论坛")
    assert success_text.index("鼠 新竹论坛") < success_text.index("内容\t次数\t排名")
    assert not paths.new_failure.exists()  # 无失败即删除失败清单，不留「无」占位文件


def test_repaired_success_removes_failure_row_with_previous_url(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "无\n")
    _write(
        paths.new_failure,
        "新竹论坛 top https://old.example/ 原因：[方向失败] 旧地址失败\n\n"
        "其他新增站点 top https://example.test/ 原因：[方向失败] 其他\n",
    )

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    failure_text = paths.new_failure.read_text(encoding="utf-8")
    assert "新竹论坛" not in failure_text
    assert "其他新增站点" in failure_text


def test_merge_keeps_existing_same_value_row_without_appending_duplicate(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(
        paths.new_success,
        "鼠 \u200c新竹论坛\n猴 其他新增站点\n红色\n\n生肖次数排行榜\n鼠 1次\n猴 1次\n\n前一期失败统计\n无\n",
    )
    _write(paths.new_failure, "无\n")

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    success_text = paths.new_success.read_text(encoding="utf-8")
    assert success_text.count("新竹论坛") == 1
    assert "鼠 \u200c新竹论坛\n" in success_text
    assert "猴 其他新增站点" in success_text
    assert "红色" not in success_text


def test_failed_repair_keeps_existing_success_row(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "鼠 新竹论坛\n红色\n\n生肖次数排行榜\n鼠 1次\n\n前一期失败统计\n无\n")
    _write(
        paths.new_failure,
        "其他新增站点 top https://example.test/ 原因：[方向失败] 其他\n\n"
        "失败分类统计\n方向失败 1条\n",
    )
    failure = ScrapeResult.failure(
        _site(),
        224,
        FailureCode.DEDICATED_PARSER_MISS,
        "专属解析未命中指定224期",
        (_document(),),
    )

    merge_formal_single_result_output(failure, paths, WritePermit.formal_single(224))

    success_text = paths.new_success.read_text(encoding="utf-8")
    failure_text = paths.new_failure.read_text(encoding="utf-8")
    assert "鼠 新竹论坛" in success_text
    assert "其他新增站点" in failure_text
    assert "新竹论坛 top " + _URL in failure_text
    assert "专属解析未命中" in failure_text


def test_repaired_success_refuses_to_overwrite_existing_different_value(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    original = "牛 新竹论坛\n红色\n\n生肖次数排行榜\n牛 1次\n\n前一期失败统计\n无\n"
    _write(paths.new_success, original)
    _write(paths.new_failure, "无\n")

    with pytest.raises(ValueError, match="成功TXT已有不同值，禁止覆盖"):
        merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    assert paths.new_success.read_text(encoding="utf-8") == original


def test_authorized_repair_corrects_existing_different_value_in_place(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(
        paths.new_success,
        "猴 其他新增站点\n牛 新竹论坛\n红色\n\n生肖次数排行榜\n猴 1次\n牛 1次\n\n前一期失败统计\n无\n",
    )
    _write(paths.new_failure, "无\n")

    merge_formal_single_result_output(
        _success(),
        paths,
        WritePermit.formal_single(224),
        allow_existing_value_correction=True,
    )

    success_text = paths.new_success.read_text(encoding="utf-8")
    assert "猴 其他新增站点\n鼠 新竹论坛\n" in success_text
    assert "红色" not in success_text
    assert "牛 新竹论坛" not in success_text


def test_merge_preserves_multiple_failures_and_reformats_failure_counts(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "无\n")
    _write(
        paths.new_failure,
        "方向失败站点 top https://direction.test/ 原因：[方向失败] 方向越界\n\n"
        "期数失败站点 bottom https://period.test/ 原因：[期数失败] 指定期缺失\n\n"
        f"新竹论坛 top {_URL} 原因：[锚点失败] 旧锚点失败\n\n"
        "失败分类统计\n方向失败 1条\n期数失败 1条\n锚点失败 1条\n",
    )
    failure = ScrapeResult.failure(
        _site(),
        224,
        FailureCode.DEDICATED_PARSER_MISS,
        "专属解析未命中指定224期",
        (_document(),),
    )

    merge_formal_single_result_output(failure, paths, WritePermit.formal_single(224))

    failure_text = paths.new_failure.read_text(encoding="utf-8")
    assert failure_text.count("方向失败站点 top https://direction.test/") == 1
    assert failure_text.count("期数失败站点 bottom https://period.test/") == 1
    assert failure_text.count("新竹论坛 top " + _URL) == 1
    assert "方向越界\n\n期数失败站点" in failure_text
    assert "指定期缺失\n\n新竹论坛" in failure_text
    assert "旧锚点失败" not in failure_text
    assert "方向失败 1条" in failure_text
    assert "期数失败 1条" in failure_text
    assert "专属解析未命中 1条" in failure_text
    assert "锚点失败 1条" not in failure_text


def test_single_success_can_append_existing_section_extra_name(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")

    payloads = build_output_payloads(
        (_success(),),
        paths,
        existing_success_extra_names=("华林",),
    )
    write_output_payloads(payloads, WritePermit.formal_single(224))

    success_text = paths.new_success.read_text(encoding="utf-8")
    existing_text = paths.existing_success.read_text(encoding="utf-8")
    assert "华林" not in success_text
    assert "华林" in existing_text
    assert "羽墨" not in existing_text
    assert existing_text.index("华林") < existing_text.index("内容\t次数\t排名")


def test_formal_single_does_not_automatically_append_hualin(monkeypatch, tmp_path: Path) -> None:
    import zodiac_v2.cli as cli

    class FakeScraper:
        def scrape_sites(self, *args, **kwargs):
            return ()

    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "_runtime", lambda sites_file: ((), FakeScraper()))

    def fake_commit(results, **kwargs):
        captured.update(kwargs)
        return results

    monkeypatch.setattr(cli, "commit_formal_single", fake_commit)

    assert cli.main(
        (
            "single",
            "--period",
            "242",
            "--formal",
            "--sites-file",
            str(tmp_path / "sites.json"),
            "--cache-file",
            str(tmp_path / "cache.json"),
            "--success-dir",
            str(tmp_path / "success"),
            "--failure-dir",
            str(tmp_path / "failure"),
        )
    ) == 0
    assert "existing_success_extra_names" not in captured


def test_output_payload_rejects_result_period_that_does_not_match_paths(tmp_path: Path) -> None:
    paths = output_paths(225, tmp_path / "success", tmp_path / "failure")

    with pytest.raises(PermissionError, match="结果期数与输出文件期数"):
        build_output_payloads((_success(),), paths)


def test_targeted_existing_merge_preserves_success_extra_names(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(
        paths.existing_success,
        "华林\n羽墨\n\n生肖次数排行榜\n\n前一期失败统计\n无\n",
    )
    _write(paths.existing_failure, "无\n")

    merge_formal_single_result_output(
        _existing_success(),
        paths,
        WritePermit.formal_single(224),
    )

    success_text = paths.existing_success.read_text(encoding="utf-8")
    assert "鼠 已有目标站" in success_text
    assert "华林" in success_text
    assert "羽墨" not in success_text
    assert success_text.index("鼠 已有目标站") < success_text.index("华林")
    assert success_text.index("华林") < success_text.index("内容\t次数\t排名")


def test_targeted_merge_recognizes_existing_row_above_ranking(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    original = (
        "猴 其他新增站点\n红色\n鼠 新竹论坛\n\n"
        "生肖次数排行榜\n猴 1次\n鼠 1次\n\n前一期失败统计\n无\n"
    )
    _write(paths.new_success, original)
    _write(paths.new_failure, "无\n")

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    success_text = paths.new_success.read_text(encoding="utf-8")
    assert success_text.count("鼠 新竹论坛") == 1
    assert "红色" not in success_text
    assert success_text.index("鼠 新竹论坛") < success_text.index("内容\t次数\t排名")


def test_success_ranking_uses_dense_ranks_and_columns() -> None:
    text = _format_success_rows(
        (
            ("狗", "甲"),
            ("狗", "乙"),
            ("狗", "丙"),
            ("马", "丁"),
            ("马", "戊"),
            ("龙", "己"),
            ("龙", "庚"),
            ("羊", "辛"),
        ),
        SiteSection.EXISTING,
    )

    assert "内容\t次数\t排名\n狗\t3\t1\n马\t2\t2\n龙\t2\t2\n羊\t1\t3\n" in text
    assert "生肖次数排行榜" not in text
    assert "次\n" not in text


def test_merge_drops_multiline_reason_of_repaired_site_without_orphans(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "无\n")
    _write(
        paths.new_failure,
        f"新竹论坛 top {_URL} 原因：[浏览器取源失败] 浏览器取源失败：Page.goto: net::ERR_TIMED_OUT\n"
        "Call log:\n"
        f'  - navigating to "{_URL}", waiting until "domcontentloaded"\n\n'
        "其他新增站点 top https://example.test/ 原因：[方向失败] 其他\n"
        "Call log:\n"
        '  - navigating to "https://example.test/", waiting until "domcontentloaded"\n\n'
        "失败分类统计\n浏览器取源失败 1条\n方向失败 1条\n",
    )

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    failure_text = paths.new_failure.read_text(encoding="utf-8")
    assert "新竹论坛" not in failure_text
    assert _URL not in failure_text
    assert (
        "其他新增站点 top https://example.test/ 原因：[方向失败] 其他\n"
        "Call log:\n"
        '  - navigating to "https://example.test/", waiting until "domcontentloaded"\n'
    ) in failure_text
    assert "浏览器取源失败" not in failure_text
    assert "方向失败 1条" in failure_text


def test_both_success_files_use_ranked_columns(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    payloads = build_output_payloads((_existing_success(), _success()), paths)

    for path in (paths.existing_success, paths.new_success):
        text = payloads[path]
        assert text is not None
        assert "内容\t次数\t排名" in text
        assert "鼠\t1\t1" in text
        assert "生肖次数排行榜" not in text


def _renamed_success(name: str) -> ScrapeResult:
    site = replace(_site(), name=name)
    return ScrapeResult._validated_success(site, 224, _success().candidate, (_document(),))


def test_full_single_deletes_failure_files_when_no_failure(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_failure, "其他新增站点 top https://example.test/ 原因：[方向失败] 旧失败\n")
    _write(paths.existing_failure, "无\n")

    payloads = build_output_payloads((_existing_success(), _success()), paths)
    assert payloads[paths.new_failure] is None
    assert payloads[paths.existing_failure] is None
    write_output_payloads(payloads, WritePermit.formal_single(224))

    assert not paths.new_failure.exists()
    assert not paths.existing_failure.exists()
    assert paths.new_success.exists()
    assert paths.existing_success.exists()


def test_targeted_merge_deletes_failure_file_when_last_row_is_repaired(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "无\n")
    _write(
        paths.new_failure,
        f"新竹论坛 top {_URL} 原因：[锚点失败] 旧锚点失败\n\n失败分类统计\n锚点失败 1条\n",
    )

    merge_formal_single_result_output(_success(), paths, WritePermit.formal_single(224))

    assert not paths.new_failure.exists()
    assert "鼠 新竹论坛" in paths.new_success.read_text(encoding="utf-8")


def test_targeted_batch_deletion_does_not_resurrect_cleared_rows(tmp_path: Path) -> None:
    paths = output_paths(224, tmp_path / "success", tmp_path / "failure")
    _write(paths.new_success, "无\n")
    _write(
        paths.new_failure,
        f"新竹论坛 top {_URL} 原因：[锚点失败] 旧锚点失败\n\n失败分类统计\n锚点失败 1条\n",
    )
    cache_path = tmp_path / "recent_10_cache.json"
    cache_path.write_text("{broken-json", encoding="utf-8")
    other = "另一新增站点"

    with pytest.raises(CachePersistenceError):
        commit_targeted_formal_single(
            (_success(), _renamed_success(other)),
            expected_sites=(_site(), replace(_site(), name=other)),
            cache_path=cache_path,
            paths=paths,
            permit=WritePermit.formal_single(224),
        )

    assert not paths.new_failure.exists()
