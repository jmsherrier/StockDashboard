"""
yfinance provider — for development/testing ONLY.

yfinance is free and fast for prototyping, but it:
- Scrapes Yahoo Finance (unofficial, can break any time)
- Has aggressive rate limiting and IP bans
- Returns inconsistent data for some fields
- Has no SLA, no support, no guarantee

Use this during local development when you don't want to burn
FMP free-tier quota. Never deploy this as a production dependency.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from functools import partial
from typing import Optional, Sequence

from core.schemas import FundamentalData, OHLCVBar, QuoteSnapshot, StockInfo
from providers.base import (
    FundamentalsProvider,
    IntradayProvider,
    PriceProvider,
    UniverseProvider,
)

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore
    logger.warning("yfinance not installed. Install with: pip install yfinance")


def _run_sync(func, *args, **kwargs):
    """Run a synchronous yfinance call in the thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, partial(func, *args, **kwargs))


class YFinanceUniverseProvider(UniverseProvider):
    """
    Fetches stock universe from Wikipedia (S&P 500 + NASDAQ-100) using pandas.
    No API key required. Good enough for dev and small universes.
    """

    async def get_stock_list(
        self,
        exchange: Optional[str] = None,
        min_market_cap: Optional[float] = None,
    ) -> list[StockInfo]:
        import io
        import urllib.request

        import pandas as pd

        def _fetch_html_tables(url: str) -> list[pd.DataFrame]:
            """Fetch HTML tables with a proper User-Agent to avoid 403."""
            req = urllib.request.Request(url, headers={"User-Agent": "stock-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8")
            return pd.read_html(io.StringIO(html))

        loop = asyncio.get_event_loop()
        stocks: list[StockInfo] = []
        seen_symbols: set[str] = set()

        # Fetch S&P 500 from Wikipedia
        try:
            sp500_tables = await loop.run_in_executor(
                None,
                partial(_fetch_html_tables, "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"),
            )
            if sp500_tables:
                df = sp500_tables[0]
                for _, row in df.iterrows():
                    symbol = str(row.get("Symbol", "")).replace(".", "-")
                    if symbol and symbol not in seen_symbols:
                        seen_symbols.add(symbol)
                        stocks.append(StockInfo(
                            symbol=symbol,
                            name=str(row.get("Security", "")),
                            exchange=str(row.get("Exchange", "")),  # Not always present
                            sector=str(row.get("GICS Sector", "")),
                            industry=str(row.get("GICS Sub-Industry", "")),
                            country="US",
                        ))
            logger.info("Fetched %d S&P 500 stocks from Wikipedia", len(stocks))
        except Exception as e:
            logger.warning("Failed to fetch S&P 500 from Wikipedia: %s", e)

        # Fetch NASDAQ-100 from Wikipedia (adds ~40 more not in S&P 500)
        try:
            nasdaq_tables = await loop.run_in_executor(
                None,
                partial(_fetch_html_tables, "https://en.wikipedia.org/wiki/Nasdaq-100"),
            )
            added = 0
            if nasdaq_tables:
                # Find the table with ticker/symbol column
                for table in nasdaq_tables:
                    # Flatten MultiIndex columns if present
                    if hasattr(table.columns, 'levels'):
                        table.columns = [
                            str(c[-1]) if isinstance(c, tuple) else str(c)
                            for c in table.columns
                        ]
                    cols = [str(c).lower() for c in table.columns]
                    if "ticker" in cols or "symbol" in cols:
                        col = "Ticker" if "ticker" in cols else "Symbol"
                        for _, row in table.iterrows():
                            symbol = str(row.get(col, "")).replace(".", "-")
                            if symbol and symbol not in seen_symbols:
                                seen_symbols.add(symbol)
                                company = str(row.get("Company", row.get("Security", "")))
                                stocks.append(StockInfo(
                                    symbol=symbol,
                                    name=company,
                                    exchange="NASDAQ",
                                    country="US",
                                ))
                                added += 1
                        break
            logger.info("Fetched %d additional NASDAQ-100 stocks from Wikipedia", added)
        except Exception as e:
            logger.warning("Failed to fetch NASDAQ-100 from Wikipedia: %s", e)

        if not stocks:
            logger.error("Could not fetch any stock universe from Wikipedia")
            return []

        # Apply exchange filter
        if exchange:
            ex_upper = exchange.upper()
            stocks = [s for s in stocks if s.exchange and ex_upper in s.exchange.upper()]

        # Note: market cap filtering skipped here (Wikipedia doesn't provide it).
        # S&P 500 stocks all have market cap > $100M so the default filter is met.
        logger.info("Universe: %d stocks after filters", len(stocks))
        return stocks

    async def get_stock_profile(self, symbol: str) -> Optional[StockInfo]:
        if yf is None:
            return None
        try:
            ticker = yf.Ticker(symbol)
            info = await _run_sync(lambda: ticker.info)
            return StockInfo(
                symbol=symbol,
                name=info.get("longName", info.get("shortName", "")),
                exchange=info.get("exchange"),
                sector=info.get("sector"),
                industry=info.get("industry"),
                market_cap=info.get("marketCap"),
                country=info.get("country", "US"),
            )
        except Exception as e:
            logger.error("yfinance profile failed for %s: %s", symbol, e)
            return None


class YFinanceFundamentalsProvider(FundamentalsProvider):

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalData]:
        if yf is None:
            return None
        try:
            ticker = yf.Ticker(symbol)
            info = await _run_sync(lambda: ticker.info)
            return FundamentalData(
                symbol=symbol,
                snapshot_date=date.today(),
                market_cap=info.get("marketCap"),
                price=info.get("currentPrice", info.get("regularMarketPrice")),
                pe_ratio=info.get("trailingPE"),
                forward_pe=info.get("forwardPE"),
                peg_ratio=info.get("pegRatio"),
                price_to_book=info.get("priceToBook"),
                price_to_sales=info.get("priceToSalesTrailing12Months"),
                ev_to_ebitda=info.get("enterpriseToEbitda"),
                revenue_growth_yoy=info.get("revenueGrowth"),
                eps_growth_yoy=info.get("earningsGrowth"),
                gross_margin=info.get("grossMargins"),
                operating_margin=info.get("operatingMargins"),
                net_margin=info.get("profitMargins"),
                roe=info.get("returnOnEquity"),
                roa=info.get("returnOnAssets"),
                debt_to_equity=info.get("debtToEquity"),
                current_ratio=info.get("currentRatio"),
                quick_ratio=info.get("quickRatio"),
                free_cash_flow=info.get("freeCashflow"),
                dividend_yield=info.get("dividendYield"),
                payout_ratio=info.get("payoutRatio"),
                avg_volume_10d=info.get("averageVolume10days"),
                avg_volume_30d=info.get("averageVolume"),
                shares_outstanding=info.get("sharesOutstanding"),
                float_shares=info.get("floatShares"),
                insider_ownership=info.get("heldPercentInsiders"),
                institutional_ownership=info.get("heldPercentInstitutions"),
            )
        except Exception as e:
            logger.error("yfinance fundamentals failed for %s: %s", symbol, e)
            return None

    async def get_fundamentals_bulk(
        self, symbols: Sequence[str]
    ) -> list[FundamentalData]:
        results = []
        # yfinance is slow per-ticker; process sequentially with small delay
        for s in symbols:
            r = await self.get_fundamentals(s)
            if r:
                results.append(r)
            await asyncio.sleep(0.2)  # Avoid rate limiting
        return results


