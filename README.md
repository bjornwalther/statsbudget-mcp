# statsbudget-mcp

MCP server for the Swedish national budget (statsbudgeten). Provides structured, queryable access to budget allocations, tax revenue, and fiscal data.

## Data Sources

| Source | What | Format | Coverage |
|--------|------|--------|----------|
| SCB PxWeb API | Tax revenue by type, tax quota/GDP | JSON (POST) | 1950-2025 |
| Statskontoret Oppna Data | Budget outcome per expenditure area | CSV | 2006-2025 |
| Riksdagen Oppna Data | Votes, documents, propositions | JSON | All sessions |

## MCP Tools

- `get_budget_overview(year)` - total income/expenditure, all 27 areas
- `get_expenditure_area(area_id, year)` - drill-down into appropriations
- `compare_budgets(year_a, year_b)` - delta between years
- `get_revenue(year)` - tax revenue by type (labour, capital, consumption)
- `get_revenue_timeseries(from_year, to_year)` - time series
- `get_laffer_data(tax_type?)` - tax rate vs revenue as % of GDP
- `get_votes_on_budget(year, area_id?)` - voting results
- `search_budget_decisions(query)` - free-text search

## Installation

```bash
# From PyPI (once published)
uvx statsbudget-mcp

# Development
git clone https://github.com/bjornwalther/statsbudget-mcp.git
cd statsbudget-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
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
|-- __init__.py
|-- server.py          # FastMCP server + tool definitions
|-- scb_client.py      # SCB PxWeb API client
|-- statskontoret.py   # Statskontoret CSV client (budget outcomes)
|-- riksdagen.py       # Riksdagen API client (votes, documents)
|-- cache.py           # SQLite local cache
```

## License

MIT
