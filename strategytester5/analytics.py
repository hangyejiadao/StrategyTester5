"""
Advanced analytics for StrategyTester5 backtest results.

This module adds the analysis layer that the basic tester statistics do not
cover:

* risk-adjusted performance metrics computed from the equity curve
  (Sharpe, Sortino, Calmar, Ulcer index, drawdown durations, ...),
* pairing of raw deals into round-trip trades,
* per-trade statistics (win rate, expectancy in R, SQN, VaR/CVaR of trade
  outcomes, holding-time distribution),
* breakdowns of trade performance by symbol, direction, entry hour and
  weekday,
* maximum adverse / favourable excursion (MAE / MFE) per trade, computed
  from bar data over the holding period.

Everything here is pure computation over plain Python / NumPy data, so it
can be unit-tested without a MetaTrader 5 terminal.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

# MetaTrader 5 deal constants (platform values).
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2

_EPS = 1e-12


def _deal_field(deal: Any, name: str, default: Any = 0) -> Any:
    """Read a field from a deal given as a namedtuple or as a dict."""
    if isinstance(deal, dict):
        return deal.get(name, default)
    return getattr(deal, name, default)


def pair_trades(deals: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    Pair raw deals into round-trip trades keyed by ``position_id``.

    Balance operations and deals without a position id are ignored. Partial
    closes are aggregated: the close price is the volume-weighted average of
    the closing deals and the close time is the last closing deal. A trade
    whose closing volume does not yet cover the opened volume is reported
    with ``closed=False``.

    Returns a list of trade dictionaries sorted by open time.
    """
    grouped: Dict[int, List[Any]] = defaultdict(list)
    for deal in deals:
        deal_type = _deal_field(deal, "type", -1)
        position_id = _deal_field(deal, "position_id", 0)
        if deal_type not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL) or not position_id:
            continue
        grouped[int(position_id)].append(deal)

    trades: List[Dict[str, Any]] = []
    for position_id, rows in grouped.items():
        rows.sort(key=lambda d: (_deal_field(d, "time", 0), _deal_field(d, "time_msc", 0)))
        opening = [d for d in rows if _deal_field(d, "entry") in (DEAL_ENTRY_IN, DEAL_ENTRY_INOUT)]
        closing = [d for d in rows if _deal_field(d, "entry") in (DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT)]
        if not opening:
            continue

        first_open = opening[0]
        direction = "long" if _deal_field(first_open, "type") == DEAL_TYPE_BUY else "short"

        open_volume = sum(float(_deal_field(d, "volume", 0.0)) for d in opening)
        close_volume = sum(float(_deal_field(d, "volume", 0.0)) for d in closing)
        if open_volume <= 0:
            continue

        def _vwap(subset: List[Any]) -> float:
            total_volume = sum(float(_deal_field(d, "volume", 0.0)) for d in subset)
            if total_volume <= 0:
                return float(_deal_field(subset[0], "price", 0.0)) if subset else 0.0
            return sum(
                float(_deal_field(d, "price", 0.0)) * float(_deal_field(d, "volume", 0.0))
                for d in subset
            ) / total_volume

        open_time = int(_deal_field(first_open, "time", 0))
        close_time = int(_deal_field(closing[-1], "time", 0)) if closing else None
        net_profit = sum(
            float(_deal_field(d, "profit", 0.0))
            + float(_deal_field(d, "commission", 0.0))
            + float(_deal_field(d, "swap", 0.0))
            + float(_deal_field(d, "fee", 0.0))
            for d in rows
        )

        trades.append(
            {
                "position_id": position_id,
                "symbol": _deal_field(first_open, "symbol", ""),
                "direction": direction,
                "magic": int(_deal_field(first_open, "magic", 0)),
                "comment": _deal_field(first_open, "comment", ""),
                "volume": open_volume,
                "open_time": open_time,
                "open_price": _vwap(opening),
                "close_time": close_time,
                "close_price": _vwap(closing) if closing else None,
                "profit": net_profit,
                "closed": bool(closing) and close_volume >= open_volume - 1e-9,
                "duration_seconds": (close_time - open_time) if close_time else None,
                "exit_reason": int(_deal_field(closing[-1], "reason", 0)) if closing else None,
            }
        )

    trades.sort(key=lambda t: t["open_time"])
    return trades


