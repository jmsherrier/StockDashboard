"""
Environment-driven configuration using Pydantic settings.
All provider keys, database URLs, and feature flags live here.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SD_",  # SD = Stock Dashboard
        case_sensitive=False,
    )

    # --- General ---
    env: Environment = Environment.DEV
    debug: bool = False
    log_level: str = "INFO"

    # --- Database ---
    # Dev default is SQLite; prod should override with PostgreSQL URL
    database_url: str = "sqlite:///./stock_dashboard.db"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_fundamentals: int = 86400 * 7  # 7 days
    cache_ttl_eod_prices: int = 86400         # 1 day
    cache_ttl_intraday: int = 300             # 5 minutes

    # --- Provider Keys ---
    fmp_api_key: Optional[str] = None
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"  # paper by default
    finnhub_api_key: Optional[str] = None
    tiingo_api_key: Optional[str] = None
    polygon_api_key: Optional[str] = None

    # --- Provider Selection ---
    # Which provider to use for each data type. Changeable per-environment.
    provider_fundamentals: str = "fmp"
    provider_eod_prices: str = "fmp"
    provider_historical: str = "fmp"
    provider_intraday: str = "fmp"
    provider_universe: str = "fmp"

    # --- Pipeline ---
    universe_refresh_cron: str = "0 5 * * 1"    # Monday 5am
    eod_refresh_cron: str = "0 18 * * 1-5"      # Weekday 6pm ET
    screener_run_cron: str = "30 18 * * 1-5"    # Weekday 6:30pm ET
    intraday_interval_seconds: int = 300          # 5 min during market hours

    # --- Screening Defaults ---
    min_market_cap: float = 100_000_000          # $100M
    min_avg_volume: int = 200_000                # 200k shares/day
    min_price: float = 5.0                       # No penny stocks
    max_stocks_tier2: int = 500                  # Max passed to technical filter
    max_stocks_tier3: int = 100                  # Max passed to intraday filter

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
