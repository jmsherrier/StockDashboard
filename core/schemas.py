"""
Pydantic schemas — used for API responses and as internal DTOs
between providers and the pipeline.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Provider DTOs ────────────────────────────────────────────────

class StockInfo(BaseModel):
    """Minimal stock info returned by universe providers."""
    symbol: str
    name: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    country: str = "US"
    ipo_date: Optional[date] = None


class FundamentalData(BaseModel):
    """Fundamental metrics for a single stock."""
    symbol: str
    snapshot_date: date

    # Market data (needed by filters)
    market_cap: Optional[float] = None
    price: Optional[float] = None

    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None

    revenue_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    revenue_growth_qoq: Optional[float] = None
    eps_growth_qoq: Optional[float] = None

    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None

    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    free_cash_flow: Optional[float] = None

    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    avg_volume_10d: Optional[float] = None
    avg_volume_30d: Optional[float] = None
    shares_outstanding: Optional[float] = None
    float_shares: Optional[float] = None
    insider_ownership: Optional[float] = None
    institutional_ownership: Optional[float] = None


class OHLCVBar(BaseModel):
    """Single OHLCV bar — works for daily, intraday, any interval."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: Optional[float] = None


class QuoteSnapshot(BaseModel):
    """Real-time or delayed quote for intraday filtering."""
    symbol: str
    timestamp: datetime
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    volume: int = 0
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None


# ── Filter Results ───────────────────────────────────────────────

class FilterResult(BaseModel):
    """Result of running a single filter on a stock."""
    symbol: str
    passed: bool
    score: float = Field(0.0, ge=0, le=100)
    reason: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


# ── API Response Schemas ─────────────────────────────────────────

class ScreenerResultResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    composite_score: Optional[float] = None
    fundamental_score: Optional[float] = None
    technical_score: Optional[float] = None
    intraday_score: Optional[float] = None
    price: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    passed_tiers: list[str] = Field(default_factory=list)


class ScreenerRunResponse(BaseModel):
    run_id: str
    timestamp: datetime
    total_universe: int
    passed_fundamental: int
    passed_technical: int
    passed_intraday: int
    results: list[ScreenerResultResponse]


class HealthResponse(BaseModel):
    status: str = "ok"
    environment: str
    database: str = "unknown"
    cache: str = "unknown"
    providers: dict[str, str] = Field(default_factory=dict)
