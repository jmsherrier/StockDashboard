"""
SQLAlchemy models. Works with both SQLite (dev) and PostgreSQL (prod).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Stock(Base):
    """
    Core stock universe table. Populated from provider's stock list endpoint.
    Updated weekly — this is the cheapest data to maintain.
    """
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(20))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    industry: Mapped[Optional[str]] = mapped_column(String(200))
    market_cap: Mapped[Optional[float]] = mapped_column(Float)
    country: Mapped[Optional[str]] = mapped_column(String(10), default="US")
    ipo_date: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_stocks_exchange_active", "exchange", "is_active"),
        Index("ix_stocks_sector", "sector"),
        Index("ix_stocks_market_cap", "market_cap"),
    )


class Fundamental(Base):
    """
    Fundamental data snapshot. Refreshed weekly or on earnings.
    One row per stock per snapshot date.
    """
    __tablename__ = "fundamentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Market data (needed by filters)
    market_cap: Mapped[Optional[float]] = mapped_column(Float)
    price: Mapped[Optional[float]] = mapped_column(Float)

    # Valuation
    pe_ratio: Mapped[Optional[float]] = mapped_column(Float)
    forward_pe: Mapped[Optional[float]] = mapped_column(Float)
    peg_ratio: Mapped[Optional[float]] = mapped_column(Float)
    price_to_book: Mapped[Optional[float]] = mapped_column(Float)
    price_to_sales: Mapped[Optional[float]] = mapped_column(Float)
    ev_to_ebitda: Mapped[Optional[float]] = mapped_column(Float)

    # Growth
    revenue_growth_yoy: Mapped[Optional[float]] = mapped_column(Float)
    eps_growth_yoy: Mapped[Optional[float]] = mapped_column(Float)
    revenue_growth_qoq: Mapped[Optional[float]] = mapped_column(Float)
    eps_growth_qoq: Mapped[Optional[float]] = mapped_column(Float)

    # Profitability
    gross_margin: Mapped[Optional[float]] = mapped_column(Float)
    operating_margin: Mapped[Optional[float]] = mapped_column(Float)
    net_margin: Mapped[Optional[float]] = mapped_column(Float)
    roe: Mapped[Optional[float]] = mapped_column(Float)
    roa: Mapped[Optional[float]] = mapped_column(Float)
    roic: Mapped[Optional[float]] = mapped_column(Float)

    # Financial Health
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Float)
    current_ratio: Mapped[Optional[float]] = mapped_column(Float)
    quick_ratio: Mapped[Optional[float]] = mapped_column(Float)
    interest_coverage: Mapped[Optional[float]] = mapped_column(Float)
    free_cash_flow: Mapped[Optional[float]] = mapped_column(Float)

    # Dividend
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float)
    payout_ratio: Mapped[Optional[float]] = mapped_column(Float)

    # Volume & Float
    avg_volume_10d: Mapped[Optional[float]] = mapped_column(Float)
    avg_volume_30d: Mapped[Optional[float]] = mapped_column(Float)
    shares_outstanding: Mapped[Optional[float]] = mapped_column(Float)
    float_shares: Mapped[Optional[float]] = mapped_column(Float)
    insider_ownership: Mapped[Optional[float]] = mapped_column(Float)
    institutional_ownership: Mapped[Optional[float]] = mapped_column(Float)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_date", name="uq_fundamental_snapshot"),
        Index("ix_fundamentals_date", "snapshot_date"),
    )


class DailyPrice(Base):
    """
    End-of-day OHLCV. The workhorse table for technical analysis.
    """
    __tablename__ = "daily_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "price_date", name="uq_daily_price"),
        Index("ix_daily_prices_symbol_date", "symbol", "price_date"),
        Index("ix_daily_prices_date", "price_date"),
    )


class ScreenerResult(Base):
    """
    Output of each screening run. Stores which stocks passed each tier
    and their composite scores. This is what the frontend will display
    and what trading strategies will consume.
    """
    __tablename__ = "screener_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)  # UUID
    run_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Which tiers this stock passed
    passed_fundamental: Mapped[bool] = mapped_column(Boolean, default=False)
    passed_technical: Mapped[bool] = mapped_column(Boolean, default=False)
    passed_intraday: Mapped[bool] = mapped_column(Boolean, default=False)

    # Scores (0-100) from each tier
    fundamental_score: Mapped[Optional[float]] = mapped_column(Float)
    technical_score: Mapped[Optional[float]] = mapped_column(Float)
    intraday_score: Mapped[Optional[float]] = mapped_column(Float)
    composite_score: Mapped[Optional[float]] = mapped_column(Float)

    # Snapshot of key metrics at scan time (denormalized for fast reads)
    price_at_scan: Mapped[Optional[float]] = mapped_column(Float)
    volume_at_scan: Mapped[Optional[float]] = mapped_column(Float)
    market_cap_at_scan: Mapped[Optional[float]] = mapped_column(Float)

    # JSON blob for strategy-specific metadata
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_screener_run_score", "run_id", "composite_score"),
    )
