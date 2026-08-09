"""Tests for Statskontoret CSV client."""

import pytest

from statsbudget_mcp.statskontoret import (
    AreaSummary,
    BudgetOverview,
    ExpenditureRow,
    IncomeRow,
    StatskontoretClient,
    _parse_swedish_decimal,
)


class TestSwedishDecimalParsing:
    def test_normal_value(self):
        assert _parse_swedish_decimal("136,996") == pytest.approx(136.996)

    def test_negative_value(self):
        assert _parse_swedish_decimal("-40,62704977") == pytest.approx(-40.62704977)

    def test_large_value(self):
        assert _parse_swedish_decimal("1428000,12345678") == pytest.approx(1428000.12345678)

    def test_empty_string(self):
        assert _parse_swedish_decimal("") is None

    def test_double_dot(self):
        assert _parse_swedish_decimal("..") is None

    def test_dash(self):
        assert _parse_swedish_decimal("-") is None

    def test_whitespace_handling(self):
        assert _parse_swedish_decimal(" 1 234,56 ") == pytest.approx(1234.56)

    def test_non_breaking_space(self):
        assert _parse_swedish_decimal("1\xa0234,56") == pytest.approx(1234.56)


class TestExpenditureCsvParsing:
    SAMPLE_CSV = (
        "Utgiftsomr\u00e5de;Utgiftsomr\u00e5desnamn;Anslag;Anslagsnamn;"
        "Utgiftsomr\u00e5de utfalls\u00e5r;Utgiftsomr\u00e5desnamn utfalls\u00e5r;"
        "Anslag utfalls\u00e5r;Anslagsnamn utfalls\u00e5r;"
        "\u00c5r;Ing\u00e5ende \u00f6verf\u00f6ringsbelopp;Statens budget;"
        "\u00c4ndringsbudgetar;Indragningar;"
        "Utnyttjad del av medgivet\u00f6verskridande;Utfall;"
        "Anslagskredit;Utg\u00e5ende \u00f6verf\u00f6ringsbelopp\n"
        "01;Rikets styrelse;0101001;Kungliga hov- och slottsstaten;"
        "01;Rikets styrelse;0101001;Kungliga hov- och slottsstaten;"
        "2024;0,5;160,996;0;0;0;158,244;4,83;3,252\n"
        "06;F\u00f6rsvar och samh\u00e4llets krisberedskap;0601001;F\u00f6rbandsverksamhet;"
        "06;F\u00f6rsvar och samh\u00e4llets krisberedskap;0601001;F\u00f6rbandsverksamhet;"
        "2024;1200,0;85000,0;500,0;0;0;84500,0;2550,0;1200,0\n"
    )

    def test_parse_expenditure_csv(self):
        client = StatskontoretClient()
        rows = client._parse_expenditure_csv(self.SAMPLE_CSV)
        assert len(rows) == 2
        assert isinstance(rows[0], ExpenditureRow)

    def test_first_row_values(self):
        client = StatskontoretClient()
        rows = client._parse_expenditure_csv(self.SAMPLE_CSV)
        row = rows[0]
        assert row.expenditure_area_id == "01"
        assert row.expenditure_area_name == "Rikets styrelse"
        assert row.appropriation_id == "0101001"
        assert row.year == 2024
        assert row.budget_msek == pytest.approx(160.996)
        assert row.outcome_msek == pytest.approx(158.244)

    def test_defence_row(self):
        client = StatskontoretClient()
        rows = client._parse_expenditure_csv(self.SAMPLE_CSV)
        row = rows[1]
        assert row.expenditure_area_id == "06"
        assert row.budget_msek == pytest.approx(85000.0)
        assert row.outcome_msek == pytest.approx(84500.0)


