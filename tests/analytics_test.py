"""Unit tests for strategytester5.analytics (no MT5 terminal required)."""

from collections import namedtuple

import numpy as np
import pandas as pd

from strategytester5.analytics import (
    advanced_metrics,
    compute_excursions,
    pair_trades,
    trade_breakdowns,
)

Deal = namedtuple(
    "Deal",
    ["ticket", "order", "time", "time_msc", "type", "entry", "magic",
     "position_id", "reason", "volume", "price", "commission", "swap",
     "profit", "fee", "symbol", "comment", "external_id", "balance"],
)


def make_deal(**overrides):
    base = dict(
        ticket=1, order=1, time=1700000000, time_msc=1700000000000, type=0,
        entry=0, magic=7, position_id=100, reason=0, volume=0.1, price=2000.0,
        commission=0.0, swap=0.0, profit=0.0, fee=0.0, symbol="XAUUSD",
        comment="", external_id="", balance=10000.0,
    )
    base.update(overrides)
    return Deal(**base)


def sample_deals():
    return [
        # Balance deposit (type 2) must be ignored.
        make_deal(ticket=1, type=2, entry=0, position_id=0, profit=10000.0),
        # Long position 100: buy in at 2000, sell out at 2010, +100 profit.
        make_deal(ticket=2, type=0, entry=0, position_id=100, time=1700000000, price=2000.0),
        make_deal(ticket=3, type=1, entry=1, position_id=100, time=1700003600, price=2010.0, profit=100.0, commission=-1.0),
        # Short position 101: sell in at 2005, partial closes at 2000 (+50) and 1995 (+50).
        make_deal(ticket=4, type=1, entry=0, position_id=101, time=1700007200, price=2005.0, volume=0.2),
        make_deal(ticket=5, type=0, entry=1, position_id=101, time=1700010800, price=2000.0, volume=0.1, profit=50.0),
        make_deal(ticket=6, type=0, entry=1, position_id=101, time=1700014400, price=1995.0, volume=0.1, profit=50.0),
        # Losing long 102: -40.
        make_deal(ticket=7, type=0, entry=0, position_id=102, time=1700018000, price=2000.0, symbol="EURUSD"),
        make_deal(ticket=8, type=1, entry=1, position_id=102, time=1700021600, price=1996.0, profit=-40.0, symbol="EURUSD"),
    ]


def test_pair_trades_groups_and_aggregates():
    trades = pair_trades(sample_deals())
    assert len(trades) == 3

    long_trade = trades[0]
    assert long_trade["direction"] == "long"
    assert long_trade["closed"] is True
    assert long_trade["open_price"] == 2000.0
    assert long_trade["close_price"] == 2010.0
    assert long_trade["profit"] == 99.0  # 100 profit - 1 commission
    assert long_trade["duration_seconds"] == 3600

    short_trade = trades[1]
    assert short_trade["direction"] == "short"
    assert short_trade["closed"] is True
    assert short_trade["close_price"] == 1997.5  # VWAP of the two partial closes
    assert short_trade["profit"] == 100.0


def test_advanced_metrics_drawdown_and_ratios():
    times = np.arange(0, 6 * 3600, 3600, dtype=float) + 1700000000
    equity = np.array([10000.0, 11000.0, 9000.0, 9500.0, 12000.0, 12000.0])
    trades = pair_trades(sample_deals())
    metrics = advanced_metrics(equity, times=times, trades=trades, initial_deposit=10000.0)

    # Peak 11000 -> trough 9000 is an 18.18% drawdown lasting until recovery at index 4.
    assert abs(metrics["max_drawdown_pct"] - (2000.0 / 11000.0 * 100.0)) < 1e-9
    assert metrics["max_drawdown_duration_seconds"] == 3 * 3600
    assert metrics["ulcer_index"] > 0
    assert metrics["sharpe_annualized"] is not None
    assert metrics["win_rate_pct"] == 2 / 3 * 100
    assert metrics["sqn"] > 0


def test_trade_breakdowns_grouping():
    trades = pair_trades(sample_deals())
    breakdown = trade_breakdowns(trades)
    assert breakdown["by_symbol"]["XAUUSD"]["trades"] == 2
    assert breakdown["by_symbol"]["EURUSD"]["net_profit"] == -40.0
    assert breakdown["by_direction"]["short"]["trades"] == 1
    assert breakdown["best_trades"][0]["profit"] == 100.0
    assert breakdown["worst_trades"][0]["profit"] == -40.0


def test_compute_excursions_uses_bar_range():
    trades = pair_trades(sample_deals())
    bars = pd.DataFrame(
        {
            "time": [1700000000, 1700001800, 1700003600],
            "high": [2005.0, 2015.0, 2012.0],
            "low": [1998.0, 1990.0, 2001.0],
        }
    )
    enriched = compute_excursions(trades, {"XAUUSD": bars})
    long_trade = enriched[0]
    assert long_trade["mfe_price"] == 15.0  # 2015 high - 2000 entry
    assert long_trade["mae_price"] == 10.0  # 2000 entry - 1990 low
    # EURUSD trade has no bars and stays untouched.
    assert "mfe_price" not in enriched[2]


def test_replay_events_carry_sltp_and_profits(tmp_path=None):
    from collections import namedtuple as _nt

    from strategytester5.replay import build_replay_events, export_mt5_replay

    Order = _nt("Order", ["ticket", "sl", "tp"])
    deals = sample_deals()
    # The opening deal of position 100 has order ticket 1 -> attach SL/TP.
    orders = [Order(ticket=1, sl=1990.0, tp=2030.0)]
    events = build_replay_events(deals, orders)

    opens = [e for e in events if e["event"] == "open"]
    closes = [e for e in events if e["event"] == "close"]
    assert len(opens) == 3 and len(closes) == 3
    first_open = opens[0]
    assert first_open["sl"] == 1990.0 and first_open["tp"] == 2030.0
    assert events == sorted(events, key=lambda e: e["time"])

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = export_mt5_replay(deals, orders, tmp, "demo")
        assert path is not None and path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert lines[0].startswith("time,symbol,event")
        assert len(lines) == 1 + 6  # header + 3 opens + 3 closes
