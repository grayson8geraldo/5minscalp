"""Three entry models: Support/Resistance, Supply/Demand, Open Range Breakout."""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
import pytz

from bot.config import TradingConfig
from bot.patterns import EngulfingSignal, detect_engulfing, is_fair_value_gap
from bot.sessions import AMDContext, SessionRange

logger = logging.getLogger(__name__)
UTC = pytz.utc


@dataclass
class TradeSignal:
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    model: str  # "SR", "SD", "ORB"
    timestamp: pd.Timestamp
    engulfing: EngulfingSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_sr_levels(df: pd.DataFrame, lookback: int = 50) -> List[float]:
    """Find basic support/resistance levels using recent swing highs/lows."""
    if len(df) < 5:
        return []
    window = min(lookback, len(df))
    subset = df.iloc[-window:]
    levels = []

    for i in range(2, len(subset) - 2):
        h = subset["high"].iloc
        l = subset["low"].iloc

        # Swing high
        if h[i] > h[i - 1] and h[i] > h[i - 2] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            levels.append(h[i])
        # Swing low
        if l[i] < l[i - 1] and l[i] < l[i - 2] and l[i] < l[i + 1] and l[i] < l[i + 2]:
            levels.append(l[i])

    return levels


def _price_near_level(price: float, level: float, tolerance_pct: float = 0.1) -> bool:
    return abs(price - level) / level * 100 <= tolerance_pct


# ---------------------------------------------------------------------------
# Model 1: Support & Resistance
# ---------------------------------------------------------------------------

def check_sr_model(
    df: pd.DataFrame, amd: AMDContext, cfg: TradingConfig
) -> Optional[TradeSignal]:
    """S/R model: price returns to a broken S/R level + engulfing confirmation."""
    if not amd.expected_ny_direction or not amd.asian:
        return None

    direction = amd.expected_ny_direction
    eng_dir = "bullish" if direction == "long" else "bearish"

    levels = _find_sr_levels(df)
    if not levels:
        return None

    engulfing = detect_engulfing(df, eng_dir)
    if not engulfing:
        return None

    # Check if the engulfing candle is near a known S/R level
    trigger_price = engulfing.close_price
    for level in levels:
        if _price_near_level(trigger_price, level, tolerance_pct=0.15):
            sl, tp = _compute_sl_tp(direction, trigger_price, level, cfg)
            return TradeSignal(
                symbol=amd.symbol,
                direction=direction,
                entry_price=trigger_price,
                stop_loss=sl,
                take_profit=tp,
                model="SR",
                timestamp=engulfing.trigger_time,
                engulfing=engulfing,
            )
    return None


# ---------------------------------------------------------------------------
# Model 2: Supply & Demand
# ---------------------------------------------------------------------------

def _find_demand_zone(df: pd.DataFrame, end_idx: int) -> Optional[tuple]:
    """Find a recent demand zone (strong bullish impulse leaving FVG)."""
    for i in range(end_idx - 1, max(end_idx - 30, 2), -1):
        candle = df.iloc[i]
        body = abs(candle["close"] - candle["open"])
        full_range = candle["high"] - candle["low"]
        if full_range == 0:
            continue
        # Strong impulse candle (large body ratio)
        if body / full_range > 0.6 and candle["close"] > candle["open"]:
            if is_fair_value_gap(df, i):
                zone_low = candle["low"]
                zone_high = candle["open"]
                return (zone_low, zone_high)
    return None


def _find_supply_zone(df: pd.DataFrame, end_idx: int) -> Optional[tuple]:
    """Find a recent supply zone (strong bearish impulse leaving FVG)."""
    for i in range(end_idx - 1, max(end_idx - 30, 2), -1):
        candle = df.iloc[i]
        body = abs(candle["close"] - candle["open"])
        full_range = candle["high"] - candle["low"]
        if full_range == 0:
            continue
        if body / full_range > 0.6 and candle["close"] < candle["open"]:
            if is_fair_value_gap(df, i):
                zone_low = candle["open"]
                zone_high = candle["high"]
                return (zone_low, zone_high)
    return None


def check_sd_model(
    df: pd.DataFrame, amd: AMDContext, cfg: TradingConfig
) -> Optional[TradeSignal]:
    """Supply/Demand model: price retraces to a demand/supply zone + engulfing."""
    if not amd.expected_ny_direction:
        return None

    direction = amd.expected_ny_direction
    eng_dir = "bullish" if direction == "long" else "bearish"

    engulfing = detect_engulfing(df, eng_dir)
    if not engulfing:
        return None

    idx = engulfing.trigger_idx
    trigger_price = engulfing.close_price

    if direction == "long":
        zone = _find_demand_zone(df, idx)
        if zone and zone[0] <= trigger_price <= zone[1] * 1.002:
            sl = zone[0] - (zone[1] - zone[0]) * 0.2
            dist = trigger_price - sl
            tp = trigger_price + dist * cfg.risk_reward_ratio
            return TradeSignal(
                symbol=amd.symbol, direction=direction,
                entry_price=trigger_price, stop_loss=sl, take_profit=tp,
                model="SD", timestamp=engulfing.trigger_time, engulfing=engulfing,
            )
    else:
        zone = _find_supply_zone(df, idx)
        if zone and zone[0] * 0.998 <= trigger_price <= zone[1]:
            sl = zone[1] + (zone[1] - zone[0]) * 0.2
            dist = sl - trigger_price
            tp = trigger_price - dist * cfg.risk_reward_ratio
            return TradeSignal(
                symbol=amd.symbol, direction=direction,
                entry_price=trigger_price, stop_loss=sl, take_profit=tp,
                model="SD", timestamp=engulfing.trigger_time, engulfing=engulfing,
            )

    return None


