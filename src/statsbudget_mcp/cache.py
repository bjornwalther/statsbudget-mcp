"""SQLite cache for statsbudget-mcp.

Persists parsed budget data locally so the server starts instantly
without re-downloading and re-parsing CSV files from Statskontoret
or re-querying SCB on every startup.

Schema:
- expenditure: parsed ExpenditureRow data
- income: parsed IncomeRow data
- scb_revenue: tax revenue snapshots
- scb_quota: tax quota snapshots
- meta: sync metadata (last sync time, source dates)

The cache is stored in ~/.statsbudget-cache/statsbudget.db by default.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS expenditure (
    expenditure_area_id TEXT NOT NULL,
    expenditure_area_name TEXT NOT NULL,
    appropriation_id TEXT NOT NULL,
    appropriation_name TEXT NOT NULL,
    year INTEGER NOT NULL,
    budget_msek REAL,
    amendment_budgets_msek REAL,
    outcome_msek REAL,
    opening_balance_msek REAL,
    closing_balance_msek REAL
);

CREATE TABLE IF NOT EXISTS income (
    income_type TEXT NOT NULL,
    income_type_name TEXT NOT NULL,
    income_main_group TEXT NOT NULL,
    income_main_group_name TEXT NOT NULL,
    income_title TEXT NOT NULL,
    income_title_name TEXT NOT NULL,
    year INTEGER NOT NULL,
    budget_msek REAL,
    outcome_msek REAL
);

CREATE TABLE IF NOT EXISTS scb_revenue (
    tax_type_code TEXT NOT NULL,
    tax_type_label TEXT NOT NULL,
    year INTEGER NOT NULL,
    amount_msek REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scb_quota (
    tax_type_code TEXT NOT NULL,
    tax_type_label TEXT NOT NULL,
    year INTEGER NOT NULL,
    amount_msek REAL,
    share_of_gdp REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_expenditure_year ON expenditure(year);
CREATE INDEX IF NOT EXISTS idx_income_year ON income(year);
CREATE INDEX IF NOT EXISTS idx_scb_revenue_year ON scb_revenue(year);
CREATE INDEX IF NOT EXISTS idx_scb_quota_year ON scb_quota(year);
"""


class BudgetCache:
    """SQLite-backed cache for budget data.

    Usage:
        cache = BudgetCache()
        cache.store_expenditure(rows)
        rows = cache.load_expenditure(year=2024)
        cache.close()
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            cache_dir = Path.home() / ".statsbudget-cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "statsbudget.db"
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def is_populated(self) -> bool:
        """Check if cache has any data."""
        cur = self._conn.execute("SELECT COUNT(*) FROM expenditure")
        return cur.fetchone()[0] > 0

    def get_meta(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def cache_age_hours(self) -> float | None:
        """Hours since last successful sync, or None if never synced."""
        last = self.get_meta("last_sync_utc")
        if not last:
            return None
        try:
            synced = datetime.fromisoformat(last)
            delta = datetime.now(timezone.utc) - synced
            return delta.total_seconds() / 3600
        except (ValueError, TypeError):
            return None

    def needs_refresh(self, max_age_hours: float = 24 * 7) -> bool:
        """Check if cache is stale (default: older than 1 week)."""
        age = self.cache_age_hours()
        if age is None:
            return True
        return age > max_age_hours

    # -- Expenditure --

    def store_expenditure(self, rows: list[dict[str, Any]]) -> int:
        """Store expenditure rows, replacing existing data."""
        self._conn.execute("DELETE FROM expenditure")
        self._conn.executemany(
            "INSERT INTO expenditure VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["expenditure_area_id"], r["expenditure_area_name"],
                    r["appropriation_id"], r["appropriation_name"],
                    r["year"], r.get("budget_msek"), r.get("amendment_budgets_msek"),
                    r.get("outcome_msek"), r.get("opening_balance_msek"),
                    r.get("closing_balance_msek"),
                )
                for r in rows
            ],
        )
        self._conn.commit()
        return len(rows)

    def load_expenditure(self, year: int | None = None) -> list[dict[str, Any]]:
        if year is not None:
            cur = self._conn.execute("SELECT * FROM expenditure WHERE year = ?", (year,))
        else:
            cur = self._conn.execute("SELECT * FROM expenditure")
        return [dict(row) for row in cur.fetchall()]

    # -- Income --

    def store_income(self, rows: list[dict[str, Any]]) -> int:
        self._conn.execute("DELETE FROM income")
        self._conn.executemany(
            "INSERT INTO income VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["income_type"], r["income_type_name"],
                    r["income_main_group"], r["income_main_group_name"],
                    r["income_title"], r["income_title_name"],
                    r["year"], r.get("budget_msek"), r.get("outcome_msek"),
                )
                for r in rows
            ],
        )
        self._conn.commit()
        return len(rows)

    def load_income(self, year: int | None = None) -> list[dict[str, Any]]:
        if year is not None:
            cur = self._conn.execute("SELECT * FROM income WHERE year = ?", (year,))
        else:
            cur = self._conn.execute("SELECT * FROM income")
        return [dict(row) for row in cur.fetchall()]

    # -- SCB Revenue --

    def store_scb_revenue(self, rows: list[dict[str, Any]]) -> int:
        self._conn.execute("DELETE FROM scb_revenue")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.executemany(
            "INSERT INTO scb_revenue VALUES (?,?,?,?,?)",
            [(r["tax_type_code"], r["tax_type_label"], r["year"], r.get("amount_msek"), now) for r in rows],
        )
        self._conn.commit()
        return len(rows)

    def load_scb_revenue(self, year: int | None = None) -> list[dict[str, Any]]:
        if year is not None:
            cur = self._conn.execute("SELECT * FROM scb_revenue WHERE year = ?", (year,))
        else:
            cur = self._conn.execute("SELECT * FROM scb_revenue")
        return [dict(row) for row in cur.fetchall()]

    # -- SCB Quota --

    def store_scb_quota(self, rows: list[dict[str, Any]]) -> int:
        self._conn.execute("DELETE FROM scb_quota")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.executemany(
            "INSERT INTO scb_quota VALUES (?,?,?,?,?,?)",
            [(r["tax_type_code"], r["tax_type_label"], r["year"], r.get("amount_msek"), r.get("share_of_gdp"), now) for r in rows],
        )
        self._conn.commit()
        return len(rows)

    def load_scb_quota(self, year: int | None = None) -> list[dict[str, Any]]:
        if year is not None:
            cur = self._conn.execute("SELECT * FROM scb_quota WHERE year = ?", (year,))
        else:
            cur = self._conn.execute("SELECT * FROM scb_quota")
        return [dict(row) for row in cur.fetchall()]

    # -- Summary --

    def get_stats(self) -> dict[str, Any]:
        """Cache statistics for diagnostics."""
        counts = {}
        for table in ("expenditure", "income", "scb_revenue", "scb_quota"):
            cur = self._conn.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cur.fetchone()[0]

        years = set()
        for table in ("expenditure", "income"):
            cur = self._conn.execute(f"SELECT DISTINCT year FROM {table}")
            years.update(row[0] for row in cur.fetchall())

        return {
            "db_path": str(self._db_path),
            "row_counts": counts,
            "total_rows": sum(counts.values()),
            "years_covered": sorted(years),
            "last_sync": self.get_meta("last_sync_utc"),
            "cache_age_hours": self.cache_age_hours(),
            "needs_refresh": self.needs_refresh(),
        }
