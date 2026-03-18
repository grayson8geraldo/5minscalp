"""AMD session analysis — Asian (Accumulation), London (Manipulation), NY (Distribution)."""

import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Tuple

import pandas as pd
import pytz

from bot.config import TradingConfig

logger = logging.getLogger(__name__)

UTC = pytz.utc


@dataclass
class SessionRange:
    high: float
    low: float
    range_pct: float  # range as percentage of midpoint price
    candles: pd.DataFrame


@dataclass
class AMDContext:
    """Full AMD context for a trading day."""
    date: datetime
    symbol: str
    asian: Optional[SessionRange]
    london: Optional[SessionRange]
    asian_valid: bool  # False if range is too wide
    london_manipulation: Optional[str]  # "bullish_sweep" or "bearish_sweep" or None
    expected_ny_direction: Optional[str]  # "long" or "short"
    is_stock: bool = False  # True for stocks/ETFs (no 24h data)
    prev_day_bias: Optional[str] = None  # "long" or "short" based on prev day


def _parse_time(t: str) -> time:
    parts = t.split(":")
    return time(int(parts[0]), int(parts[1]))


def _get_session_candles(
    df: pd.DataFrame, date: datetime, start_str: str, end_str: str
) -> pd.DataFrame:
    """Filter candles belonging to a specific session on a given date (UTC)."""
    start_t = _parse_time(start_str)
    end_t = _parse_time(end_str)
    day_start = datetime.combine(date.date(), start_t, tzinfo=UTC)
    day_end = datetime.combine(date.date(), end_t, tzinfo=UTC)
    mask = (df.index >= day_start) & (df.index < day_end)
    return df.loc[mask]


def _build_range(candles: pd.DataFrame) -> Optional[SessionRange]:
    if candles.empty:
        return None
    h = candles["high"].max()
    l = candles["low"].min()
    mid = (h + l) / 2
    return SessionRange(
        high=h,
        low=l,
        range_pct=(h - l) / mid * 100 if mid > 0 else 0,
        candles=candles,
    )


def detect_london_manipulation(
    asian: SessionRange, london: SessionRange
) -> Optional[str]:
    """Detect if London swept Asian highs or lows.

    - If London low < Asian low and then recovered → bearish sweep (liquidity grab below)
      → expect NY to go LONG
    - If London high > Asian high and then pulled back → bullish sweep
      → expect NY to go SHORT
    """
    london_candles = london.candles
    if london_candles.empty:
        return None

    swept_low = london.low < asian.low
    swept_high = london.high > asian.high

    if swept_low and swept_high:
        # Both swept — ambiguous, skip
        return None

    last_close = london_candles["close"].iloc[-1]

    if swept_low and last_close > asian.low:
        return "bearish_sweep"  # swept lows → expect long
    if swept_high and last_close < asian.high:
        return "bullish_sweep"  # swept highs → expect short
    return None


def _is_stock_symbol(symbol: str) -> bool:
    """Stocks/ETFs don't have '=' in the ticker."""
    return "=" not in symbol


def _get_prev_day_bias(df: pd.DataFrame, date: datetime) -> Optional[str]:
    """Determine directional bias from previous trading day's price action.

    Looks at whether the previous day closed above or below its open,
    and whether it swept the prior day's high or low.
    """
    prev_date = date - pd.Timedelta(days=1)
    # Go back up to 4 days to find the last trading day
    for offset in range(1, 5):
        check_date = date - pd.Timedelta(days=offset)
        day_mask = df.index.date == check_date.date()
        day_candles = df.loc[day_mask]
        if len(day_candles) >= 5:
            day_open = day_candles["open"].iloc[0]
            day_close = day_candles["close"].iloc[-1]
            day_high = day_candles["high"].max()
            day_low = day_candles["low"].min()

            # Look for the day before that to detect sweeps
            for offset2 in range(offset + 1, offset + 5):
                prev_check = date - pd.Timedelta(days=offset2)
                prev_mask = df.index.date == prev_check.date()
                prev_candles = df.loc[prev_mask]
                if len(prev_candles) >= 5:
                    prev_high = prev_candles["high"].max()
                    prev_low = prev_candles["low"].min()

                    swept_low = day_low < prev_low and day_close > prev_low
                    swept_high = day_high > prev_high and day_close < prev_high

                    if swept_low and not swept_high:
                        return "long"  # Swept lows and recovered → bullish
                    if swept_high and not swept_low:
                        return "short"  # Swept highs and rejected → bearish
                    break

            # Fallback: simple close vs open
            if day_close > day_open:
                return "long"
            elif day_close < day_open:
                return "short"
            return None
    return None


def analyse_amd(
    df: pd.DataFrame, date: datetime, symbol: str, cfg: TradingConfig
) -> AMDContext:
    """Build the AMD context for a given day."""
    is_stock = _is_stock_symbol(symbol)

    asian_candles = _get_session_candles(df, date, cfg.asian_start, cfg.asian_end)
    london_candles = _get_session_candles(df, date, cfg.london_start, cfg.london_end)

    asian = _build_range(asian_candles)
    london = _build_range(london_candles)

    manipulation = None
    expected_dir = None
    prev_day_bias = None

    if is_stock:
        # Stocks have no Asian/London data — use previous day bias + ORB only
        asian_valid = True  # Don't filter out stocks
        prev_day_bias = _get_prev_day_bias(df, date)
        expected_dir = prev_day_bias  # Use prev day bias as direction hint
    else:
        # Forex: full AMD analysis
        asian_valid = asian is not None and asian.range_pct <= cfg.max_asian_range_pct

        if asian and london and asian_valid:
            manipulation = detect_london_manipulation(asian, london)
            if manipulation == "bearish_sweep":
                expected_dir = "long"
            elif manipulation == "bullish_sweep":
                expected_dir = "short"

    return AMDContext(
        date=date,
        symbol=symbol,
        asian=asian,
        london=london,
        asian_valid=asian_valid,
        london_manipulation=manipulation,
        expected_ny_direction=expected_dir,
        is_stock=is_stock,
        prev_day_bias=prev_day_bias,
    )
