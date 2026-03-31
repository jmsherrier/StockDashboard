# Stock Dashboard — Screening & Data Pipeline

A provider-agnostic stock screening and data pipeline designed to evolve into automated trading strategies.

## Architecture Philosophy

**Filter cheap → filter expensive.** Static/fundamental data eliminates 90%+ of the universe
before any live or intraday data is fetched. This keeps API costs minimal and scales cleanly.

```
Universe (~8,000 US equities)
    │
    ▼  TIER 1: Static filters (free/cached, run once daily)
    │  - Market cap, sector, exchange, listing age
    │  - Fundamental ratios (P/E, debt/equity, revenue growth)
    │  - Average volume, float
    │  Result: ~500-1500 stocks
    │
    ▼  TIER 2: Daily technical filters (EOD data, cheap)
    │  - Moving averages, RSI, MACD
    │  - Volume breakout, relative strength
    │  - 52-week high/low proximity
    │  Result: ~50-200 stocks
    │
    ▼  TIER 3: Intraday/live filters (expensive, real-time)
    │  - Intraday volume surge
    │  - Bid/ask spread
    │  - Real-time price momentum
    │  Result: ~10-30 actionable stocks
    │
    ▼  OUTPUT: Ranked watchlist → future trading signals
```

## Data Provider Strategy

The system uses a **provider adapter pattern** — every data call goes through an abstract
interface, with swappable backends. This means you develop with free/cheap providers and
deploy with production ones, changing only a config value.

| Data Type | Dev Provider (Free) | Prod Provider (Cheap) | Prod Provider (Pro) |
|---|---|---|---|
| **Fundamentals** | FMP Free (250 req/day) | FMP Starter ($19/mo) | FMP Premium / Polygon |
| **EOD Prices** | FMP Free / yfinance | FMP Starter | Polygon Starter ($29/mo) |
| **Historical OHLCV** | yfinance | FMP / Tiingo ($10/mo) | Polygon Developer |
| **Intraday Quotes** | FMP Free (delayed) | Alpaca (free real-time) | Polygon / Massive |
| **Stock Universe** | FMP /stock/list | FMP /stock/list | SEC EDGAR + FMP |
| **News/Sentiment** | Finnhub Free | FMP Starter | Benzinga / Bloomberg |

**Why FMP as default?** $19/mo gets fundamentals + EOD + screener endpoints + 70k+ symbols
across 46 countries. For a screening pipeline that mostly needs daily data, this is the
cheapest path to production-grade data. yfinance is fine for development but should never
be the sole production dependency.

**Why Alpaca for real-time?** Free real-time US equity data with a (free, unfunded) brokerage
account. And when you're ready to automate trading, Alpaca IS the broker — zero friction
from screening to execution.

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.11+ | Ecosystem, pandas, async |
| API Framework | FastAPI | Async, auto-docs, typed |
| Task Queue | Celery + Redis | Scheduled scans, background fetches |
| Database | PostgreSQL (prod) / SQLite (dev) | SQLAlchemy, same ORM either way |
| Cache | Redis | TTL-based data caching |
| TA Library | pandas-ta | Pure Python, no C deps like TA-Lib |

## Project Structure

```
stock-dashboard/
├── config/
│   ├── settings.py          # Pydantic settings, env-driven
│   └── providers.yaml       # Provider selection per data type
├── core/
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas for API
│   └── enums.py             # Exchanges, sectors, intervals
├── providers/
│   ├── base.py              # Abstract provider interfaces
│   ├── fmp.py               # Financial Modeling Prep
│   ├── yfinance_provider.py # yfinance (dev only)
│   ├── alpaca_provider.py   # Alpaca Markets
│   └── registry.py          # Provider factory/registry
├── filters/
│   ├── base.py              # Abstract filter interface
│   ├── fundamental.py       # Tier 1: static/fundamental
│   ├── technical.py         # Tier 2: daily technical
│   └── intraday.py          # Tier 3: live/intraday
├── pipeline/
│   ├── orchestrator.py      # Runs filter tiers in sequence
│   ├── scheduler.py         # Celery beat schedules
│   └── tasks.py             # Celery task definitions
├── storage/
│   ├── database.py          # SQLAlchemy engine/session
│   ├── cache.py             # Redis cache wrapper
│   └── repositories.py      # Data access layer
├── api/
│   ├── app.py               # FastAPI app factory
│   ├── routes/
│   │   ├── screener.py      # Screening endpoints
│   │   ├── stocks.py        # Stock detail endpoints
│   │   └── health.py        # Health check
│   └── deps.py              # Dependency injection
├── scripts/
│   ├── seed_universe.py     # Initial universe population
│   └── backfill_history.py  # Historical data backfill
├── tests/
├── requirements.txt
├── docker-compose.yml
└── .env.example
```

## Quick Start

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with your FMP API key (free tier works)

# 3. Initialize database
python -m scripts.seed_universe

# 4. Run the screening pipeline
python -m pipeline.orchestrator

# 5. Start the API (optional, for frontend later)
uvicorn api.app:create_app --factory --reload
```

## Future: Trading Strategy Integration

The pipeline output (ranked watchlist) is designed to feed into:
- **Signal generators** — consume the filtered universe, emit buy/sell signals
- **Backtesting** — historical filter results stored for replay
- **Execution** — Alpaca's trading API (same provider, same auth)

The `pipeline.orchestrator` emits events that a strategy module can subscribe to.
"""
