"""Tests for SQLite cache module."""

import os
import tempfile
from datetime import datetime, timezone

from statsbudget_mcp.cache import BudgetCache


class TestCacheCreation:
    def test_creates_db_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            cache = BudgetCache(db_path=path)
            assert os.path.exists(path)
            cache.close()

    def test_empty_cache_not_populated(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            assert not cache.is_populated()
            cache.close()

    def test_needs_refresh_when_empty(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            assert cache.needs_refresh()
            cache.close()


class TestMeta:
    def test_set_and_get_meta(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            cache.set_meta("test_key", "test_value")
            assert cache.get_meta("test_key") == "test_value"
            cache.close()

    def test_get_missing_meta_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            assert cache.get_meta("nonexistent") is None
            cache.close()

    def test_cache_age_none_when_never_synced(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            assert cache.cache_age_hours() is None
            cache.close()

    def test_cache_age_after_sync(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cache.set_meta("last_sync_utc", now)
            age = cache.cache_age_hours()
            assert age is not None and age < 0.01
            cache.close()


class TestExpenditure:
    ROWS = [
        {"expenditure_area_id": "01", "expenditure_area_name": "Rikets styrelse",
         "appropriation_id": "0101001", "appropriation_name": "Hovet",
         "year": 2024, "budget_msek": 160.0, "amendment_budgets_msek": None,
         "outcome_msek": 158.0, "opening_balance_msek": 0.5, "closing_balance_msek": 3.0},
        {"expenditure_area_id": "06", "expenditure_area_name": "Forsvar",
         "appropriation_id": "0601001", "appropriation_name": "Forband",
         "year": 2024, "budget_msek": 85000.0, "amendment_budgets_msek": 500.0,
         "outcome_msek": 84500.0, "opening_balance_msek": 1200.0, "closing_balance_msek": 1200.0},
        {"expenditure_area_id": "01", "expenditure_area_name": "Rikets styrelse",
         "appropriation_id": "0101001", "appropriation_name": "Hovet",
         "year": 2023, "budget_msek": 150.0, "amendment_budgets_msek": None,
         "outcome_msek": 148.0, "opening_balance_msek": None, "closing_balance_msek": None},
    ]

    def test_store_and_load_all(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            count = cache.store_expenditure(self.ROWS)
            assert count == 3
            loaded = cache.load_expenditure()
            assert len(loaded) == 3
            cache.close()

    def test_load_by_year(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            cache.store_expenditure(self.ROWS)
            loaded = cache.load_expenditure(year=2024)
            assert len(loaded) == 2
            assert all(r["year"] == 2024 for r in loaded)
            cache.close()

    def test_is_populated_after_store(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            cache.store_expenditure(self.ROWS)
            assert cache.is_populated()
            cache.close()

    def test_store_replaces_existing(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            cache.store_expenditure(self.ROWS)
            cache.store_expenditure(self.ROWS[:1])
            assert len(cache.load_expenditure()) == 1
            cache.close()


class TestIncome:
    ROWS = [
        {"income_type": "1000", "income_type_name": "Skatter",
         "income_main_group": "1100", "income_main_group_name": "Arbete",
         "income_title": "1111", "income_title_name": "Statlig",
         "year": 2024, "budget_msek": 51000.0, "outcome_msek": 50000.0},
    ]

    def test_store_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            count = cache.store_income(self.ROWS)
            assert count == 1
            loaded = cache.load_income()
            assert len(loaded) == 1
            assert loaded[0]["income_type"] == "1000"
            assert loaded[0]["outcome_msek"] == 50000.0
            cache.close()


class TestSCBRevenue:
    ROWS = [
        {"tax_type_code": "190", "tax_type_label": "Totala skatteintakter",
         "year": 2023, "amount_msek": 2847123.0},
    ]

    def test_store_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            count = cache.store_scb_revenue(self.ROWS)
            assert count == 1
            loaded = cache.load_scb_revenue(year=2023)
            assert len(loaded) == 1
            cache.close()


class TestSCBQuota:
    ROWS = [
        {"tax_type_code": "102", "tax_type_label": "Totala skatter",
         "year": 2020, "amount_msek": 2200000.0, "share_of_gdp": 42.8},
    ]

    def test_store_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            count = cache.store_scb_quota(self.ROWS)
            assert count == 1
            loaded = cache.load_scb_quota()
            assert len(loaded) == 1
            assert loaded[0]["share_of_gdp"] == 42.8
            cache.close()


class TestStats:
    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as td:
            cache = BudgetCache(db_path=os.path.join(td, "test.db"))
            cache.store_expenditure([
                {"expenditure_area_id": "01", "expenditure_area_name": "X",
                 "appropriation_id": "Y", "appropriation_name": "Z",
                 "year": 2024, "budget_msek": 100.0, "outcome_msek": 99.0}
            ])
            stats = cache.get_stats()
            assert stats["row_counts"]["expenditure"] == 1
            assert stats["total_rows"] == 1
            assert 2024 in stats["years_covered"]
            assert stats["needs_refresh"] is True
            cache.close()


class TestPersistence:
    def test_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.db")
            cache = BudgetCache(db_path=path)
            cache.store_expenditure([
                {"expenditure_area_id": "01", "expenditure_area_name": "X",
                 "appropriation_id": "Y", "appropriation_name": "Z",
                 "year": 2024, "budget_msek": 100.0, "outcome_msek": 99.0}
            ])
            cache.set_meta("last_sync_utc", "2026-09-02T20:00:00+00:00")
            cache.close()

            cache2 = BudgetCache(db_path=path)
            assert cache2.is_populated()
            assert len(cache2.load_expenditure()) == 1
            assert cache2.get_meta("last_sync_utc") == "2026-09-02T20:00:00+00:00"
            cache2.close()
