from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from zodiac_v2.cli import DEFAULT_FAILURE_DIR, DEFAULT_SUCCESS_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BAT_PATH = PROJECT_ROOT / "爬虫-每天杀肖.bat"
DUPLICATE_BAT_PATH = PROJECT_ROOT / "爬虫-每天杀肖 - 检查重复.bat"


def test_formal_output_defaults_use_requested_directories() -> None:
    assert Path(
        r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳"
    ) == DEFAULT_SUCCESS_DIR
    assert Path(
        r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败"
    ) == DEFAULT_FAILURE_DIR


def test_daily_batch_uses_cmd_compatible_line_endings() -> None:
    payload = BAT_PATH.read_bytes()

    assert b"\r\n" in payload
    assert b"\n" not in payload.replace(b"\r\n", b"")


def test_duplicate_batch_uses_cmd_compatible_line_endings() -> None:
    payload = DUPLICATE_BAT_PATH.read_bytes()

    assert b"\r\n" in payload
    assert b"\n" not in payload.replace(b"\r\n", b"")


def test_daily_batch_does_not_reference_removed_external_runtime() -> None:
    text = BAT_PATH.read_text(encoding="utf-8")

    assert "CRAWLER_RUNTIME" not in text
    assert "公共抓取运行库" not in text


def test_service_v2_entrypoint_and_bridge_are_removed() -> None:
    assert not (PROJECT_ROOT / "爬虫-每天杀肖-Service-V2.bat").exists()
    assert not (PROJECT_ROOT / "src" / "zodiac_v2" / "shared_runtime_bridge.py").exists()


def test_local_runtime_constructs_without_external_runtime_dependency() -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    environment.pop("CRAWLER_RUNTIME", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from zodiac_v2.cli import _runtime; "
                "sites, scraper = _runtime(Path('sites.json')); "
                "print(len(sites))"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().isdigit()


def test_daily_batch_without_period_shows_error_instead_of_cmd_parser_crash() -> None:
    result = subprocess.run(
        [str(Path(r"C:\Windows\System32\cmd.exe")), "/d", "/c", str(BAT_PATH)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=False,
    )
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

    assert result.returncode == 1
    assert "ERROR: period is required." in output
    assert "was unexpected at this time" not in output


def test_duplicate_batch_without_period_returns_failure() -> None:
    result = subprocess.run(
        [
            str(Path(r"C:\Windows\System32\cmd.exe")),
            "/d",
            "/c",
            str(DUPLICATE_BAT_PATH),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=False,
    )
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

    assert result.returncode == 1
    assert "ERROR: period is required." in output


def test_duplicate_batch_propagates_python_exit_code_and_restores_directory() -> None:
    text = DUPLICATE_BAT_PATH.read_text(encoding="utf-8")

    assert "setlocal" in text
    assert 'set "RC=%ERRORLEVEL%"' in text
    assert "popd" in text
    assert "exit /b %RC%" in text
