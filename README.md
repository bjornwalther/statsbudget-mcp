# statsbudget-mcp

> **Status: Alpha (v0.1.0)**
> This project is under active development. APIs, schemas, and output formats may change without notice. Not recommended for production use yet. Contributions and feedback welcome.

MCP server for the Swedish national budget (statsbudgeten). Provides structured, queryable access to budget allocations, tax revenue, Laffer curve analysis, and fiscal data.

Built for Claude Desktop, Glama, and any MCP-compatible client.

## Data Sources

| Source | What | Format | Coverage |
|--------|------|--------|----------|
| SCB PxWeb API | Tax revenue by type, tax quota/GDP | JSON (POST) | 1950-2025 |
| Statskontoret Oppna Data | Budget outcome per expenditure area | CSV | 2006-2025 |
| Riksdagen Oppna Data | Votes, documents, propositions | JSON | All sessions |

## MCP Tools (14)

**Budget (4)**
- `get_budget_overview(year)` : total income/expenditure, all 27 areas
- `get_expenditure_area(area_id, year)` : drill-down into appropriations
- `compare_budgets(year_a, year_b)` : delta between years
- `sync_budget_data(year?)` : download and cache latest data

**Revenue (3)**
- `get_revenue(year)` : tax revenue by type (labour, capital, consumption)
- `get_revenue_timeseries(from_year, to_year)` : time series
- `get_revenue_detail(year, tax_types?)` : full 40-category breakdown

**Laffer Curve (3)**
- `get_laffer_data(from_year?, to_year?)` : tax pressure vs GDP, grouped by decade
- `get_laffer_timeseries(from_year?, to_year?)` : tax quota over time with reform markers
- `get_tax_reforms()` : annotated Swedish tax reforms (1971-2020)

**Meta (4)**
- `get_sync_status()` : data freshness and cache diagnostics
- `get_publication_schedule()` : when Statskontoret publishes new data
- `get_available_years()` : years with loaded data
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
|-- statskontoret.py   # Statskontoret CSV client (scrape, parse, sync metadata)
|-- laffer.py          # Laffer curve analysis with reform annotations
|-- cache.py           # SQLite persistent cache
|-- formatters.py      # ASCII visualization (bars, flow, decision chain, Laffer)
```

## Roadmap

- [x] SCB tax revenue and quota client
- [x] Statskontoret budget outcome client
- [x] Laffer curve module with reform annotations
- [x] SQLite cache with auto-load at startup
- [x] FastMCP server with 14 tools
- [x] ASCII formatters (bars, flow, decision, comparison, Laffer timeline)
- [x] Retry logic with exponential backoff
- [ ] Publish to PyPI (`uvx statsbudget-mcp`)
- [ ] Riksdagen voting client
- [ ] Laffer #2: corporate tax (statutory rate vs revenue/GDP)
- [ ] Laffer #3: marginal income tax (Pomperipossa analysis)
- [ ] Taxpayer breakdown (private/public/transfer recipients)
- [ ] Schema versioning and cache validation

## License

MIT