class TestIncomeCsvParsing:
    SAMPLE_CSV = (
        "Inkomsttyp;Inkomsttypsnamn;Inkomsthuvudgrupp;Inkomsthuvudgruppsnamn;"
        "Inkomsttitelgrupp;Inkomsttitelgruppsnamn;Inkomsttitel;Inkomsttitelsnamn;"
        "Inkomsttyp utfalls\u00e5r;Inkomsttypsnamn utfalls\u00e5r;"
        "Inkomsthuvudgrupp utfalls\u00e5r;Inkomsthuvudgruppsnamn utfalls\u00e5r;"
        "Inkomsttitelgrupp utfalls\u00e5r;Inkomsttitelgruppsnamn utfalls\u00e5r;"
        "Inkomsttitel utfalls\u00e5r;Inkomsttitelsnamn utfalls\u00e5r;"
        "\u00c5r;Statens budget;Utfall\n"
        "1000;Statens skatteinkomster;1100;Direkta skatter p\u00e5 arbete;"
        "1110;Inkomstskatter;1111;Statlig inkomstskatt;"
        "1000;Statens skatteinkomster;1100;Direkta skatter p\u00e5 arbete;"
        "1110;Inkomstskatter;1111;Statlig inkomstskatt;"
        "2024;51380,859539;50805,94943\n"
    )

    def test_parse_income_csv(self):
        client = StatskontoretClient()
        rows = client._parse_income_csv(self.SAMPLE_CSV)
        assert len(rows) == 1
        assert isinstance(rows[0], IncomeRow)

    def test_income_row_values(self):
        client = StatskontoretClient()
        rows = client._parse_income_csv(self.SAMPLE_CSV)
        row = rows[0]
        assert row.income_type == "1000"
        assert row.income_type_name == "Statens skatteinkomster"
        assert row.income_title == "1111"
        assert row.year == 2024
        assert row.budget_msek == pytest.approx(51380.859539)
        assert row.outcome_msek == pytest.approx(50805.94943)


class TestBudgetOverview:
    def test_overview_aggregation(self):
        client = StatskontoretClient()
        client._expenditure_data = [
            ExpenditureRow("01", "Rikets styrelse", "0101001", "Hovet", 2024, 160.0, None, 158.0, None, None),
            ExpenditureRow("01", "Rikets styrelse", "0101002", "Riksdagen", 2024, 2000.0, None, 1950.0, None, None),
            ExpenditureRow("06", "F\u00f6rsvar", "0601001", "F\u00f6rband", 2024, 85000.0, None, 84500.0, None, None),
        ]
        client._income_data = [
            IncomeRow("1000", "Skatter", "1100", "Arbete", "1111", "Statlig", 2024, 51000.0, 50000.0),
            IncomeRow("2000", "Inkomster", "2100", "\u00d6vrigt", "2111", "Div", 2024, 40000.0, 38000.0),
        ]

        overview = client.get_budget_overview(2024)
        assert isinstance(overview, BudgetOverview)
        assert overview.year == 2024
        assert overview.total_expenditure_msek == pytest.approx(158.0 + 1950.0 + 84500.0)
        assert overview.total_income_msek == pytest.approx(50000.0 + 38000.0)
        assert len(overview.areas) == 2
        assert overview.areas[0].area_id == "01"
        assert overview.areas[0].outcome_msek == pytest.approx(158.0 + 1950.0)


class TestBudgetComparison:
    def test_compare_two_years(self):
        client = StatskontoretClient()
        client._expenditure_data = [
            ExpenditureRow("01", "Rikets styrelse", "0101001", "X", 2023, 100.0, None, 95.0, None, None),
            ExpenditureRow("01", "Rikets styrelse", "0101001", "X", 2024, 110.0, None, 108.0, None, None),
        ]

        result = client.compare_budgets(2023, 2024)
        assert len(result) == 1
        assert result[0]["area_id"] == "01"
        assert result[0]["delta_msek"] == pytest.approx(13.0)
        assert result[0]["delta_pct"] == pytest.approx(13.68, rel=0.01)


class TestAvailableYears:
    def test_returns_sorted_years(self):
        client = StatskontoretClient()
        client._expenditure_data = [
            ExpenditureRow("01", "X", "Y", "Z", 2022, None, None, None, None, None),
            ExpenditureRow("01", "X", "Y", "Z", 2024, None, None, None, None, None),
        ]
        client._income_data = [
            IncomeRow("1000", "X", "1100", "Y", "1111", "Z", 2023, None, None),
        ]
        assert client.get_available_years() == [2022, 2023, 2024]
