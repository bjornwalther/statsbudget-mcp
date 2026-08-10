"""Tests for Laffer curve module."""

import pytest

from statsbudget_mcp.laffer import (
    TAX_REFORMS,
    LafferPoint,
    laffer_timeseries,
    laffer_to_chart_data,
)


def _make_points() -> list[LafferPoint]:
    """Create sample LafferPoints for testing."""
    return [
        LafferPoint(
            year=1975, tax_quota_pct=44.2, gdp_msek=250000,
            total_tax_msek=110500, real_gdp_growth_pct=2.1,
            decade="1970s", is_reform_year=False, reform_label=None,
        ),
        LafferPoint(
            year=1976, tax_quota_pct=47.8, gdp_msek=280000,
            total_tax_msek=133840, real_gdp_growth_pct=-1.2,
            decade="1970s", is_reform_year=True,
            reform_label="Pomperipossa (102% marginalskatt)",
        ),
        LafferPoint(
            year=1990, tax_quota_pct=52.3, gdp_msek=1450000,
            total_tax_msek=758350, real_gdp_growth_pct=-1.1,
            decade="1990s", is_reform_year=False, reform_label=None,
        ),
        LafferPoint(
            year=1991, tax_quota_pct=49.1, gdp_msek=1530000,
            total_tax_msek=751230, real_gdp_growth_pct=-1.0,
            decade="1990s", is_reform_year=True,
            reform_label="\u00c5rhundradets skattereform",
        ),
        LafferPoint(
            year=2024, tax_quota_pct=42.5, gdp_msek=6400000,
            total_tax_msek=2720000, real_gdp_growth_pct=1.5,
            decade="2020s", is_reform_year=False, reform_label=None,
        ),
    ]


class TestLafferPoint:
    def test_dataclass_fields(self):
        p = _make_points()[0]
        assert p.year == 1975
        assert p.tax_quota_pct == 44.2
        assert p.decade == "1970s"
        assert p.is_reform_year is False

    def test_reform_year_detection(self):
        points = _make_points()
        reforms = [p for p in points if p.is_reform_year]
        assert len(reforms) == 2
        assert reforms[0].year == 1976
        assert "Pomperipossa" in reforms[0].reform_label


class TestChartData:
    def test_datasets_grouped_by_decade(self):
        points = _make_points()
        chart = laffer_to_chart_data(points)
        assert "1970s" in chart["datasets"]
        assert "1990s" in chart["datasets"]
        assert "2020s" in chart["datasets"]

    def test_annotations_contain_reforms(self):
        points = _make_points()
        chart = laffer_to_chart_data(points)
        annotations = chart["annotations"]
        assert len(annotations) == 2
        assert annotations[0]["year"] == 1976
        assert annotations[1]["year"] == 1991

    def test_summary_statistics(self):
        points = _make_points()
        chart = laffer_to_chart_data(points)
        summary = chart["summary"]
        assert summary["peak_quota_pct"] == 52.3
        assert summary["peak_year"] == 1990
        assert summary["current_year"] == 2024
        assert summary["years_covered"] == 5

    def test_axis_labels_present(self):
        points = _make_points()
        chart = laffer_to_chart_data(points)
        assert "x" in chart["axis_labels"]
        assert "y" in chart["axis_labels"]


class TestTimeseries:
    def test_output_format(self):
        points = _make_points()
        ts = laffer_timeseries(points)
        assert len(ts) == 5
        assert ts[0]["year"] == 1975
        assert ts[0]["tax_quota_pct"] == 44.2
        assert ts[0]["reform"] is None

    def test_reform_annotations_in_timeseries(self):
        points = _make_points()
        ts = laffer_timeseries(points)
        reform_entries = [t for t in ts if t["reform"] is not None]
        assert len(reform_entries) == 2


class TestTaxReforms:
    def test_pomperipossa_included(self):
        years = [r["year"] for r in TAX_REFORMS]
        assert 1976 in years

    def test_1991_reform_included(self):
        years = [r["year"] for r in TAX_REFORMS]
        assert 1991 in years

    def test_all_reforms_have_required_fields(self):
        for reform in TAX_REFORMS:
            assert "year" in reform
            assert "label" in reform
            assert "description" in reform
            assert isinstance(reform["year"], int)


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests hitting real SCB API."""

    pytestmark = pytest.mark.integration

    async def test_build_laffer_curve(self):
        from statsbudget_mcp.laffer import build_laffer_curve

        async with SCBClient() as scb:
            points = await build_laffer_curve(scb, from_year=2000, to_year=2005)
            assert len(points) >= 5
            assert all(isinstance(p, LafferPoint) for p in points)
            assert all(p.tax_quota_pct > 0 for p in points)
            assert all(20 < p.tax_quota_pct < 60 for p in points)


# Need import for integration test
from statsbudget_mcp.scb_client import SCBClient  # noqa: E402
