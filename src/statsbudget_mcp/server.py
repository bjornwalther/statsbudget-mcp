"""FastMCP server for statsbudget-mcp.

Exposes Swedish national budget data as MCP tools. Entry point for
`uvx statsbudget-mcp` and Claude Desktop integration.

Startup behavior:
1. Open SQLite cache (~/.statsbudget-cache/statsbudget.db)
2. If cache has data and is fresh (< 1 week): load from cache (ms)
3. If cache is empty or stale: sync from Statskontoret, save to cache
4. SCB data is fetched on-demand (with retry) and cached per session
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from .cache import BudgetCache
from .laffer import (
    TAX_REFORMS,
    build_laffer_curve,
    laffer_timeseries,
    laffer_to_chart_data,
)
from .scb_client import SCBClient
from .statskontoret import (
    ExpenditureRow,
    IncomeRow,
    StatskontoretClient,
)

_scb: SCBClient | None = None
_sk: StatskontoretClient | None = None
_cache: BudgetCache | None = None


def _rows_to_dicts(rows: list) -> list[dict[str, Any]]:
    """Convert dataclass rows to dicts for cache storage."""
    return [asdict(r) for r in rows]


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize clients, load or sync data, tear down on exit."""
    global _scb, _sk, _cache
    _scb = SCBClient()
    _sk = StatskontoretClient()
    _cache = BudgetCache()

    # Load from cache if fresh, otherwise sync
    try:
        if _cache.is_populated() and not _cache.needs_refresh():
            _load_from_cache(_sk, _cache)
            print(
                f"Loaded from cache ({_cache.db_path}), "
                f"age: {_cache.cache_age_hours():.1f}h",
                file=sys.stderr,
            )
        else:
            print("Cache empty or stale, syncing...", file=sys.stderr)
            try:
                await _sync_and_cache(_sk, _cache)
                print("Sync complete, data cached.", file=sys.stderr)
            except Exception as exc:
                print(f"Sync failed: {exc}. Starting with empty data.", file=sys.stderr)
                if _cache.is_populated():
                    _load_from_cache(_sk, _cache)
                    print("Fell back to stale cache.", file=sys.stderr)
    except Exception as exc:
        print(f"Startup warning: {exc}", file=sys.stderr)

    try:
        yield
    finally:
        if _scb:
            await _scb.close()
        if _sk:
            await _sk.close()
        if _cache:
            _cache.close()
        _scb = None
        _sk = None
        _cache = None


def _load_from_cache(sk: StatskontoretClient, cache: BudgetCache) -> None:
    """Populate the Statskontoret client from cached data."""
    exp_rows = cache.load_expenditure()
    inc_rows = cache.load_income()
    sk._expenditure_data = [
        ExpenditureRow(**{k: v for k, v in r.items()}) for r in exp_rows
    ]
    sk._income_data = [
        IncomeRow(**{k: v for k, v in r.items()}) for r in inc_rows
    ]


