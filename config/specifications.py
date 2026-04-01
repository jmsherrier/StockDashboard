"""
Screening specifications — all filter configs and pipeline parameters.

Edit this file to customize screening behavior. The orchestrator and
seed scripts read from here so everything stays in one place.
"""
from __future__ import annotations

from filters.base import FilterConfig

# ── Data Import ──────────────────────────────────────────────────

# 1 trading year = 252 days. The seed script converts this to
# calendar days (~1.45x) so yfinance/FMP return enough bars.
TRADING_DAYS = 252

# ── Tier 1: Fundamental Filters ─────────────────────────────────
# These run against cached DB data. Zero API calls needed.
# Stocks must pass all required=True filters to advance.

FUNDAMENTAL_FILTERS = [
    FilterConfig(
        name="market_cap",
        params={"min_cap": 100_000_000},
        weight=1.0,
        required=True,
    ),
    FilterConfig(
        name="volume",
        params={"min_volume": 200_000},
        weight=0.8,
        required=True,
    ),
    FilterConfig(
        name="price",
        params={"min_price": 5.0},
        weight=0.5,
        required=True,
    ),
    FilterConfig(
        name="valuation",
        params={"max_pe": 60, "min_roe": 0.03},
        weight=1.5,
        required=True,
    ),
    FilterConfig(
        name="growth",
        params={"min_revenue_growth": 0.0, "min_eps_growth": 0.0},
        weight=1.0,
        required=True,
    ),
]

# ── Tier 2: Technical Filters ───────────────────────────────────
# These run against daily OHLCV data using TA indicators.

TECHNICAL_FILTERS = [
    FilterConfig(
        name="trend",
        params={"max_pct_below_52w_high": 0.30},
        weight=2.0,
        required=True,
    ),
    FilterConfig(
        name="momentum",
        params={"rsi_min": 35, "rsi_max": 80},
        weight=1.5,
        required=True,
    ),
    FilterConfig(
        name="relative_strength",
        params={"min_percentile": 50},
        weight=1.5,
        required=True,
    ),
]

# ── Tier 3: Intraday Filters ────────────────────────────────────
# These use live/near-live data. Most expensive tier.

INTRADAY_FILTERS = [
    FilterConfig(
        name="spread",
        params={"max_spread_pct": 1.0},
        weight=1.0,
        required=False,
    ),
    FilterConfig(
        name="intraday_momentum",
        params={"min_change_pct": -5},
        weight=1.0,
        required=False,
    ),
]
