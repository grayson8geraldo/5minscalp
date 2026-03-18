"""Candlestick pattern detection — Engulfing pattern is the primary trigger."""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class EngulfingSignal:
    direction: str  # "bullish" or "bearish"
    trigger_idx: int  # index position in dataframe
    trigger_time: pd.Timestamp
    open_price: float
    close_price: float
    prev_open: float
    prev_close: float


def detect_engulfing(df: pd.DataFrame, direction: str) -> Optional[EngulfingSignal]:
    """Scan the last few candles for an engulfing pattern matching `direction`.

    Bullish engulfing: current green candle body fully covers prev red candle body.
    Bearish engulfing: current red candle body fully covers prev green candle body.

    Returns the most recent signal found (if any).
    """
    if len(df) < 2:
        return None

    # Scan last 10 candles (most recent first) to find a fresh signal
    lookback = min(10, len(df))
    for i in range(len(df) - 1, len(df) - lookback, -1):
        curr = df.iloc[i]
        prev = df.iloc[i - 1]

        c_open, c_close = curr["open"], curr["close"]
        p_open, p_close = prev["open"], prev["close"]

        if direction == "bullish":
            # Previous must be red, current must be green
            if p_close >= p_open:
                continue
            if c_close <= c_open:
                continue
            # Current body engulfs previous body
            if c_close > p_open and c_open < p_close:
                return EngulfingSignal(
                    direction="bullish",
                    trigger_idx=i,
                    trigger_time=df.index[i],
                    open_price=c_open,
                    close_price=c_close,
                    prev_open=p_open,
                    prev_close=p_close,
                )

        elif direction == "bearish":
            # Previous must be green, current must be red
            if p_close <= p_open:
                continue
            if c_close >= c_open:
                continue
            # Current body engulfs previous body
            if c_open > p_close and c_close < p_open:
                return EngulfingSignal(
                    direction="bearish",
                    trigger_idx=i,
                    trigger_time=df.index[i],
                    open_price=c_open,
                    close_price=c_close,
                    prev_open=p_open,
                    prev_close=p_close,
                )

    return None


def is_fair_value_gap(df: pd.DataFrame, idx: int) -> bool:
    """Check if candle at idx has a Fair Value Gap (imbalance).

    FVG bullish: candle[idx-2].high < candle[idx].low  (gap between wicks)
    FVG bearish: candle[idx-2].low > candle[idx].high
    """
    if idx < 2 or idx >= len(df):
        return False

    c0 = df.iloc[idx - 2]
    c2 = df.iloc[idx]

    # Bullish FVG
    if c0["high"] < c2["low"]:
        return True
    # Bearish FVG
    if c0["low"] > c2["high"]:
        return True

    return False
