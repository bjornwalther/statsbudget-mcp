"""Tests for the FastMCP server module."""

import pytest

from statsbudget_mcp.server import (
    EXPENDITURE_AREAS,
    _require_cache,
    _require_scb,
    _require_sk,
    mcp,
)

# Tool functions are module-level, imported to verify they exist
from statsbudget_mcp.server import (
    get_budget_overview,
    get_expenditure_area,
    compare_budgets,
    sync_budget_data,
    get_revenue,
    get_revenue_timeseries,
    get_revenue_detail,
    get_laffer_data,
    get_laffer_timeseries,
    get_tax_reforms,
    get_sync_status,
    get_publication_schedule,
    get_available_years,
    get_cache_stats,
)


class TestServerSetup:
    def test_mcp_name(self):
        assert mcp.name == "statsbudget-mcp"

    def test_mcp_has_instructions(self):
        instructions = getattr(mcp, "instructions", None) or ""
        assert "Swedish national budget" in instructions

    def test_expenditure_areas_count(self):
        assert len(EXPENDITURE_AREAS) == 27

    def test_expenditure_areas_format(self):
        for area_id, name in EXPENDITURE_AREAS:
            assert len(area_id) == 2
            assert area_id.isdigit()
            assert len(name) > 0

    def test_area_ids_sequential(self):
        ids = [int(aid) for aid, _ in EXPENDITURE_AREAS]
        assert ids == list(range(1, 28))


class TestClientGuards:
    def test_require_scb_raises_when_not_initialized(self):
        import statsbudget_mcp.server as mod

        original = mod._scb
        mod._scb = None
        try:
            with pytest.raises(
                RuntimeError,
                match="SCB client not initialized",
            ):
                _require_scb()
        finally:
            mod._scb = original

    def test_require_sk_raises_when_not_initialized(self):
        import statsbudget_mcp.server as mod

        original = mod._sk
        mod._sk = None
        try:
            with pytest.raises(
                RuntimeError,
                match="Statskontoret client not initialized",
            ):
                _require_sk()
        finally:
            mod._sk = original

    def test_require_cache_raises_when_not_initialized(self):
        import statsbudget_mcp.server as mod

        original = mod._cache
        mod._cache = None
        try:
            with pytest.raises(
                RuntimeError, match="Cache not initialized",
            ):
                _require_cache()
        finally:
            mod._cache = original


class TestToolRegistration:
    """Verify all 14 tool functions are importable and callable.

    Uses direct function imports instead of private FastMCP
    internals (_tool_manager), so this works across all
    FastMCP versions.
    """

    EXPECTED_TOOLS = [
        get_budget_overview,
        get_expenditure_area,
        compare_budgets,
        sync_budget_data,
        get_revenue,
        get_revenue_timeseries,
        get_revenue_detail,
        get_laffer_data,
        get_laffer_timeseries,
        get_tax_reforms,
        get_sync_status,
        get_publication_schedule,
        get_available_years,
        get_cache_stats,
    ]

    def test_all_tools_callable(self):
        for fn in self.EXPECTED_TOOLS:
            assert callable(fn), f"{fn.__name__} not callable"

    def test_total_tool_count(self):
        assert len(self.EXPECTED_TOOLS) == 14

    def test_budget_tools_exist(self):
        names = {fn.__name__ for fn in self.EXPECTED_TOOLS}
        assert "get_budget_overview" in names
        assert "get_expenditure_area" in names
        assert "compare_budgets" in names
        assert "sync_budget_data" in names

    def test_revenue_tools_exist(self):
        names = {fn.__name__ for fn in self.EXPECTED_TOOLS}
        assert "get_revenue" in names
        assert "get_revenue_timeseries" in names
        assert "get_revenue_detail" in names

    def test_laffer_tools_exist(self):
        names = {fn.__name__ for fn in self.EXPECTED_TOOLS}
        assert "get_laffer_data" in names
        assert "get_laffer_timeseries" in names
        assert "get_tax_reforms" in names

    def test_meta_tools_exist(self):
        names = {fn.__name__ for fn in self.EXPECTED_TOOLS}
        assert "get_sync_status" in names
        assert "get_publication_schedule" in names
        assert "get_available_years" in names
        assert "get_cache_stats" in names


class TestSyncErrorHandling:
    """Server imports and catches SyncError."""

    def test_sync_error_in_sync_errors_tuple(self):
        from statsbudget_mcp.server import _SYNC_ERRORS
        from statsbudget_mcp.statskontoret import SyncError

        assert SyncError in _SYNC_ERRORS

    def test_value_error_in_sync_errors_tuple(self):
        from statsbudget_mcp.server import _SYNC_ERRORS

        assert ValueError in _SYNC_ERRORS


class TestEntryPoint:
    def test_main_function_exists(self):
        from statsbudget_mcp.server import main

        assert callable(main)
