"""Statskontoret open data client for statsbudget-mcp.

Downloads and parses annual budget outcome data (arsutfall) from
Statskontoret's open data pages. Data is delivered as semicolon-separated
CSV files inside ZIP archives.

File format:
- Encoding: UTF-8
- Separator: semicolon (;)
- Decimal: comma (,)
- Amounts: millions SEK with up to 8 decimals
- First row: column headers

Data covers 2006-2025 (expenditure) and includes both budget and outcome.

Publication schedule (Statskontoret publishes new data at these intervals):
- Expenditure (definitiv): ~March each year (covers previous year)
- Income (prelimin\u00e4r 1): ~March (ESV estimate)
- Income (prelimin\u00e4r 2): ~June (Government estimate in \u00c5rsredovisning f\u00f6r staten)
- Income (prelimin\u00e4r 3): ~March year+2 (ESV estimate)
- Income (definitiv): ~June year+2 (final)

In practice, syncing once in March and once in June covers all updates.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://www.statskontoret.se"
ARSUTFALL_PAGE = "/analys-och-statistik/oppna-data/arsutfall/"

HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
UPDATED_RE = re.compile(r"Senast uppdaterad\s+(\d{4}-\d{2}-\d{2})")


@dataclass
class DataSourceMeta:
    """Metadata about a synced data source for UI display."""

    source: str
    description: str
    publication_cadence: str
    last_synced_at: str | None = None
    source_last_updated: str | None = None
    files_downloaded: list[str] = field(default_factory=list)
    years_covered: list[int] = field(default_factory=list)


@dataclass
class SyncStatus:
    """Overall sync status for the Statskontoret data."""

    last_sync: str | None = None
    next_expected_update: str | None = None
    sources: list[DataSourceMeta] = field(default_factory=list)


@dataclass
class ExpenditureRow:
    """A single appropriation outcome row."""

    expenditure_area_id: str
    expenditure_area_name: str
    appropriation_id: str
    appropriation_name: str
    year: int
    budget_msek: float | None
    amendment_budgets_msek: float | None
    outcome_msek: float | None
    opening_balance_msek: float | None
    closing_balance_msek: float | None


@dataclass
class IncomeRow:
    """A single income title outcome row."""

    income_type: str
    income_type_name: str
    income_main_group: str
    income_main_group_name: str
    income_title: str
    income_title_name: str
    year: int
    budget_msek: float | None
    outcome_msek: float | None


@dataclass
class BudgetOverview:
    """Aggregated budget overview for a given year."""

    year: int
    total_expenditure_msek: float
    total_income_msek: float
    balance_msek: float
    areas: list[AreaSummary] = field(default_factory=list)


@dataclass
class AreaSummary:
    """Summary for one expenditure area."""

    area_id: str
    area_name: str
    budget_msek: float
    outcome_msek: float
    delta_msek: float


# Publication schedule constants for UI
PUBLICATION_SCHEDULE = {
    "expenditure_definitive": {
        "description": "Definitiva utgifter f\u00f6r f\u00f6reg\u00e5ende \u00e5r",
        "typical_month": 3,
        "cadence": "Annually in March",
    },
    "income_preliminary_1": {
        "description": "Prelimin\u00e4r 1: ESV:s ber\u00e4kning (skattetyp 1000/7000/8000 prognos)",
        "typical_month": 3,
        "cadence": "Annually in March",
    },
    "income_preliminary_2": {
        "description": "Prelimin\u00e4r 2: Regeringens ber\u00e4kning i \u00c5rsredovisning f\u00f6r staten",
        "typical_month": 6,
        "cadence": "Annually in June",
    },
    "income_preliminary_3": {
        "description": "Prelimin\u00e4r 3: ESV:s uppdaterade ber\u00e4kning (\u00e5r t+1)",
        "typical_month": 3,
        "cadence": "Annually in March (year + 1)",
    },
    "income_definitive": {
        "description": "Definitiva inkomster (alla inkomsttyper slutliga)",
        "typical_month": 6,
        "cadence": "Annually in June (year + 2)",
    },
}


def _parse_swedish_decimal(value: str) -> float | None:
    """Parse Swedish number format (comma as decimal separator)."""
    value = value.strip()
    if not value or value in ("..", ".", "-"):
        return None
    cleaned = value.replace("\xa0", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int_safe(value: str) -> int:
    """Parse year or similar integer, defaulting to 0."""
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return 0


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_expected_update() -> str:
    """Estimate next Statskontoret data release."""
    now = datetime.now(timezone.utc)
    year = now.year
    # March and June are the update months
    if now.month < 3:
        return f"{year}-03-15"
    elif now.month < 6:
        return f"{year}-06-15"
    else:
        return f"{year + 1}-03-15"


class StatskontoretClient:
    """Async client for Statskontoret budget outcome data.

    Supports two modes:
    1. Online: scrape download links from the Statskontoret page and fetch ZIPs
    2. Offline: load from a local data directory with pre-downloaded CSVs

    Usage:
        async with StatskontoretClient() as sk:
            await sk.sync(year=2024)
            overview = sk.get_budget_overview(2024)
            status = sk.get_sync_status()
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._data_dir = Path(data_dir) if data_dir else Path.cwd() / ".statsbudget-cache"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._expenditure_data: list[ExpenditureRow] = []
        self._income_data: list[IncomeRow] = []
        self._sync_meta: SyncStatus = SyncStatus()
        self._meta_path = self._data_dir / "sync_meta.json"
        self._load_meta()

    def _load_meta(self) -> None:
        """Load sync metadata from disk if available."""
        if self._meta_path.exists():
            try:
                raw = json.loads(self._meta_path.read_text(encoding="utf-8"))
                self._sync_meta = SyncStatus(
                    last_sync=raw.get("last_sync"),
                    next_expected_update=raw.get("next_expected_update"),
                    sources=[
                        DataSourceMeta(**s) for s in raw.get("sources", [])
                    ],
                )
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_meta(self) -> None:
        """Persist sync metadata to disk."""
        data = {
            "last_sync": self._sync_meta.last_sync,
            "next_expected_update": self._sync_meta.next_expected_update,
            "sources": [
                {
                    "source": s.source,
                    "description": s.description,
                    "publication_cadence": s.publication_cadence,
                    "last_synced_at": s.last_synced_at,
                    "source_last_updated": s.source_last_updated,
                    "files_downloaded": s.files_downloaded,
                    "years_covered": s.years_covered,
                }
                for s in self._sync_meta.sources
            ],
        }
        self._meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "StatskontoretClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def discover_download_links(
        self, year: int | None = None
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Scrape the arsutfall page for download links.

        Returns:
            Tuple of (links, source_update_dates) where links is a list of
            dicts with 'url', 'text', and 'type' (expenditure/income), and
            source_update_dates is a list of dates found on the page.
        """
        url = f"{BASE_URL}{ARSUTFALL_PAGE}"
        if year:
            url += f"?year={year}"

        resp = await self._client.get(url)
        resp.raise_for_status()
        html = resp.text

        # Extract "Senast uppdaterad" dates from the page
        source_dates = UPDATED_RE.findall(html)

        links: list[dict[str, str]] = []
        for match in HREF_RE.finditer(html):
            href = match.group(1).strip()
            text = TAG_RE.sub("", match.group(2)).strip().lower()

            is_data_file = (
                "getfile" in href.lower()
                or href.endswith(".zip")
                or href.endswith(".xlsx")
                or "filetype=" in href.lower()
            )
            if not is_data_file:
                continue

            file_type = "unknown"
            if "utgift" in text or "expenditure" in text:
                file_type = "expenditure"
            elif "inkomst" in text or "income" in text:
                file_type = "income"

            resolved = href if href.startswith("http") else f"{BASE_URL}{href}"
            links.append({"url": resolved, "text": text, "type": file_type})

        return links, source_dates

    async def download_file(self, url: str, filename: str) -> Path:
        """Download a file to the data directory."""
        resp = await self._client.get(url)
        resp.raise_for_status()
        path = self._data_dir / filename
        path.write_bytes(resp.content)
        return path

    async def sync(self, year: int | None = None) -> SyncStatus:
        """Download and parse latest data from Statskontoret.

        If year is specified, only sync that year's data.
        Returns SyncStatus with metadata about what was fetched.
        """
        links, source_dates = await self.discover_download_links(year=year)
        sync_time = _now_iso()
        latest_source_date = max(source_dates) if source_dates else None
        files_downloaded: list[str] = []

        for link in links:
            url = link["url"]
            file_type = link["type"]
            suffix = "zip" if "zip" in url.lower() or "filetype=zip" in url.lower() else "xlsx"
            filename = f"{file_type}_{year or 'latest'}.{suffix}"

            path = await self.download_file(url, filename)
            files_downloaded.append(filename)

            if suffix == "zip":
                csv_content = self._extract_csv_from_zip(path)
                if csv_content and file_type == "expenditure":
                    self._expenditure_data.extend(self._parse_expenditure_csv(csv_content))
                elif csv_content and file_type == "income":
                    self._income_data.extend(self._parse_income_csv(csv_content))

        # Update sync metadata
        source_meta = DataSourceMeta(
            source="Statskontoret \u00d6ppna Data - \u00c5rsutfall",
            description="Annual budget outcome: expenditure and income for central government",
            publication_cadence="Expenditure: March (annual). Income: March + June (prelim/definitive over 2 years).",
            last_synced_at=sync_time,
            source_last_updated=latest_source_date,
            files_downloaded=files_downloaded,
            years_covered=self.get_available_years(),
        )

        self._sync_meta = SyncStatus(
            last_sync=sync_time,
            next_expected_update=_next_expected_update(),
            sources=[source_meta],
        )
        self._save_meta()

        return self._sync_meta

    def get_sync_status(self) -> SyncStatus:
        """Get current sync status and data freshness info.

        Useful for UI display: shows when data was last fetched,
        when the source was last updated, and when to expect new data.
        """
        return self._sync_meta

    def get_publication_schedule(self) -> dict[str, Any]:
        """Get the publication schedule for Statskontoret budget data.

        Returns a dict describing when new data is typically published,
        useful for displaying freshness indicators in a UI.
        """
        return {
            "schedule": PUBLICATION_SCHEDULE,
            "summary": (
                "Statskontoret publicerar ny budgetdata tv\u00e5 g\u00e5nger per \u00e5r: "
                "utgifter (definitiva) i mars, inkomster (prelimin\u00e4ra) i mars och juni. "
                "Definitiva inkomster publiceras i juni tv\u00e5 \u00e5r efter budget\u00e5ret."
            ),
            "next_expected_update": _next_expected_update(),
            "sync_recommendation": "Sync in March and June each year for complete coverage.",
        }

    def load_from_csv(
        self,
        expenditure_path: str | Path | None = None,
        income_path: str | Path | None = None,
    ) -> None:
        """Load data from local CSV files (already extracted from ZIP)."""
        if expenditure_path:
            content = Path(expenditure_path).read_text(encoding="utf-8")
            self._expenditure_data = self._parse_expenditure_csv(content)
        if income_path:
            content = Path(income_path).read_text(encoding="utf-8")
            self._income_data = self._parse_income_csv(content)

    def _extract_csv_from_zip(self, zip_path: Path) -> str | None:
        """Extract first CSV file from a ZIP archive."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_files:
                    return None
                with zf.open(csv_files[0]) as f:
                    return f.read().decode("utf-8")
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
            return None

    def _parse_expenditure_csv(self, content: str) -> list[ExpenditureRow]:
        """Parse expenditure CSV content into ExpenditureRow objects."""
        rows: list[ExpenditureRow] = []
        reader = csv.DictReader(io.StringIO(content), delimiter=";")

        if not reader.fieldnames:
            return rows

        col_map = self._map_expenditure_columns(reader.fieldnames)

        for record in reader:
            area_id = record.get(col_map["area_id"], "").strip()
            if not area_id or not area_id[0].isdigit():
                continue

            rows.append(
                ExpenditureRow(
                    expenditure_area_id=area_id,
                    expenditure_area_name=record.get(col_map["area_name"], "").strip(),
                    appropriation_id=record.get(col_map["approp_id"], "").strip(),
                    appropriation_name=record.get(col_map["approp_name"], "").strip(),
                    year=_parse_int_safe(record.get(col_map["year"], "0")),
                    budget_msek=_parse_swedish_decimal(record.get(col_map["budget"], "")),
                    amendment_budgets_msek=_parse_swedish_decimal(
                        record.get(col_map["amendments"], "")
                    ),
                    outcome_msek=_parse_swedish_decimal(record.get(col_map["outcome"], "")),
                    opening_balance_msek=_parse_swedish_decimal(
                        record.get(col_map["opening"], "")
                    ),
                    closing_balance_msek=_parse_swedish_decimal(
                        record.get(col_map["closing"], "")
                    ),
                )
            )
        return rows

    def _parse_income_csv(self, content: str) -> list[IncomeRow]:
        """Parse income CSV content into IncomeRow objects."""
        rows: list[IncomeRow] = []
        reader = csv.DictReader(io.StringIO(content), delimiter=";")

        if not reader.fieldnames:
            return rows

        col_map = self._map_income_columns(reader.fieldnames)

        for record in reader:
            income_type = record.get(col_map["income_type"], "").strip()
            if not income_type or not income_type[0].isdigit():
                continue

            rows.append(
                IncomeRow(
                    income_type=income_type,
                    income_type_name=record.get(col_map["income_type_name"], "").strip(),
                    income_main_group=record.get(col_map["main_group"], "").strip(),
                    income_main_group_name=record.get(
                        col_map["main_group_name"], ""
                    ).strip(),
                    income_title=record.get(col_map["title"], "").strip(),
                    income_title_name=record.get(col_map["title_name"], "").strip(),
                    year=_parse_int_safe(record.get(col_map["year"], "0")),
                    budget_msek=_parse_swedish_decimal(record.get(col_map["budget"], "")),
                    outcome_msek=_parse_swedish_decimal(record.get(col_map["outcome"], "")),
                )
            )
        return rows

    @staticmethod
    def _map_expenditure_columns(fieldnames: list[str]) -> dict[str, str]:
        """Map known column name variants to canonical keys."""
        mapping: dict[str, str] = {}
        for name in fieldnames:
            lower = name.lower().strip()
            if lower.startswith("utgiftsomr\u00e5de") and "namn" not in lower:
                if "utfalls" in lower:
                    continue
                mapping.setdefault("area_id", name)
            elif "utgiftsomr\u00e5desnamn" in lower:
                if "utfalls" in lower:
                    continue
                mapping.setdefault("area_name", name)
            elif lower == "anslag":
                mapping.setdefault("approp_id", name)
            elif "anslagsnamn" in lower:
                if "utfalls" in lower:
                    continue
                mapping.setdefault("approp_name", name)
            elif lower in ("\u00e5r", "ar", "year"):
                mapping.setdefault("year", name)
            elif "statens budget" in lower:
                mapping.setdefault("budget", name)
            elif "\u00e4ndringsbudget" in lower or "andringsbudget" in lower:
                mapping.setdefault("amendments", name)
            elif lower == "utfall":
                mapping.setdefault("outcome", name)
            elif "ing\u00e5ende" in lower or "ingaende" in lower:
                mapping.setdefault("opening", name)
            elif "utg\u00e5ende" in lower or "utgaende" in lower:
                mapping.setdefault("closing", name)

        defaults = {
            "area_id": "Utgiftsomr\u00e5de",
            "area_name": "Utgiftsomr\u00e5desnamn",
            "approp_id": "Anslag",
            "approp_name": "Anslagsnamn",
            "year": "\u00c5r",
            "budget": "Statens budget",
            "amendments": "\u00c4ndringsbudgetar",
            "outcome": "Utfall",
            "opening": "Ing\u00e5ende \u00f6verf\u00f6ringsbelopp",
            "closing": "Utg\u00e5ende \u00f6verf\u00f6ringsbelopp",
        }
        for key, default in defaults.items():
            mapping.setdefault(key, default)
        return mapping

    @staticmethod
    def _map_income_columns(fieldnames: list[str]) -> dict[str, str]:
        """Map income CSV column name variants to canonical keys."""
        mapping: dict[str, str] = {}
        for name in fieldnames:
            lower = name.lower().strip()
            if lower == "inkomsttyp" or (
                lower.startswith("inkomsttyp") and "namn" not in lower and "utfalls" not in lower
            ):
                mapping.setdefault("income_type", name)
            elif "inkomsttypsnamn" in lower and "utfalls" not in lower:
                mapping.setdefault("income_type_name", name)
            elif (
                "inkomsthuvudgrupp" in lower and "namn" not in lower and "utfalls" not in lower
            ):
                mapping.setdefault("main_group", name)
            elif "inkomsthuvudgruppsnamn" in lower and "utfalls" not in lower:
                mapping.setdefault("main_group_name", name)
            elif lower == "inkomsttitel" or (
                lower.startswith("inkomsttitel")
                and "namn" not in lower
                and "grupp" not in lower
                and "utfalls" not in lower
            ):
                mapping.setdefault("title", name)
            elif "inkomsttitelsnamn" in lower and "utfalls" not in lower:
                mapping.setdefault("title_name", name)
            elif lower in ("\u00e5r", "ar", "year"):
                mapping.setdefault("year", name)
            elif "statens budget" in lower:
                mapping.setdefault("budget", name)
            elif lower == "utfall":
                mapping.setdefault("outcome", name)

        defaults = {
            "income_type": "Inkomsttyp",
            "income_type_name": "Inkomsttypsnamn",
            "main_group": "Inkomsthuvudgrupp",
            "main_group_name": "Inkomsthuvudgruppsnamn",
            "title": "Inkomsttitel",
            "title_name": "Inkomsttitelsnamn",
            "year": "\u00c5r",
            "budget": "Statens budget",
            "outcome": "Utfall",
        }
        for key, default in defaults.items():
            mapping.setdefault(key, default)
        return mapping

    def get_budget_overview(self, year: int) -> BudgetOverview:
        """Get aggregated budget overview for a specific year."""
        year_exp = [r for r in self._expenditure_data if r.year == year]
        year_inc = [r for r in self._income_data if r.year == year]

        area_map: dict[str, AreaSummary] = {}
        for row in year_exp:
            aid = row.expenditure_area_id
            if aid not in area_map:
                area_map[aid] = AreaSummary(
                    area_id=aid,
                    area_name=row.expenditure_area_name,
                    budget_msek=0.0,
                    outcome_msek=0.0,
                    delta_msek=0.0,
                )
            if row.budget_msek is not None:
                area_map[aid].budget_msek += row.budget_msek
            if row.outcome_msek is not None:
                area_map[aid].outcome_msek += row.outcome_msek

        for area in area_map.values():
            area.delta_msek = area.outcome_msek - area.budget_msek

        total_exp = sum(a.outcome_msek for a in area_map.values())
        total_inc = sum(r.outcome_msek or 0.0 for r in year_inc)

        return BudgetOverview(
            year=year,
            total_expenditure_msek=total_exp,
            total_income_msek=total_inc,
            balance_msek=total_inc - total_exp,
            areas=sorted(area_map.values(), key=lambda a: a.area_id),
        )

    def get_expenditure_area(self, area_id: str, year: int) -> list[ExpenditureRow]:
        """Get all appropriations for a specific expenditure area and year."""
        return [
            r
            for r in self._expenditure_data
            if r.expenditure_area_id == area_id and r.year == year
        ]

    def compare_budgets(self, year_a: int, year_b: int) -> list[dict[str, Any]]:
        """Compare budget outcomes between two years.

        Returns per-area comparison with absolute and percentage deltas.
        """
        overview_a = self.get_budget_overview(year_a)
        overview_b = self.get_budget_overview(year_b)

        areas_a = {a.area_id: a for a in overview_a.areas}
        areas_b = {a.area_id: a for a in overview_b.areas}

        all_ids = sorted(set(areas_a.keys()) | set(areas_b.keys()))

        comparisons: list[dict[str, Any]] = []
        for aid in all_ids:
            a = areas_a.get(aid)
            b = areas_b.get(aid)
            outcome_a = a.outcome_msek if a else 0.0
            outcome_b = b.outcome_msek if b else 0.0
            delta = outcome_b - outcome_a
            pct = (delta / outcome_a * 100) if outcome_a != 0 else None

            comparisons.append({
                "area_id": aid,
                "area_name": (b or a).area_name if (b or a) else aid,
                f"outcome_{year_a}_msek": outcome_a,
                f"outcome_{year_b}_msek": outcome_b,
                "delta_msek": delta,
                "delta_pct": round(pct, 2) if pct is not None else None,
            })

        return comparisons

    def get_available_years(self) -> list[int]:
        """Get list of years with loaded data."""
        years = set()
        for row in self._expenditure_data:
            years.add(row.year)
        for row in self._income_data:
            years.add(row.year)
        return sorted(years)

    @property
    def expenditure_data(self) -> list[ExpenditureRow]:
        """Access raw expenditure data."""
        return self._expenditure_data

    @property
    def income_data(self) -> list[IncomeRow]:
        """Access raw income data."""
        return self._income_data
