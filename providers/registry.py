"""
Provider registry — maps config strings to concrete provider classes.

Usage:
    from providers.registry import get_universe_provider, get_price_provider

    universe = get_universe_provider()  # reads from settings.provider_universe
    stocks = await universe.get_stock_list()

To add a new provider (e.g. Polygon):
    1. Create providers/polygon.py implementing the relevant ABCs
    2. Register it in the dicts below
    3. Set SD_PROVIDER_xxx=polygon in .env
"""
from __future__ import annotations

import logging
from typing import Type

from config.settings import settings
from providers.base import (
    FundamentalsProvider,
    IntradayProvider,
    PriceProvider,
    UniverseProvider,
)

logger = logging.getLogger(__name__)

# ── Registration maps ────────────────────────────────────────────
# Lazy imports to avoid loading unused providers

_UNIVERSE_PROVIDERS: dict[str, tuple[str, str]] = {
    "fmp": ("providers.fmp", "FMPUniverseProvider"),
    "yfinance": ("providers.yfinance_provider", "YFinanceUniverseProvider"),
}

_FUNDAMENTALS_PROVIDERS: dict[str, tuple[str, str]] = {
    "fmp": ("providers.fmp", "FMPFundamentalsProvider"),
    "yfinance": ("providers.yfinance_provider", "YFinanceFundamentalsProvider"),
}

_PRICE_PROVIDERS: dict[str, tuple[str, str]] = {
    "fmp": ("providers.fmp", "FMPPriceProvider"),
    "yfinance": ("providers.yfinance_provider", "YFinancePriceProvider"),
}

_INTRADAY_PROVIDERS: dict[str, tuple[str, str]] = {
    "fmp": ("providers.fmp", "FMPIntradayProvider"),
    "yfinance": ("providers.yfinance_provider", "YFinanceIntradayProvider"),
}


def _load_class(module_path: str, class_name: str) -> Type:
    """Dynamically import a provider class."""
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _get_provider(registry: dict, config_key: str, interface_name: str):
    """Generic factory for any provider type."""
    if config_key not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(
            f"Unknown {interface_name} provider: '{config_key}'. "
            f"Available: {available}"
        )
    module_path, class_name = registry[config_key]
    cls = _load_class(module_path, class_name)
    logger.info("Using %s provider: %s", interface_name, config_key)
    return cls()


# ── Public factory functions ─────────────────────────────────────

def get_universe_provider() -> UniverseProvider:
    return _get_provider(
        _UNIVERSE_PROVIDERS, settings.provider_universe, "universe"
    )


def get_fundamentals_provider() -> FundamentalsProvider:
    return _get_provider(
        _FUNDAMENTALS_PROVIDERS, settings.provider_fundamentals, "fundamentals"
    )


def get_price_provider() -> PriceProvider:
    return _get_provider(
        _PRICE_PROVIDERS, settings.provider_eod_prices, "price"
    )


def get_intraday_provider() -> IntradayProvider:
    return _get_provider(
        _INTRADAY_PROVIDERS, settings.provider_intraday, "intraday"
    )
