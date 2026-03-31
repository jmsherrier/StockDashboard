"""
Financial Modeling Prep (FMP) provider implementation.

FMP is the recommended default because:
- Free tier: 250 req/day, enough for dev and small universes
- Starter ($19/mo): unlimited calls, 20GB bandwidth, full fundamentals
- Single API covers universe + fundamentals + EOD + intraday + screener
- Clean JSON, well-documented, Python-friendly
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Optional, Sequence

import httpx

from config.settings import settings
from core.schemas import FundamentalData, OHLCVBar, QuoteSnapshot, StockInfo
from providers.base import (
    FundamentalsProvider,
    IntradayProvider,
    PriceProvider,
    UniverseProvider,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/api"


class FMPClient:
    """
    Shared HTTP client for FMP with rate limiting and error handling.
    All provider classes delegate to this.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.fmp_api_key
        if not self.api_key:
            raise ValueError(
                "FMP API key required. Set SD_FMP_API_KEY env var or get a free key at "
                "https://site.financialmodelingprep.com/developer/docs"
            )
        self._semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def get(self, path: str, params: Optional[dict] = None) -> Any:
        """Make a GET request to FMP API."""
        params = params or {}
        params["apikey"] = self.api_key
        async with self._semaphore:
            client = await self._get_client()
            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
                data = resp.json()
                # FMP returns error messages as dicts
                if isinstance(data, dict) and "Error Message" in data:
                    logger.error("FMP error for %s: %s", path, data["Error Message"])
                    return None
                return data
            except httpx.HTTPStatusError as e:
                logger.error("FMP HTTP %s for %s: %s", e.response.status_code, path, e)
                return None
            except Exception as e:
                logger.error("FMP request failed for %s: %s", path, e)
                return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton client instance
_client: Optional[FMPClient] = None


def get_fmp_client() -> FMPClient:
    global _client
    if _client is None:
        _client = FMPClient()
    return _client


# ── Universe Provider ────────────────────────────────────────────

class FMPUniverseProvider(UniverseProvider):

    async def get_stock_list(
        self,
        exchange: Optional[str] = None,
        min_market_cap: Optional[float] = None,
    ) -> list[StockInfo]:
        """
        Uses FMP's /v3/stock/list for the full universe,
        or /v3/stock-screener for filtered results.
        """
        client = get_fmp_client()

        if exchange or min_market_cap:
            # Use the screener endpoint for server-side filtering
            params: dict[str, Any] = {"isActivelyTrading": "true", "limit": 10000}
            if exchange:
                params["exchange"] = exchange
            if min_market_cap:
                params["marketCapMoreThan"] = int(min_market_cap)
            data = await client.get("/v3/stock-screener", params)
        else:
            data = await client.get("/v3/stock/list")

        if not data or not isinstance(data, list):
            return []

        results = []
        for item in data:
            try:
                results.append(StockInfo(
                    symbol=item.get("symbol", ""),
                    name=item.get("companyName", item.get("name", "")),
                    exchange=item.get("exchangeShortName", item.get("exchange")),
                    sector=item.get("sector"),
                    industry=item.get("industry"),
                    market_cap=item.get("marketCap"),
                    country=item.get("country", "US"),
                ))
            except Exception:
                continue
        return results

    async def get_stock_profile(self, symbol: str) -> Optional[StockInfo]:
        client = get_fmp_client()
        data = await client.get(f"/v3/profile/{symbol}")
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        item = data[0]
        return StockInfo(
            symbol=item.get("symbol", symbol),
            name=item.get("companyName", ""),
            exchange=item.get("exchangeShortName"),
            sector=item.get("sector"),
            industry=item.get("industry"),
            market_cap=item.get("mktCap"),
            country=item.get("country", "US"),
            ipo_date=item.get("ipoDate"),
        )


# ── Fundamentals Provider ────────────────────────────────────────

class FMPFundamentalsProvider(FundamentalsProvider):

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalData]:
        client = get_fmp_client()

        # FMP key-metrics-ttm gives trailing-twelve-month ratios in one call
        data = await client.get(f"/v3/key-metrics-ttm/{symbol}")
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        m = data[0]

        # Also get ratios for additional coverage
        ratios = await client.get(f"/v3/ratios-ttm/{symbol}")
        r = ratios[0] if ratios and isinstance(ratios, list) and len(ratios) > 0 else {}

        # And the quote for volume data
        quote = await client.get(f"/v3/quote/{symbol}")
        q = quote[0] if quote and isinstance(quote, list) and len(quote) > 0 else {}

        return FundamentalData(
            symbol=symbol,
            snapshot_date=date.today(),
            pe_ratio=m.get("peRatioTTM"),
            forward_pe=r.get("forwardPERatio"),  # Not always in TTM
            peg_ratio=m.get("pegRatioTTM"),
            price_to_book=m.get("priceToBookRatioTTM") or m.get("pbRatioTTM"),
            price_to_sales=m.get("priceToSalesRatioTTM") or m.get("psRatioTTM"),
            ev_to_ebitda=m.get("enterpriseValueOverEBITDATTM"),
            revenue_growth_yoy=m.get("revenueGrowthTTM"),
            eps_growth_yoy=m.get("epsgrowthTTM"),
            gross_margin=m.get("grossProfitMarginTTM"),
            operating_margin=m.get("operatingProfitMarginTTM"),
            net_margin=m.get("netProfitMarginTTM"),
            roe=m.get("roeTTM"),
            roa=m.get("returnOnAssetsTTM") or m.get("roaTTM"),
            roic=m.get("roicTTM"),
            debt_to_equity=m.get("debtToEquityTTM") or m.get("debtEquityRatioTTM"),
            current_ratio=m.get("currentRatioTTM"),
            quick_ratio=m.get("quickRatioTTM"),
            interest_coverage=m.get("interestCoverageTTM"),
            free_cash_flow=m.get("freeCashFlowPerShareTTM"),
            dividend_yield=m.get("dividendYielTTM") or m.get("dividendYieldTTM"),
            payout_ratio=m.get("payoutRatioTTM"),
            avg_volume_10d=q.get("avgVolume"),
            shares_outstanding=q.get("sharesOutstanding"),
        )

    async def get_fundamentals_bulk(
        self, symbols: Sequence[str]
    ) -> list[FundamentalData]:
        """
        FMP doesn't have a true bulk key-metrics endpoint on free tier,
        so we chunk and parallelize. On paid tiers, you'd use the
        bulk financial endpoints instead.
        """
        results = []
        # Process in chunks of 5 (matching semaphore)
        for i in range(0, len(symbols), 5):
            chunk = symbols[i:i + 5]
            tasks = [self.get_fundamentals(s) for s in chunk]
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in chunk_results:
                if isinstance(r, FundamentalData):
                    results.append(r)
                elif isinstance(r, Exception):
                    logger.warning("Fundamental fetch failed: %s", r)
        return results