# ---------------------------------------------------------------------------
# Model 3: Open Range Breakout (ORB)
# ---------------------------------------------------------------------------

def check_orb_model(
    df: pd.DataFrame, amd: AMDContext, cfg: TradingConfig
) -> Optional[TradeSignal]:
    """ORB model: breakout of first 15 min of NY session, pullback + engulfing."""
    if not amd.expected_ny_direction:
        return None

    direction = amd.expected_ny_direction

    # Get ORB range: first 3 five-minute candles of NY session
    ny_start_t = time(13, 30, tzinfo=UTC)
    ny_orb_end_t = time(13, 45, tzinfo=UTC)

    day = amd.date.date()
    orb_start = datetime.combine(day, ny_start_t.replace(tzinfo=None), tzinfo=UTC)
    orb_end = datetime.combine(day, ny_orb_end_t.replace(tzinfo=None), tzinfo=UTC)

    orb_candles = df.loc[(df.index >= orb_start) & (df.index < orb_end)]
    if len(orb_candles) < cfg.orb_candles:
        return None

    orb_high = orb_candles["high"].max()
    orb_low = orb_candles["low"].min()

    # Look at candles after ORB
    after_orb = df.loc[df.index >= orb_end]
    if len(after_orb) < 3:
        return None

    eng_dir = "bullish" if direction == "long" else "bearish"
    engulfing = detect_engulfing(after_orb, eng_dir)
    if not engulfing:
        return None

    trigger_price = engulfing.close_price

    if direction == "long":
        broke_high = after_orb["high"].max() > orb_high
        pullback = trigger_price <= orb_high * 1.003
        if broke_high and pullback:
            sl = orb_low
            dist = trigger_price - sl
            tp = trigger_price + dist * cfg.risk_reward_ratio
            return TradeSignal(
                symbol=amd.symbol, direction=direction,
                entry_price=trigger_price, stop_loss=sl, take_profit=tp,
                model="ORB", timestamp=engulfing.trigger_time, engulfing=engulfing,
            )
    else:
        broke_low = after_orb["low"].min() < orb_low
        pullback = trigger_price >= orb_low * 0.997
        if broke_low and pullback:
            sl = orb_high
            dist = sl - trigger_price
            tp = trigger_price - dist * cfg.risk_reward_ratio
            return TradeSignal(
                symbol=amd.symbol, direction=direction,
                entry_price=trigger_price, stop_loss=sl, take_profit=tp,
                model="ORB", timestamp=engulfing.trigger_time, engulfing=engulfing,
            )

    return None


# ---------------------------------------------------------------------------
# Aggregate: try all models
# ---------------------------------------------------------------------------

def find_signals(
    df: pd.DataFrame, amd: AMDContext, cfg: TradingConfig
) -> List[TradeSignal]:
    """Run all three entry models and return any valid signals."""
    signals: List[TradeSignal] = []

    for checker in (check_sr_model, check_sd_model, check_orb_model):
        sig = checker(df, amd, cfg)
        if sig:
            signals.append(sig)
            logger.info(
                "Signal [%s] %s %s @ %.5f  SL=%.5f  TP=%.5f",
                sig.model, sig.direction, sig.symbol,
                sig.entry_price, sig.stop_loss, sig.take_profit,
            )

    return signals


def _compute_sl_tp(
    direction: str, entry: float, ref_level: float, cfg: TradingConfig
):
    """Compute stop-loss & take-profit from a reference S/R level.

    Uses a minimum SL distance of 0.1% of price so that trades near the
    exact S/R level still get a practical stop-loss.
    """
    min_sl_dist = entry * 0.001  # 0.1% of price (~10 pips on majors)

    if direction == "long":
        raw_dist = abs(entry - ref_level) * 1.3
        dist = max(raw_dist, min_sl_dist)
        sl = entry - dist
        tp = entry + dist * cfg.risk_reward_ratio
    else:
        raw_dist = abs(entry - ref_level) * 1.3
        dist = max(raw_dist, min_sl_dist)
        sl = entry + dist
        tp = entry - dist * cfg.risk_reward_ratio
    return sl, tp