async def _sync_and_cache(sk: StatskontoretClient, cache: BudgetCache) -> None:
    """Sync from Statskontoret and persist to cache."""
    await sk.sync()
    cache.store_expenditure(_rows_to_dicts(sk.expenditure_data))
    cache.store_income(_rows_to_dicts(sk.income_data))
    cache.set_meta("last_sync_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))


mcp = FastMCP(
    "statsbudget-mcp",
    description=(
        "Swedish national budget data: expenditure areas, tax revenue, "
        "Laffer curve analysis, and budget comparisons. "
        "Data from SCB, Statskontoret, and Riksdagen."
    ),
    lifespan=lifespan,
)


def _require_scb() -> SCBClient:
    if _scb is None:
        raise RuntimeError("SCB client not initialized. Server not started?")
    return _scb


def _require_sk() -> StatskontoretClient:
    if _sk is None:
        raise RuntimeError("Statskontoret client not initialized. Server not started?")
    return _sk


def _require_cache() -> BudgetCache:
    if _cache is None:
        raise RuntimeError("Cache not initialized. Server not started?")
    return _cache


EXPENDITURE_AREAS = [
    ("01", "Rikets styrelse"),
    ("02", "Samh\u00e4llsekonomi och finansf\u00f6rvaltning"),
    ("03", "Skatt, tull och exekution"),
    ("04", "R\u00e4ttsv\u00e4sendet"),
    ("05", "Internationell samverkan"),
    ("06", "F\u00f6rsvar och samh\u00e4llets krisberedskap"),
    ("07", "Internationellt bist\u00e5nd"),
    ("08", "Migration"),
    ("09", "H\u00e4lsov\u00e5rd, sjukv\u00e5rd och social omsorg"),
    ("10", "Ekonomisk trygghet vid sjukdom och funktionsneds\u00e4ttning"),
    ("11", "Ekonomisk trygghet vid \u00e5lderdom"),
    ("12", "Ekonomisk trygghet f\u00f6r familjer och barn"),
    ("13", "Integration och j\u00e4mst\u00e4lldhet"),
    ("14", "Arbetsmarknad och arbetsliv"),
    ("15", "Studiest\u00f6d"),
    ("16", "Utbildning och universitetsforskning"),
    ("17", "Kultur, medier, trossamfund och fritid"),
    ("18", "Samh\u00e4llsplanering, bostadsf\u00f6rs\u00f6rjning och byggande samt konsumentpolitik"),
    ("19", "Regional utveckling"),
    ("20", "Allm\u00e4n milj\u00f6- och naturv\u00e5rd"),
    ("21", "Energi"),
    ("22", "Kommunikationer"),
    ("23", "Areella n\u00e4ringar, landsbygd och livsmedel"),
    ("24", "N\u00e4ringsliv"),
    ("25", "Allm\u00e4nna bidrag till kommuner"),
    ("26", "Statsskulds\u00e4ntor m.m."),
    ("27", "Avgiften till Europeiska unionen"),
]


# ---------------------------------------------------------------------------
# Budget tools (Statskontoret)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_budget_overview(year: int) -> dict[str, Any]:
    """Get the Swedish national budget overview for a given year.

    Returns total expenditure, total income, balance, and all 27
    expenditure areas with budget vs outcome amounts in MSEK.

    Args:
        year: Budget year (2006-2025 available).
    """
    sk = _require_sk()
    overview = sk.get_budget_overview(year)
    return {
        "year": overview.year,
        "total_expenditure_msek": overview.total_expenditure_msek,
        "total_income_msek": overview.total_income_msek,
        "balance_msek": overview.balance_msek,
        "areas": [
            {
                "area_id": a.area_id,
                "area_name": a.area_name,
                "budget_msek": a.budget_msek,
                "outcome_msek": a.outcome_msek,
                "delta_msek": a.delta_msek,
            }
            for a in overview.areas
        ],
    }


@mcp.tool()
async def get_expenditure_area(area_id: str, year: int) -> list[dict[str, Any]]:
    """Drill down into a specific expenditure area.

    Returns all appropriations within the area with budget, outcome,
    and balance amounts in MSEK.

    Args:
        area_id: Two-digit area ID (e.g. "01" for Rikets styrelse, "06" for Defence).
        year: Budget year.
    """
    sk = _require_sk()
    rows = sk.get_expenditure_area(area_id, year)
    return [
        {
            "appropriation_id": r.appropriation_id,
            "appropriation_name": r.appropriation_name,
            "budget_msek": r.budget_msek,
            "amendment_budgets_msek": r.amendment_budgets_msek,
            "outcome_msek": r.outcome_msek,
            "opening_balance_msek": r.opening_balance_msek,
            "closing_balance_msek": r.closing_balance_msek,
        }
        for r in rows
    ]


@mcp.tool()
async def compare_budgets(year_a: int, year_b: int) -> list[dict[str, Any]]:
    """Compare budget outcomes between two years.

    Returns per-area comparison with absolute delta (MSEK) and
    percentage change.

    Args:
        year_a: First year (baseline).
        year_b: Second year (comparison).
    """
    sk = _require_sk()
    return sk.compare_budgets(year_a, year_b)


@mcp.tool()
async def sync_budget_data(year: int | None = None) -> dict[str, Any]:
    """Download and parse latest budget data from Statskontoret.

    Also persists the data to the local SQLite cache so subsequent
    server startups are instant.

    Args:
        year: Specific year to sync (default: latest available).
    """
    sk = _require_sk()
    cache = _require_cache()
    status = await sk.sync(year=year)

    # Persist to cache
    cache.store_expenditure(_rows_to_dicts(sk.expenditure_data))
    cache.store_income(_rows_to_dicts(sk.income_data))
    cache.set_meta("last_sync_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    return {
        "last_sync": status.last_sync,
        "next_expected_update": status.next_expected_update,
        "cache_stats": cache.get_stats(),
        "sources": [
            {
                "source": s.source,
                "last_synced_at": s.last_synced_at,
                "source_last_updated": s.source_last_updated,
                "files_downloaded": s.files_downloaded,
                "years_covered": s.years_covered,
            }
            for s in status.sources
        ],
    }


# ---------------------------------------------------------------------------
# Revenue tools (SCB)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_revenue(year: int) -> dict[str, Any]:
    """Get tax revenue breakdown for a specific year.

    Returns total revenue and breakdown by category (labour, capital,
    consumption, other) in MSEK.

    Args:
        year: Tax year (2000-2024 available).
    """
    scb = _require_scb()
    rows = await scb.get_tax_revenue_summary(years=[year])
    result: dict[str, float | None] = {}
    label_map = {
        "101": "labour",
        "140": "capital",
        "160": "consumption",
        "180": "other",
        "190": "total",
    }
    for row in rows:
        key = label_map.get(row.tax_type_code, row.tax_type_code)
        result[key] = row.amount_msek

    return {"year": year, "revenue_msek": result}


@mcp.tool()
async def get_revenue_timeseries(
    from_year: int = 2000, to_year: int = 2024
) -> list[dict[str, Any]]:
    """Get tax revenue timeseries grouped by category.

    Returns yearly data with labour, capital, consumption, other,
    and total amounts in MSEK.

    Args:
        from_year: Start year (default 2000).
        to_year: End year (default 2024).
    """
    scb = _require_scb()
    return await scb.get_revenue_timeseries(from_year=from_year, to_year=to_year)


@mcp.tool()
async def get_revenue_detail(
    year: int, tax_types: list[str] | None = None
) -> list[dict[str, Any]]:
    """Get detailed tax revenue for specific tax types.

    Returns full breakdown with all 40 SCB tax categories.

    Args:
        year: Tax year.
        tax_types: Optional list of SCB tax type codes to filter.
    """
    scb = _require_scb()
    rows = await scb.get_tax_revenue(years=[year], tax_types=tax_types)
    return [
        {
            "tax_type_code": r.tax_type_code,
            "tax_type_label": r.tax_type_label,
            "year": r.year,
            "amount_msek": r.amount_msek,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Laffer curve tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_laffer_data(
    from_year: int = 1950, to_year: int = 2025
) -> dict[str, Any]:
    """Get Laffer curve data: total tax pressure vs GDP over time.

    Returns scatter plot data grouped by decade with annotated reform
    years (1976 Pomperipossa, 1991 century reform, 2020 varnskatt removed).

    Args:
        from_year: Start year (default 1950).
        to_year: End year (default 2025).
    """
    scb = _require_scb()
    points = await build_laffer_curve(scb, from_year=from_year, to_year=to_year)
    return laffer_to_chart_data(points)


@mcp.tool()
async def get_laffer_timeseries(
    from_year: int = 1950, to_year: int = 2025
) -> list[dict[str, Any]]:
    """Get tax quota timeseries with reform annotations.

    Returns yearly tax quota (% of GDP) with markers at major reforms.
    Suitable for line chart visualization.

    Args:
        from_year: Start year (default 1950).
        to_year: End year (default 2025).
    """
    scb = _require_scb()
    points = await build_laffer_curve(scb, from_year=from_year, to_year=to_year)
    return laffer_timeseries(points)


@mcp.tool()
async def get_tax_reforms() -> list[dict[str, Any]]:
    """Get list of major Swedish tax reforms with descriptions.

    Returns reform year, label, and description for annotating
    visualizations.
    """
    return TAX_REFORMS


# ---------------------------------------------------------------------------
# Meta tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_sync_status() -> dict[str, Any]:
    """Get data freshness information.

    Returns when budget data was last synced, when the source was
    last updated, and when to expect the next publication.
    """
    sk = _require_sk()
    cache = _require_cache()
    status = sk.get_sync_status()
    return {
        "last_sync": status.last_sync,
        "next_expected_update": status.next_expected_update,
        "cache": cache.get_stats(),
        "sources": [
            {
                "source": s.source,
                "description": s.description,
                "publication_cadence": s.publication_cadence,
                "last_synced_at": s.last_synced_at,
                "source_last_updated": s.source_last_updated,
                "years_covered": s.years_covered,
            }
            for s in status.sources
        ],
    }


@mcp.tool()
async def get_publication_schedule() -> dict[str, Any]:
    """Get the Statskontoret data publication schedule.

    Shows when new budget data is typically published (March and June)
    and what each release contains.
    """
    sk = _require_sk()
    return sk.get_publication_schedule()


@mcp.tool()
async def get_available_years() -> dict[str, Any]:
    """Get list of years with loaded budget data.

    Returns years for which expenditure and income data is available.
    Call sync_budget_data first if this returns empty.
    """
    sk = _require_sk()
    return {"years": sk.get_available_years()}


@mcp.tool()
async def get_cache_stats() -> dict[str, Any]:
    """Get SQLite cache diagnostics.

    Returns row counts, years covered, cache age, and whether
    a refresh is recommended.
    """
    cache = _require_cache()
    return cache.get_stats()


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("budget://areas")
async def budget_areas() -> str:
    """All 27 Swedish expenditure areas (id, name)."""
    return json.dumps(
        [{"area_id": aid, "area_name": name} for aid, name in EXPENDITURE_AREAS],
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server (called by `statsbudget-mcp` console script)."""
    mcp.run()


if __name__ == "__main__":
    main()