# ── Price Provider ───────────────────────────────────────────────

class FMPPriceProvider(PriceProvider):

    async def get_daily_prices(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        client = get_fmp_client()
        params: dict[str, Any] = {}
        if start_date:
            params["from"] = start_date.isoformat()
        if end_date:
            params["to"] = end_date.isoformat()

        data = await client.get(f"/v3/historical-price-full/{symbol}", params)
        if not data or "historical" not in data:
            return []

        bars = []
        for item in data["historical"]:
            try:
                bars.append(OHLCVBar(
                    symbol=symbol,
                    timestamp=datetime.strptime(item["date"], "%Y-%m-%d"),
                    open=item["open"],
                    high=item["high"],
                    low=item["low"],
                    close=item["close"],
                    volume=int(item.get("volume", 0)),
                    adj_close=item.get("adjClose"),
                ))
            except (KeyError, ValueError):
                continue
        # FMP returns newest first; reverse for chronological order
        bars.reverse()
        return bars

    async def get_daily_prices_bulk(
        self,
        symbols: Sequence[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, list[OHLCVBar]]:
        """Parallelize individual fetches. FMP paid tiers have batch-request-end-of-day-prices."""
        results: dict[str, list[OHLCVBar]] = {}
        for i in range(0, len(symbols), 5):
            chunk = symbols[i:i + 5]
            tasks = [
                self.get_daily_prices(s, start_date, end_date) for s in chunk
            ]
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, res in zip(chunk, chunk_results):
                if isinstance(res, list):
                    results[sym] = res
        return results


# ── Intraday Provider ────────────────────────────────────────────

class FMPIntradayProvider(IntradayProvider):

    async def get_quote(self, symbol: str) -> Optional[QuoteSnapshot]:
        client = get_fmp_client()
        data = await client.get(f"/v3/quote/{symbol}")
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        q = data[0]
        return QuoteSnapshot(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(q.get("timestamp", 0)),
            price=q.get("price", 0),
            volume=int(q.get("volume", 0)),
            day_high=q.get("dayHigh"),
            day_low=q.get("dayLow"),
            prev_close=q.get("previousClose"),
            change_pct=q.get("changesPercentage"),
        )

    async def get_quotes_bulk(
        self, symbols: Sequence[str]
    ) -> list[QuoteSnapshot]:
        """FMP supports comma-separated symbols in quote endpoint."""
        client = get_fmp_client()
        results = []
        # FMP allows batching quotes with comma-separated symbols
        for i in range(0, len(symbols), 50):
            chunk = symbols[i:i + 50]
            symbol_str = ",".join(chunk)
            data = await client.get(f"/v3/quote/{symbol_str}")
            if data and isinstance(data, list):
                for q in data:
                    try:
                        results.append(QuoteSnapshot(
                            symbol=q["symbol"],
                            timestamp=datetime.fromtimestamp(q.get("timestamp", 0)),
                            price=q.get("price", 0),
                            volume=int(q.get("volume", 0)),
                            day_high=q.get("dayHigh"),
                            day_low=q.get("dayLow"),
                            prev_close=q.get("previousClose"),
                            change_pct=q.get("changesPercentage"),
                        ))
                    except (KeyError, ValueError):
                        continue
        return results

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "5min",
        start_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        client = get_fmp_client()
        params: dict[str, Any] = {}
        if start_date:
            params["from"] = start_date.isoformat()

        data = await client.get(
            f"/v3/historical-chart/{interval}/{symbol}", params
        )
        if not data or not isinstance(data, list):
            return []

        bars = []
        for item in data:
            try:
                bars.append(OHLCVBar(
                    symbol=symbol,
                    timestamp=datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S"),
                    open=item["open"],
                    high=item["high"],
                    low=item["low"],
                    close=item["close"],
                    volume=int(item.get("volume", 0)),
                ))
            except (KeyError, ValueError):
                continue
        bars.reverse()
        return bars
