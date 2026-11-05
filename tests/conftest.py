"""Cross-platform skip rules for tests that need a real Windows shell."""

import os

import pytest

WINDOWS_COMMAND_TESTS = {
    'test_daily_batch_without_period_shows_error_instead_of_cmd_parser_crash',
    'test_duplicate_batch_without_period_returns_failure',
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        if os.name != 'nt' and item.name in WINDOWS_COMMAND_TESTS:
            item.add_marker(pytest.mark.skip(reason='Requires real Windows cmd.exe; exercised by Windows CI.'))
