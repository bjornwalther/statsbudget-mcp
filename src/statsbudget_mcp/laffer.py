"""Laffer curve analysis module for statsbudget-mcp.

Provides data and computation for Laffer curve visualization using
SCB's SkattekvotBNP table. The primary visualization plots total
tax pressure (% of GDP) against tax revenue growth or level.

This is the standard "total tax burden" Laffer analysis used in
international comparisons (OECD, EU) and Swedish public debate.

Data source: SCB PxWeb API, table SkattekvotBNP (1950-2025)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scb_client import SCBClient

# Notable Swedish tax reforms for annotation
TAX_REFORMS: list[dict[str, Any]] = [
    {
        "year": 1971,
        "label": "S\u00e4rskild inkomstskatt inf\u00f6rs",
        "description": "Individuell beskattning inf\u00f6rs, skattetrycket \u00f6kar kraftigt",
    },
    {
        "year": 1976,
        "label": "Pomperipossa (102% marginalskatt)",
        "description": "Astrid Lindgren publicerar Pomperipossa i Monismanien. "
        "H\u00f6gsta marginalskatten \u00f6verstiger 100% f\u00f6r h\u00f6ginkomsttagare.",
    },
    {
        "year": 1983,
        "label": "Marginalskattereform",
        "description": "Marginalskatterna s\u00e4nks fr\u00e5n 87% till 80% (h\u00f6gsta skiktet)",
    },
    {
        "year": 1991,
        "label": "\u00c5rhundradets skattereform",
        "description": "Marginalskatt max 50%, bolagsskatt 30%, breddad bas. "
        "Skattekvoten sjunker fr\u00e5n ~53% till ~47% av BNP.",
    },
    {
        "year": 2007,
        "label": "Jobbskatteavdraget inf\u00f6rs",
        "description": "F\u00f6rsta steget av jobbskatteavdrag. S\u00e4nkt skatt p\u00e5 arbete.",
    },
    {
        "year": 2020,
        "label": "V\u00e4rnskatten avskaffas",
        "description": "H\u00f6gsta marginalskattesatsen s\u00e4nks fr\u00e5n ~57% till ~52%.",
    },
]


@dataclass
class LafferPoint:
    """A single year's observation for Laffer curve plotting."""

    year: int
    tax_quota_pct: float  # Total tax as % of GDP (X-axis)
    gdp_msek: float  # GDP in MSEK (for context)
    total_tax_msek: float  # Total tax revenue in MSEK
    real_gdp_growth_pct: float | None  # Real GDP growth next year (if available)
    decade: str  # e.g. "1950s", "1960s" for color coding
    is_reform_year: bool
    reform_label: str | None


async def build_laffer_curve(
    scb: SCBClient,
    from_year: int = 1950,
    to_year: int = 2025,
) -> list[LafferPoint]:
    """Build Laffer curve dataset from SCB tax quota data.

    Returns a list of LafferPoint objects ready for visualization.
    Each point represents one year with tax quota (X) and supporting data.
    """
    raw = await scb.get_laffer_data(from_year=from_year, to_year=to_year)

    reform_years = {r["year"]: r["label"] for r in TAX_REFORMS}

    points: list[LafferPoint] = []
    for i, row in enumerate(raw):
        year = row["year"]
        tax_pct = row["tax_share_pct"]
        gdp = row["gdp_msek"]
        tax = row["total_tax_msek"]

        if tax_pct is None or gdp is None:
            continue

        # Calculate real GDP growth (next year vs this year, nominal approximation)
        real_growth: float | None = None
        if i + 1 < len(raw) and raw[i + 1]["gdp_msek"] is not None:
            next_gdp = raw[i + 1]["gdp_msek"]
            real_growth = round((next_gdp - gdp) / gdp * 100, 2)

        decade = f"{(year // 10) * 10}s"

        points.append(
            LafferPoint(
                year=year,
                tax_quota_pct=tax_pct,
                gdp_msek=gdp,
                total_tax_msek=tax or 0.0,
                real_gdp_growth_pct=real_growth,
                decade=decade,
                is_reform_year=year in reform_years,
                reform_label=reform_years.get(year),
            )
        )

    return points


def laffer_to_chart_data(points: list[LafferPoint]) -> dict[str, Any]:
    """Convert LafferPoints to a format suitable for Chart.js or D3.

    Returns a dict with:
    - datasets: grouped by decade for color coding
    - annotations: reform years with labels
    - axis_labels: for X and Y
    - summary: key statistics
    """
    # Group by decade
    decades: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        if p.decade not in decades:
            decades[p.decade] = []
        decades[p.decade].append({
            "x": p.tax_quota_pct,
            "y": p.tax_quota_pct,  # Y = same as X for basic plot (revenue/GDP)
            "year": p.year,
            "gdp_msek": p.gdp_msek,
            "tax_msek": p.total_tax_msek,
        })

    # Annotations for reform years
    annotations = [
        {
            "year": p.year,
            "x": p.tax_quota_pct,
            "label": p.reform_label,
        }
        for p in points
        if p.is_reform_year
    ]

    # Key stats
    tax_quotas = [p.tax_quota_pct for p in points if p.tax_quota_pct is not None]
    peak_year = max(points, key=lambda p: p.tax_quota_pct)
    current = points[-1] if points else None

    return {
        "datasets": decades,
        "annotations": annotations,
        "axis_labels": {
            "x": "Total skattekvot (% av BNP)",
            "y": "Skatteint\u00e4kter (% av BNP)",
        },
        "summary": {
            "min_quota_pct": min(tax_quotas) if tax_quotas else None,
            "max_quota_pct": max(tax_quotas) if tax_quotas else None,
            "peak_year": peak_year.year if peak_year else None,
            "peak_quota_pct": peak_year.tax_quota_pct if peak_year else None,
            "current_year": current.year if current else None,
            "current_quota_pct": current.tax_quota_pct if current else None,
            "years_covered": len(points),
        },
    }


def laffer_timeseries(points: list[LafferPoint]) -> list[dict[str, Any]]:
    """Convert to timeseries format for line chart visualization.

    Useful for showing how tax quota evolved over time with
    reform annotations as vertical markers.
    """
    return [
        {
            "year": p.year,
            "tax_quota_pct": p.tax_quota_pct,
            "gdp_msek": p.gdp_msek,
            "total_tax_msek": p.total_tax_msek,
            "growth_pct": p.real_gdp_growth_pct,
            "reform": p.reform_label,
        }
        for p in points
    ]
