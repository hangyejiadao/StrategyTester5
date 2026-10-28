"""
MetaTrader 5 visual trade replay export.

After a backtest, the trades can be replayed inside the MetaTrader 5
terminal itself: this module converts the tester's deals into an ordered
list of open/close events and writes them to a CSV file. The companion
MQL5 script ``MQL5/TradeReplay.mq5`` reads that file on a terminal chart
and redraws the trades step by step (entry/exit arrows, entry-to-exit
trend lines, stop-loss / take-profit levels and profit labels).

``install_replay_assets`` copies the CSV into the terminal's
``MQL5/Files`` folder and the script into ``MQL5/Scripts`` so the replay
is ready to attach to a chart.
"""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import analytics

REPLAY_SCRIPT_NAME = "TradeReplay.mq5"


def build_replay_events(deals: Sequence[Any], orders: Sequence[Any]) -> List[Dict[str, Any]]:
    """
    Build chronological open/close replay events from raw deals.

    Stop-loss / take-profit levels are recovered from the order that opened
    the position (matched through the opening deal's order ticket) when the
    order history is available.
    """
    order_by_ticket = {}
    for order in orders or []:
        ticket = order.get("ticket") if isinstance(order, dict) else getattr(order, "ticket", None)
        if ticket is not None:
            order_by_ticket[int(ticket)] = order

    # Opening deal per position -> order ticket, to recover SL/TP levels.
    opening_order_ticket: Dict[int, int] = {}
    for deal in deals:
        entry = deal.get("entry") if isinstance(deal, dict) else getattr(deal, "entry", None)
        position_id = deal.get("position_id") if isinstance(deal, dict) else getattr(deal, "position_id", None)
        order_ticket = deal.get("order") if isinstance(deal, dict) else getattr(deal, "order", None)
        if entry == analytics.DEAL_ENTRY_IN and position_id:
            opening_order_ticket.setdefault(int(position_id), int(order_ticket or 0))

    events: List[Dict[str, Any]] = []
    for trade in analytics.pair_trades(deals):
        sl = tp = 0.0
        order = order_by_ticket.get(opening_order_ticket.get(trade["position_id"], 0))
        if order is not None:
            sl = float(order.get("sl", 0.0) if isinstance(order, dict) else getattr(order, "sl", 0.0))
            tp = float(order.get("tp", 0.0) if isinstance(order, dict) else getattr(order, "tp", 0.0))

        events.append(
            {
                "time": trade["open_time"],
                "symbol": trade["symbol"],
                "event": "open",
                "direction": trade["direction"],
                "price": trade["open_price"],
                "volume": trade["volume"],
                "sl": sl,
                "tp": tp,
                "profit": 0.0,
                "position_id": trade["position_id"],
            }
        )
        if trade["closed"] and trade["close_time"]:
            events.append(
                {
                    "time": trade["close_time"],
                    "symbol": trade["symbol"],
                    "event": "close",
                    "direction": trade["direction"],
                    "price": trade["close_price"],
                    "volume": trade["volume"],
                    "sl": sl,
                    "tp": tp,
                    "profit": trade["profit"],
                    "position_id": trade["position_id"],
                }
            )

    events.sort(key=lambda e: (e["time"], 0 if e["event"] == "open" else 1))
    return events


def export_mt5_replay(
    deals: Sequence[Any],
    orders: Sequence[Any],
    output_dir: str,
    bot_name: str = "strategy",
) -> Optional[Path]:
    """Write the replay events CSV into ``output_dir``; returns its path."""
    events = build_replay_events(deals, orders)
    if not events:
        return None

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / f"st5_replay_{bot_name}.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["time", "symbol", "event", "direction", "price", "volume", "sl", "tp", "profit", "position_id"]
        )
        for event in events:
            writer.writerow(
                [
                    event["time"],
                    event["symbol"],
                    event["event"],
                    event["direction"],
                    f"{event['price']:.8f}",
                    f"{event['volume']:.2f}",
                    f"{event['sl']:.8f}",
                    f"{event['tp']:.8f}",
                    f"{event['profit']:.2f}",
                    event["position_id"],
                ]
            )
    return csv_path


def install_replay_assets(parent_mt5: Any, csv_path: Path) -> List[str]:
    """
    Copy the replay CSV into the terminal's ``MQL5/Files`` folder and the
    ``TradeReplay.mq5`` script into ``MQL5/Scripts``. Best effort: returns
    the list of installed file paths (empty when the terminal data path is
    unavailable).
    """
    installed: List[str] = []
    try:
        terminal_info = parent_mt5.terminal_info()
        data_path = getattr(terminal_info, "data_path", None)
        if not data_path:
            return installed

        files_dir = Path(data_path) / "MQL5" / "Files"
        files_dir.mkdir(parents=True, exist_ok=True)
        target_csv = files_dir / csv_path.name
        shutil.copyfile(csv_path, target_csv)
        installed.append(str(target_csv))

        script_source = Path(__file__).resolve().parent / "MQL5" / REPLAY_SCRIPT_NAME
        if script_source.exists():
            scripts_dir = Path(data_path) / "MQL5" / "Scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            target_script = scripts_dir / REPLAY_SCRIPT_NAME
            shutil.copyfile(script_source, target_script)
            installed.append(str(target_script))
    except Exception:
        return installed
    return installed
