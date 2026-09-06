# statsbudget-mcp

> **Status: Alpha (v0.1.0)**
> This project is under active development. APIs, schemas, and output formats may change without notice. Not recommended for production use yet. Contributions and feedback welcome.

MCP server for the Swedish national budget (statsbudgeten). Provides structured, queryable access to budget outturn (utfall), tax revenue, tax quota analysis, and fiscal data.

Built for Claude Desktop, Glama, and any MCP-compatible client.

## Important: Data Semantics

Budget tools return **actual outturn** (utfall) from Statskontoret, not the originally proposed budget. This means the numbers show what was actually spent and collected, not what was planned. Every response includes `data_type` and `source` fields so consuming applications can communicate this clearly.

## Data Sources

| Source | What | Format | Coverage |
|--------|------|--------|----------|
| SCB PxWeb API | Tax revenue by type, tax quota/GDP | JSON (POST) | 1950-2025 |
| Statskontoret Oppna Data | Budget outturn per expenditure area | CSV in ZIP | 2006-2025 |

## MCP Tools (14)

**Budget Outturn (4)**
- `get_budget_overview(year)` : actual expenditure outturn, total income, balance, all 27 areas (MSEK)
- `get_expenditure_area(area_id, year)` : drill-down into appropriations with budget vs outturn
- `compare_budgets(year_a, year_b)` : year-over-year outturn delta per area
- `sync_budget_data(year?)` : download and cache latest outturn from Statskontoret

**Tax Revenue (3)**
- `get_revenue(year)` : tax revenue by category (labour, capital, consumption) in MSEK
- `get_revenue_timeseries(from_year, to_year)` : revenue over time by category
- `get_revenue_detail(year, tax_types?)` : full 40-category breakdown

**Tax Quota Analysis (3)**
- `get_laffer_data(from_year?, to_year?)` : tax quota (% of GDP) as timeseries with decade tags and reform annotations
- `get_laffer_timeseries(from_year?, to_year?)` : flat timeseries with nominal GDP growth and reform markers
- `get_tax_reforms()` : annotated Swedish tax reforms (1971-2020)

**Meta (4)**
- `get_sync_status()` : data freshness and cache diagnostics
- `get_publication_schedule()` : when Statskontoret publishes new data
- `get_available_years()` : years with loaded outturn data
- `get_cache_stats()` : SQLite cache diagnostics

**Resources**
- `budget://areas` : all 27 expenditure areas (id, name)

## Installation

```bash
# Development
git clone https://github.com/bjornwalther/statsbudget-mcp.git
cd statsbudget-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the server
statsbudget-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "statsbudget-mcp": {
      "command": "python",
      "args": ["-m", "statsbudget_mcp.server"]
    }
  }
}
```

## Development

```bash
# Run tests (unit only)
pytest tests/ -m "not integration"

# Run all tests including SCB API integration
pytest tests/

# Lint
ruff check src/ tests/
```

## Architecture

```
src/statsbudget_mcp/
|-- __init__.py        # Package version
|-- server.py          # FastMCP server, 14 tools, lifespan with auto-cache
|-- scb_client.py      # SCB PxWeb API client (async, retry with backoff)
|-- statskontoret.py   # Statskontoret CSV client (scrape, download, parse)
|-- laffer.py          # Tax quota analysis with reform annotations
|-- cache.py           # SQLite persistent cache (schema-versioned, atomic snapshots)
|-- formatters.py      # ASCII visualization (bars, flow, decision chain, Laffer)
```

## Roadmap

- [x] SCB tax revenue and quota client
- [x] Statskontoret budget outturn client
- [x] Tax quota analysis module with reform annotations
- [x] SQLite cache with schema versioning and atomic snapshots
- [x] FastMCP server with 14 tools
- [x] ASCII formatters (bars, flow, decision, comparison, Laffer timeline)
- [x] Retry logic with exponential backoff
- [x] Download/ZIP size limits and host allowlist
- [ ] Publish to PyPI (`uvx statsbudget-mcp`)
- [ ] Riksdagen voting client (propositions, votes per party)
- [ ] Taxpayer breakdown by income source (5-level drill-down with legislative history)
- [ ] Laffer #2: corporate tax (statutory rate vs revenue/GDP)
- [ ] Laffer #3: marginal income tax (Pomperipossa analysis)

## License

MIT