class YFinancePriceProvider(PriceProvider):

    async def get_daily_prices(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        if yf is None:
            return []
        try:
            ticker = yf.Ticker(symbol)
            kwargs = {"auto_adjust": False}
            if start_date:
                kwargs["start"] = start_date.isoformat()
            if end_date:
                kwargs["end"] = end_date.isoformat()
            else:
                kwargs["period"] = "1y"

            df = await _run_sync(lambda: ticker.history(**kwargs))
            if df is None or df.empty:
                return []

            bars = []
            for idx, row in df.iterrows():
                bars.append(OHLCVBar(
                    symbol=symbol,
                    timestamp=idx.to_pydatetime(),
                    open=row["Open"],
                    high=row["High"],
                    low=row["Low"],
                    close=row["Close"],
                    volume=int(row.get("Volume", 0)),
                    adj_close=row.get("Adj Close"),
                ))
            return bars
        except Exception as e:
            logger.error("yfinance prices failed for %s: %s", symbol, e)
            return []

    async def get_daily_prices_bulk(
        self,
        symbols: Sequence[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, list[OHLCVBar]]:
        results = {}
        for s in symbols:
            bars = await self.get_daily_prices(s, start_date, end_date)
            if bars:
                results[s] = bars
            await asyncio.sleep(0.1)
        return results


class YFinanceIntradayProvider(IntradayProvider):

    async def get_quote(self, symbol: str) -> Optional[QuoteSnapshot]:
        if yf is None:
            return None
        try:
            ticker = yf.Ticker(symbol)
            info = await _run_sync(lambda: ticker.info)
            return QuoteSnapshot(
                symbol=symbol,
                timestamp=datetime.now(),
                price=info.get("currentPrice", info.get("regularMarketPrice", 0)),
                volume=int(info.get("volume", info.get("regularMarketVolume", 0))),
                day_high=info.get("dayHigh"),
                day_low=info.get("dayLow"),
                prev_close=info.get("previousClose"),
                change_pct=info.get("regularMarketChangePercent"),
                bid=info.get("bid"),
                ask=info.get("ask"),
                bid_size=info.get("bidSize"),
                ask_size=info.get("askSize"),
            )
        except Exception as e:
            logger.error("yfinance quote failed for %s: %s", symbol, e)
            return None

    async def get_quotes_bulk(
        self, symbols: Sequence[str]
    ) -> list[QuoteSnapshot]:
        results = []
        for s in symbols:
            q = await self.get_quote(s)
            if q:
                results.append(q)
            await asyncio.sleep(0.2)
        return results

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "5min",
        start_date: Optional[date] = None,
    ) -> list[OHLCVBar]:
        if yf is None:
            return []
        try:
            ticker = yf.Ticker(symbol)
            # yfinance interval mapping
            yf_interval = interval.replace("min", "m").replace("hour", "h")
            df = await _run_sync(
                lambda: ticker.history(period="1d", interval=yf_interval)
            )
            if df is None or df.empty:
                return []
            bars = []
            for idx, row in df.iterrows():
                bars.append(OHLCVBar(
                    symbol=symbol,
                    timestamp=idx.to_pydatetime(),
                    open=row["Open"],
                    high=row["High"],
                    low=row["Low"],
                    close=row["Close"],
                    volume=int(row.get("Volume", 0)),
                ))
            return bars
        except Exception as e:
            logger.error("yfinance intraday failed for %s: %s", symbol, e)
            return []
