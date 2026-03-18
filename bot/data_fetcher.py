"""Fetch real market data via yfinance."""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_candles(
    symbol: str,
    interval: str = "5m",
    days: int = 5,
) -> Optional[pd.DataFrame]:
    """Fetch 5-min OHLCV candles for the last N days.

    yfinance allows max 60 days of 5m data.  We default to 5 for speed.
    """
    try:
        ticker = yf.Ticker(symbol)
        end = datetime.now(tz=pytz.utc)
        start = end - timedelta(days=days)
        df = ticker.history(start=start, end=end, interval=interval)
        if df.empty:
            logger.warning("No data for %s", symbol)
            return None

        df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
        df.columns = [c.lower() for c in df.columns]
        # keep only needed columns
        for col in ("dividends", "stock splits", "capital gains"):
            if col in df.columns:
                df.drop(columns=[col], inplace=True)
        return df
    except Exception as e:
        logger.error("Error fetching %s: %s", symbol, e)
        return None


def get_latest_price(symbol: str) -> Optional[float]:
    """Get the most recent closing price."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None
