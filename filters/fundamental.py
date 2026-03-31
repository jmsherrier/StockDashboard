"""
Tier 1: Fundamental Filters.

These run against cached/stored fundamental data. Zero API calls
needed if the data was already fetched in the daily refresh.
This is where 80-90% of the universe gets eliminated.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from core.schemas import FilterResult, FundamentalData
from filters.base import FilterConfig, StockFilter
from storage.repositories import FundamentalRepository

logger = logging.getLogger(__name__)


class MarketCapFilter(StockFilter):
    """
    Filter by market cap range.
    Params: min_cap (float), max_cap (float, optional)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = FundamentalRepository()
        min_cap = self.config.params.get("min_cap", 100_000_000)
        max_cap = self.config.params.get("max_cap")

        results = []
        fundamentals = await repo.get_latest_bulk(symbols)

        for symbol in symbols:
            f = fundamentals.get(symbol)
            if not f or f.get("market_cap") is None:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="No market cap data"
                ))
                continue

            cap = f["market_cap"]
            passed = cap >= min_cap
            if max_cap:
                passed = passed and cap <= max_cap

            # Score: logarithmic scale, mega-cap scores highest
            import math
            score = min(100, max(0, (math.log10(max(cap, 1)) - 7) * 20))

            results.append(FilterResult(
                symbol=symbol,
                passed=passed,
                score=round(score, 2),
                details={"market_cap": cap},
            ))
        return results


class VolumeFilter(StockFilter):
    """
    Filter by average daily volume.
    Params: min_volume (int), lookback (str: '10d' or '30d')
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = FundamentalRepository()
        min_vol = self.config.params.get("min_volume", 200_000)
        lookback = self.config.params.get("lookback", "30d")

        results = []
        fundamentals = await repo.get_latest_bulk(symbols)

        for symbol in symbols:
            f = fundamentals.get(symbol)
            vol_key = "avg_volume_10d" if lookback == "10d" else "avg_volume_30d"
            vol = (f or {}).get(vol_key)

            if vol is None:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="No volume data"
                ))
                continue

            passed = vol >= min_vol
            # Score: scale relative to threshold
            score = min(100, (vol / max(min_vol, 1)) * 50)

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(score, 2),
                details={"avg_volume": vol},
            ))
        return results


class PriceFilter(StockFilter):
    """
    Filter by price range (eliminates penny stocks and extreme outliers).
    Params: min_price (float), max_price (float, optional)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = FundamentalRepository()
        min_price = self.config.params.get("min_price", 5.0)
        max_price = self.config.params.get("max_price")

        results = []
        fundamentals = await repo.get_latest_bulk(symbols)

        for symbol in symbols:
            f = fundamentals.get(symbol)
            price = (f or {}).get("price")

            if price is None:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="No price data"
                ))
                continue

            passed = price >= min_price
            if max_price:
                passed = passed and price <= max_price

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=50.0 if passed else 0,
                details={"price": price},
            ))
        return results


class ValuationFilter(StockFilter):
    """
    Multi-metric valuation filter.
    Params: max_pe (float), max_peg (float), min_roe (float), etc.
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = FundamentalRepository()
        max_pe = self.config.params.get("max_pe", 50)
        max_peg = self.config.params.get("max_peg", 3.0)
        min_roe = self.config.params.get("min_roe", 0.05)
        max_debt_equity = self.config.params.get("max_debt_equity", 3.0)

        results = []
        fundamentals = await repo.get_latest_bulk(symbols)

        for symbol in symbols:
            f = fundamentals.get(symbol)
            if not f:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0,
                    reason="No fundamental data"
                ))
                continue

            score = 50.0  # Start neutral
            flags = []
            penalties = 0

            # P/E check
            pe = f.get("pe_ratio")
            if pe is not None:
                if 0 < pe <= max_pe:
                    score += 10
                elif pe > max_pe:
                    penalties += 1
                    flags.append(f"PE={pe:.1f}>{max_pe}")
                elif pe < 0:
                    penalties += 1
                    flags.append("negative_PE")

            # PEG check
            peg = f.get("peg_ratio")
            if peg is not None:
                if 0 < peg <= max_peg:
                    score += 10
                elif peg > max_peg:
                    penalties += 1

            # ROE check
            roe = f.get("roe")
            if roe is not None:
                if roe >= min_roe:
                    score += 15
                else:
                    penalties += 1

            # Debt/Equity check
            de = f.get("debt_to_equity")
            if de is not None:
                if de <= max_debt_equity:
                    score += 10
                else:
                    penalties += 1

            # Margin bonus
            net_margin = f.get("net_margin")
            if net_margin is not None and net_margin > 0.1:
                score += 5

            score = max(0, min(100, score - penalties * 10))
            passed = penalties <= 1  # Allow one miss

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(score, 2),
                reason="; ".join(flags) if flags else None,
                details={k: f.get(k) for k in ["pe_ratio", "peg_ratio", "roe", "debt_to_equity"]},
            ))
        return results


class GrowthFilter(StockFilter):
    """
    Growth-focused filter.
    Params: min_revenue_growth (float), min_eps_growth (float)
    """

    async def apply(self, symbols: Sequence[str]) -> list[FilterResult]:
        repo = FundamentalRepository()
        min_rev_growth = self.config.params.get("min_revenue_growth", 0.05)
        min_eps_growth = self.config.params.get("min_eps_growth", 0.10)

        results = []
        fundamentals = await repo.get_latest_bulk(symbols)

        for symbol in symbols:
            f = fundamentals.get(symbol)
            if not f:
                results.append(FilterResult(
                    symbol=symbol, passed=False, score=0
                ))
                continue

            score = 50.0
            rev_g = f.get("revenue_growth_yoy")
            eps_g = f.get("eps_growth_yoy")

            if rev_g is not None and rev_g >= min_rev_growth:
                score += 20
            if eps_g is not None and eps_g >= min_eps_growth:
                score += 20

            # Bonus for acceleration
            rev_q = f.get("revenue_growth_qoq")
            if rev_q is not None and rev_g is not None and rev_q > rev_g:
                score += 10  # Accelerating growth

            score = min(100, score)
            passed = (
                (rev_g is not None and rev_g >= min_rev_growth) or
                (eps_g is not None and eps_g >= min_eps_growth)
            )

            results.append(FilterResult(
                symbol=symbol, passed=passed,
                score=round(score, 2),
                details={"revenue_growth_yoy": rev_g, "eps_growth_yoy": eps_g},
            ))
        return results


# ── Filter factory ───────────────────────────────────────────────

FUNDAMENTAL_FILTERS: dict[str, type[StockFilter]] = {
    "market_cap": MarketCapFilter,
    "volume": VolumeFilter,
    "price": PriceFilter,
    "valuation": ValuationFilter,
    "growth": GrowthFilter,
}


def build_fundamental_filters(configs: list[FilterConfig]) -> list[StockFilter]:
    """Build filter instances from config list."""
    filters = []
    for cfg in configs:
        cls = FUNDAMENTAL_FILTERS.get(cfg.name)
        if cls:
            filters.append(cls(cfg))
        else:
            logger.warning("Unknown fundamental filter: %s", cfg.name)
    return filters
