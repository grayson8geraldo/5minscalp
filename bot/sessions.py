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


def analyse_amd(
    df: pd.DataFrame, date: datetime, symbol: str, cfg: TradingConfig
) -> AMDContext:
    """Build the AMD context for a given day."""
    asian_candles = _get_session_candles(df, date, cfg.asian_start, cfg.asian_end)
    london_candles = _get_session_candles(df, date, cfg.london_start, cfg.london_end)

    asian = _build_range(asian_candles)
    london = _build_range(london_candles)

    asian_valid = asian is not None and asian.range_pct <= cfg.max_asian_range_pct

    manipulation = None
    expected_dir = None

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
    )
