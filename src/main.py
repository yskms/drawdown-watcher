"""Daily production runner.

Recomputes state_machine.run() from scratch over each ticker's full price
history (see docs/architecture.md "Statelessness and stock splits"), then
emails only the events not already notified (see src/notification_state.py)
plus a heartbeat. config/state locations are passed in as plain paths --
see docs/architecture.md "State (per ticker)" for why the cloud storage
behind those paths (local file today; maybe S3/SSM once deployed, Phase 4)
is a separate decision from this runner's logic.

Usage:
    python -m src.main --config ../drawdown-watcher-private/config/config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.config import load_config, ticker_config
from src.drawdown import rolling_high
from src.market_data import fetch_history
from src.notification_state import event_key, load_state, save_state, select_new_events
from src.notifier import notify_error, notify_event, notify_heartbeat
from src.state_machine import run
from src.status import current_status


def process_ticker(ticker: str, cfg: dict, state: dict, dry_run: bool) -> tuple[str, pd.Timestamp]:
    """Notifies new events for one ticker and updates `state` in place.
    Returns its heartbeat status line and its latest trading date."""
    config = ticker_config(cfg)
    close = fetch_history(ticker, refresh=True).dropna()
    events = run(close, rolling_high(close), config)
    today = close.index[-1]

    notified_keys = state.setdefault(ticker, set())
    for event in select_new_events(events, notified_keys, today):
        if not dry_run:
            notify_event(ticker, event)
        notified_keys.add(event_key(event))

    return f"{ticker}: {current_status(close, events, config)}", today


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument("--state", default="data/notified_state.json")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="compute and print what would happen, but send no email and save no state",
    )
    args = parser.parse_args()

    load_dotenv()

    config_path = Path(args.config)
    state_path = Path(args.state)
    tickers_cfg = load_config(config_path)
    state = load_state(state_path)

    status_lines = []
    latest_date = None
    had_error = False

    for ticker, cfg in tickers_cfg.items():
        try:
            line, today = process_ticker(ticker, cfg, state, args.dry_run)
            status_lines.append(line)
            if latest_date is None or today > latest_date:
                latest_date = today
        except Exception as exc:  # noqa: BLE001 -- one ticker's failure must not stop the others
            had_error = True
            message = f"{ticker}: {exc}"
            print(f"ERROR  {message}", file=sys.stderr)
            if not args.dry_run:
                try:
                    notify_error(ticker, message)
                except Exception as notify_exc:  # noqa: BLE001 -- the error itself (e.g. SMTP down) may be why this fails
                    print(f"ERROR  could not send error notification: {notify_exc}", file=sys.stderr)

    if args.dry_run:
        print("\n".join(status_lines))
        return

    if latest_date is not None:
        save_state(state_path, state, latest_date)
    notify_heartbeat(status_lines)
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
