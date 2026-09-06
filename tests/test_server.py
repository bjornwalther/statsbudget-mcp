"""Tests for the FastMCP server module."""

import pytest

from statsbudget_mcp.server import (
    EXPENDITURE_AREAS,
    _require_cache,
    _require_scb,
    _require_sk,
    mcp,
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
                RuntimeError, match="SCB client not initialized",
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
    """Verify all expected tools are registered on the MCP server.

    Note: accesses private _tool_manager._tools, which is fragile
    across FastMCP versions. If this breaks, inspect the public API
    for an alternative.
    """

    def _tool_names(self) -> set[str]:
        tools = mcp._tool_manager._tools  # noqa: SLF001
        return set(tools.keys())

    def test_budget_tools_registered(self):
        names = self._tool_names()
        assert "get_budget_overview" in names
        assert "get_expenditure_area" in names
        assert "compare_budgets" in names
        assert "sync_budget_data" in names

    def test_revenue_tools_registered(self):
        names = self._tool_names()
        assert "get_revenue" in names
        assert "get_revenue_timeseries" in names
        assert "get_revenue_detail" in names

    def test_laffer_tools_registered(self):
        names = self._tool_names()
        assert "get_laffer_data" in names
        assert "get_laffer_timeseries" in names
        assert "get_tax_reforms" in names

    def test_meta_tools_registered(self):
        names = self._tool_names()
        assert "get_sync_status" in names
        assert "get_publication_schedule" in names
        assert "get_available_years" in names
        assert "get_cache_stats" in names

    def test_total_tool_count(self):
        names = self._tool_names()
        assert len(names) == 14


class TestEntryPoint:
    def test_main_function_exists(self):
        from statsbudget_mcp.server import main

        assert callable(main)
