"""Keep old production-snapshot assertions intact and explicitly opt-in.

These eight tests describe manual onboarding at periods 238/240/241, not the
current rolling cache. Never reset production data to make them green.
"""
import os

import pytest

HISTORICAL_SNAPSHOTS = {
    'test_240_onboarding_batch_sites.py::test_approved_batch_is_in_existing_sites_with_validated_history',
    'test_241_onboarding_batch_sites.py::test_authorized_241_batch_config_and_cache',
    'test_batch_238_sites.py::test_formal_batch_238_config_is_complete_and_scoped',
    'test_hesuan_gongshi_site.py::test_hesuan_gongshi_is_active_existing_site_with_approved_history',
    'test_nangeng_fuzhi_onboarding.py::test_nangeng_fuzhi_formal_config_and_cache',
    'test_user_forum_special.py::test_241_special_user_sites_are_formal_existing_sites_with_cache_and_output',
    'test_xlsx_240_onboarding_sites.py::test_xlsx_240_sites_have_complete_cache_and_authorized_exceptions',
    'test_xlsx_240_onboarding_sites.py::test_xlsx_240_sites_are_merged_into_existing_success_only',
}
WINDOWS_COMMAND_TESTS = {
    'test_daily_batch_without_period_shows_error_instead_of_cmd_parser_crash',
    'test_duplicate_batch_without_period_returns_failure',
}


def pytest_addoption(parser):
    parser.addoption('--historical-snapshots', action='store_true',
                     help='Run legacy 238/240/241 snapshot assertions; requires matching historical data and TXT.')


def pytest_collection_modifyitems(config, items):
    for item in items:
        key = item.nodeid.replace('\\', '/').split('/')[-1]
        if key in HISTORICAL_SNAPSHOTS:
            item.add_marker(pytest.mark.historical_snapshot)
            if not config.getoption('--historical-snapshots'):
                item.add_marker(pytest.mark.skip(reason='Historical production snapshot (238/240/241), not portable runtime test; opt in with --historical-snapshots and matching data.'))
        if os.name != 'nt' and item.name in WINDOWS_COMMAND_TESTS:
            item.add_marker(pytest.mark.skip(reason='Requires real Windows cmd.exe; exercised by Windows CI.'))