def _drawdown_episodes(curve: np.ndarray, times: Optional[np.ndarray]) -> List[Dict[str, float]]:
    """Split a balance/equity curve into drawdown episodes (peak to recovery)."""
    episodes: List[Dict[str, float]] = []
    if curve.size == 0:
        return episodes

    peak_value = curve[0]
    peak_index = 0
    in_drawdown = False
    trough_value = curve[0]
    trough_index = 0

    for i in range(1, curve.size):
        value = curve[i]
        if not in_drawdown:
            if value >= peak_value:
                peak_value = value
                peak_index = i
            else:
                in_drawdown = True
                trough_value = value
                trough_index = i
        else:
            if value < trough_value:
                trough_value = value
                trough_index = i
            if value >= peak_value:
                episodes.append(
                    _episode(peak_index, trough_index, i, peak_value, trough_value, times, recovered=True)
                )
                in_drawdown = False
                peak_value = value
                peak_index = i

    if in_drawdown:
        episodes.append(
            _episode(peak_index, trough_index, curve.size - 1, peak_value, trough_value, times, recovered=False)
        )
    return episodes


def _episode(peak_i: int, trough_i: int, end_i: int, peak_v: float, trough_v: float,
             times: Optional[np.ndarray], recovered: bool) -> Dict[str, float]:
    def _span(a: int, b: int) -> float:
        if times is not None and times.size > max(a, b):
            return float(times[b] - times[a])
        return float(b - a)

    return {
        "depth_money": float(peak_v - trough_v),
        "depth_pct": float((peak_v - trough_v) / peak_v * 100.0) if peak_v > _EPS else 0.0,
        "duration_seconds": _span(peak_i, end_i),
        "decline_seconds": _span(peak_i, trough_i),
        "recovery_seconds": _span(trough_i, end_i) if recovered else 0.0,
        "recovered": recovered,
    }


def advanced_metrics(
    equity_curve: Sequence[float],
    balance_curve: Optional[Sequence[float]] = None,
    times: Optional[Sequence[float]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
    initial_deposit: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute risk-adjusted performance metrics for a finished backtest.

    ``times`` are the epoch-second timestamps matching the curve points; when
    given, ratios are annualised using the median sampling interval and
    drawdown durations are reported in seconds, otherwise durations fall
    back to curve-point counts and annualised fields are ``None``.
    """
    equity = np.asarray(equity_curve, dtype=np.float64).reshape(-1)
    result: Dict[str, Any] = {}
    if equity.size < 2:
        return result

    time_arr = np.asarray(times, dtype=np.float64).reshape(-1) if times is not None else None
    if time_arr is not None and time_arr.size != equity.size:
        time_arr = None

    # Per-period simple returns on the equity curve.
    previous = equity[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.where(np.abs(previous) > _EPS, np.diff(equity) / np.abs(previous), 0.0)
    returns = returns[np.isfinite(returns)]

    periods_per_year: Optional[float] = None
    if time_arr is not None and time_arr.size > 2:
        steps = np.diff(time_arr)
        steps = steps[steps > 0]
        if steps.size:
            median_step = float(np.median(steps))
            if median_step > 0:
                periods_per_year = 365.25 * 24 * 3600 / median_step

    if returns.size >= 2:
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))
        result["sharpe_per_period"] = mean_ret / std_ret if std_ret > _EPS else 0.0
        downside = returns[returns < 0]
        downside_dev = float(np.sqrt(np.mean(np.square(downside)))) if downside.size else 0.0
        result["sortino_per_period"] = mean_ret / downside_dev if downside_dev > _EPS else 0.0
        if periods_per_year:
            annual_factor = math.sqrt(periods_per_year)
            result["sharpe_annualized"] = result["sharpe_per_period"] * annual_factor
            result["sortino_annualized"] = result["sortino_per_period"] * annual_factor
            total_return = float(equity[-1] / equity[0] - 1.0) if abs(equity[0]) > _EPS else 0.0
            years = (time_arr[-1] - time_arr[0]) / (365.25 * 24 * 3600) if time_arr is not None else 0.0
            if years > 0 and total_return > -1.0:
                result["cagr_pct"] = float(((1.0 + total_return) ** (1.0 / years) - 1.0) * 100.0)
        else:
            result["sharpe_annualized"] = None
            result["sortino_annualized"] = None

    # Drawdown analysis on the equity curve.
    episodes = _drawdown_episodes(equity, time_arr)
    if episodes:
        deepest = max(episodes, key=lambda e: e["depth_pct"])
        result["max_drawdown_pct"] = deepest["depth_pct"]
        result["max_drawdown_money"] = deepest["depth_money"]
        result["max_drawdown_duration_seconds"] = max(e["duration_seconds"] for e in episodes)
        result["average_drawdown_duration_seconds"] = float(
            np.mean([e["duration_seconds"] for e in episodes])
        )
        result["drawdown_episodes"] = len(episodes)
        total_span = float(time_arr[-1] - time_arr[0]) if time_arr is not None else float(equity.size - 1)
        if total_span > 0:
            result["time_in_drawdown_pct"] = float(
                sum(e["duration_seconds"] for e in episodes) / total_span * 100.0
            )
        if result.get("cagr_pct") is not None and deepest["depth_pct"] > _EPS:
            result["calmar_ratio"] = result["cagr_pct"] / deepest["depth_pct"]

    # Ulcer index: RMS of the percentage drawdown from the running peak.
    running_peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd_pct = np.where(running_peak > _EPS, (running_peak - equity) / running_peak * 100.0, 0.0)
    result["ulcer_index"] = float(np.sqrt(np.mean(np.square(dd_pct)))) if dd_pct.size else 0.0

    if trades:
        result.update(_trade_metrics([t for t in trades if t.get("closed", True)]))
    return result


def _trade_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Trade-outcome statistics: win rate, expectancy in R, SQN, VaR/CVaR."""
    out: Dict[str, Any] = {}
    if not trades:
        return out

    profits = np.array([float(t["profit"]) for t in trades], dtype=np.float64)
    wins = profits[profits > 0]
    losses = profits[profits < 0]
    out["win_rate_pct"] = float(wins.size / profits.size * 100.0)
    out["average_win"] = float(np.mean(wins)) if wins.size else 0.0
    out["average_loss"] = float(np.mean(losses)) if losses.size else 0.0
    if wins.size and losses.size:
        out["payoff_ratio"] = float(np.mean(wins) / abs(np.mean(losses)))
        # Expectancy in R multiples, one R being the average loss magnitude.
        r_unit = abs(float(np.mean(losses)))
        if r_unit > _EPS:
            out["expectancy_r"] = float(np.mean(profits) / r_unit)
    std_profit = float(np.std(profits, ddof=1)) if profits.size > 1 else 0.0
    if std_profit > _EPS:
        out["sqn"] = float(np.mean(profits) / std_profit * math.sqrt(profits.size))
    if profits.size >= 5:
        out["var_95"] = float(np.percentile(profits, 5))
        tail = profits[profits <= out["var_95"]]
        out["cvar_95"] = float(np.mean(tail)) if tail.size else out["var_95"]
    durations = [t["duration_seconds"] for t in trades if t.get("duration_seconds") is not None]
    if durations:
        out["average_holding_seconds"] = float(np.mean(durations))
        out["median_holding_seconds"] = float(np.median(durations))
        out["max_holding_seconds"] = float(np.max(durations))
    return out


def trade_breakdowns(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate closed-trade performance by symbol, direction, entry hour
    (UTC) and weekday, plus the best and worst individual trades.
    """
    closed = [t for t in trades if t.get("closed", True)]

    def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        profits = [float(t["profit"]) for t in rows]
        wins = [p for p in profits if p > 0]
        return {
            "trades": len(rows),
            "net_profit": float(sum(profits)),
            "win_rate_pct": float(len(wins) / len(rows) * 100.0) if rows else 0.0,
            "average_profit": float(np.mean(profits)) if profits else 0.0,
        }

    def _group(key_fn) -> Dict[str, Any]:
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for trade in closed:
            buckets[key_fn(trade)].append(trade)
        return {key: _aggregate(rows) for key, rows in sorted(buckets.items())}

    breakdown = {
        "by_symbol": _group(lambda t: str(t["symbol"])),
        "by_direction": _group(lambda t: str(t["direction"])),
        "by_entry_hour_utc": _group(
            lambda t: f"{datetime.fromtimestamp(t['open_time'], tz=timezone.utc).hour:02d}"
        ),
        "by_weekday": _group(
            lambda t: datetime.fromtimestamp(t["open_time"], tz=timezone.utc).strftime("%A")
        ),
    }
    if closed:
        ordered = sorted(closed, key=lambda t: float(t["profit"]))
        breakdown["worst_trades"] = ordered[:5]
        breakdown["best_trades"] = list(reversed(ordered[-5:]))
    return breakdown


def compute_excursions(
    trades: List[Dict[str, Any]],
    bars_by_symbol: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Attach maximum adverse / favourable excursion (MAE / MFE, in price
    units) to each closed trade using bar highs and lows over its holding
    period. ``bars_by_symbol`` maps a symbol to a pandas DataFrame with
    ``time`` (epoch seconds), ``high`` and ``low`` columns. Trades whose
    symbol has no bar data are returned unchanged.
    """
    enriched: List[Dict[str, Any]] = []
    for trade in trades:
        trade = dict(trade)
        bars = bars_by_symbol.get(trade.get("symbol", ""))
        if bars is not None and trade.get("close_time"):
            window = bars[(bars["time"] >= trade["open_time"]) & (bars["time"] <= trade["close_time"])]
            if len(window):
                entry = float(trade["open_price"])
                highest = float(window["high"].max())
                lowest = float(window["low"].min())
                if trade["direction"] == "long":
                    trade["mfe_price"] = highest - entry
                    trade["mae_price"] = entry - lowest
                else:
                    trade["mfe_price"] = entry - lowest
                    trade["mae_price"] = highest - entry
        enriched.append(trade)
    return enriched
