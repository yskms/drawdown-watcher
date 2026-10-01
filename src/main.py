"""Daily production runner.

Recomputes state_machine.run() from scratch over each ticker's full price
history (see docs/architecture.md "Statelessness and stock splits"), then
emails only the events not already notified (see src/notification_state.py)
plus a heartbeat. config/state locations are passed in as plain paths --
see docs/architecture.md "State (per ticker)" for why where those paths
resolve to (a local file in dev; the private repo, committed back after
each run, in production -- see "Deployment") is a separate decision from
this runner's logic.

Must only run after the US market has fully closed -- see docs/architecture.md
"Deployment" (yfinance can return a non-final price for the current day
while the market is open, and dropna() does not catch that: it's only NaN
rows, not intraday-and-therefore-not-yet-final ones, that get dropped). A
real (non-dry-run) invocation during NYSE regular hours, or for a couple
of hours past the close, is refused outright (see `_refuse_if_market_open`)
rather than relying solely on the scheduler's own timing -- it fails
closed, as a backstop against e.g. a manual run (GitHub Actions'
`workflow_dispatch`) triggered at the wrong time of day.

Usage:
    python -m src.main --config ../drawdown-watcher-private/config/config.yaml
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from src.config import load_config, ticker_config
from src.drawdown import rolling_high
from src.event_format import format_event
from src.market_data import fetch_history
from src.notification_state import event_key, load_state, save_state, select_new_events
from src.notifier import notify_error, notify_event, notify_heartbeat
from src.state_machine import run
from src.status import current_status

# A long weekend plus a holiday, with a day of slack -- generous enough to
# never false-alarm on an ordinary gap, but still catch a data source that's
# actually stuck (see docs/architecture.md "Notifications": the heartbeat is
# the main defense against a silent failure, so it has to be able to tell
# "quiet market" apart from "broken pipe").
STALE_AFTER_DAYS = 5
# A couple of trailing rows can legitimately disappear between runs (e.g. a
# not-yet-final row from yesterday's refresh getting replaced); a bigger drop
# than that suggests the data source handed back a truncated history.
ROW_COUNT_DROP_TOLERANCE = 5

_NYSE_OPEN = time(9, 30)
# Not the literal 16:00 close -- the close itself isn't necessarily final
# the moment the bell rings (settlement/reporting lag), so this leaves the
# same couple of hours' margin the production schedule itself relies on
# (see docs/architecture.md "Deployment").
_SAFE_TO_RUN_FROM = time(18, 0)


def _refuse_if_market_open(now: datetime | None = None) -> None:
    """Raises if `now` (default: actual current time) falls within NYSE
    regular hours, or the margin past the close before a day's price is
    reliably final -- an event computed from a non-final price would be
    emailed and recorded as already-sent, with no way to retract it once
    the real close comes in (see docs/architecture.md "Deployment"). A
    coarse weekday + hours check, not a full holiday calendar: refusing on
    a market holiday afternoon is a harmless false positive, not a risk --
    it fails closed either way. `now` is a seam for tests; production code
    always calls this with no argument."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() < 5 and _NYSE_OPEN <= now.time() < _SAFE_TO_RUN_FROM:
        raise RuntimeError(
            f"refusing to run this close to NYSE hours ({now.strftime('%H:%M %Z')}) -- "
            'see docs/architecture.md "Deployment"'
        )


def process_ticker(
    ticker: str, cfg: dict, state: dict, dry_run: bool
) -> tuple[str, pd.Timestamp, list[dict], list[dict]]:
    """Notifies new events for one ticker and updates `state` in place.
    Returns (heartbeat status line, latest trading date, events notified or
    that would be notified this run, events seeded silently -- see below)."""
    config = ticker_config(cfg)
    close = fetch_history(ticker, refresh=True).dropna()
    today = close.index[-1]

    staleness_days = (pd.Timestamp.now().normalize() - today).days
    if staleness_days > STALE_AFTER_DAYS:
        raise RuntimeError(
            f"latest close is {today.date()} ({staleness_days}d old) -- data may be stuck"
        )

    # The baseline for this check lives in `state`, not the (mutable, already
    # overwritten by the fetch above) price cache file: if the row count were
    # read from that file, a truncated fetch would both raise *and* become
    # the new on-disk baseline, so a data source stuck returning the same
    # truncated history would only ever be caught on the first bad day.
    # Keeping last-known-good in `state` means it's never overwritten by a
    # bad fetch -- only by a fetch that passes this very check, below.
    #
    # Read-only (`.get`, not `state[ticker]` / `setdefault`) until every
    # check below has passed: creating the entry early would make a ticker
    # that failed on its very first attempt look like an already-seen
    # ticker to the *next* run (ticker present in `state` => not first-run
    # => no seeding), so a data source hiccup on day one could turn into a
    # same-size notification backlog once it recovers on day two.
    is_first_run = ticker not in state
    previous_rows = state.get(ticker, {}).get("last_row_count")
    if previous_rows is not None and len(close) < previous_rows - ROW_COUNT_DROP_TOLERANCE:
        raise RuntimeError(
            f"row count dropped from {previous_rows} to {len(close)} -- "
            "possible truncated history from the data source. If this is "
            "expected (e.g. the data source legitimately shortened its "
            "history), clear this ticker's last_row_count in the state file "
            "to recover."
        )

    events = run(close, rolling_high(close), config)

    entry = state.setdefault(
        ticker, {"notified_event_keys": set(), "last_updated": None, "last_row_count": None}
    )
    entry["last_row_count"] = len(close)

    # The very first run for a ticker (or one recovering from a lost state
    # file) would otherwise treat up to WINDOW_DAYS of past history as if it
    # just happened -- e.g. a month-old RECOVERY_CONFIRMED arriving with the
    # same urgency as today's. Seed it as already-known instead of notifying
    # it -- except for anything dated today, which is sent regardless, so a
    # live event happening on the very day state was lost is never silently
    # swallowed into history.
    notified_keys = entry["notified_event_keys"]
    candidates = select_new_events(events, notified_keys, today)
    notified, seeded = [], []
    for event in candidates:
        if is_first_run and event["date"] != today:
            seeded.append(event)
        else:
            if not dry_run:
                notify_event(ticker, event)
            notified.append(event)
        # Added right after this event is handled (not in a separate pass
        # over all of `candidates`), so if notify_event raises partway
        # through, events already sent earlier in this loop are still
        # recorded -- only the one that failed (and anything after it)
        # remains unrecorded, to be retried next run.
        notified_keys.add(event_key(event))

    status_line = f"{ticker}: {current_status(close, events, config)}"
    return status_line, today, notified, seeded


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
    try:
        tickers_cfg = load_config(config_path)
        state = load_state(state_path)
        if not args.dry_run:
            _refuse_if_market_open()
    except Exception as exc:  # noqa: BLE001 -- a startup failure must still be reported
        print(f"ERROR  startup: {exc}", file=sys.stderr)
        if not args.dry_run:
            try:
                notify_error(None, f"startup failed: {exc}")
            except Exception as notify_exc:  # noqa: BLE001
                print(f"ERROR  could not send error notification: {notify_exc}", file=sys.stderr)
        sys.exit(1)

    results = []  # (status_line, notified, seeded) -- successful tickers, for dry-run detail printing
    heartbeat_lines = []  # every ticker, success or failure -- see notify_heartbeat below
    today_by_ticker: dict[str, pd.Timestamp] = {}
    had_error = False

    for ticker, cfg in tickers_cfg.items():
        try:
            status_line, today, notified, seeded = process_ticker(ticker, cfg, state, args.dry_run)
            today_by_ticker[ticker] = today
            results.append((status_line, notified, seeded))
            heartbeat_lines.append(status_line)
        except Exception as exc:  # noqa: BLE001 -- one ticker's failure must not stop the others
            had_error = True
            message = f"{ticker}: {exc}"
            print(f"ERROR  {message}", file=sys.stderr)
            heartbeat_lines.append(f"{ticker}: ERROR - {exc}")
            if not args.dry_run:
                try:
                    notify_error(ticker, message)
                except Exception as notify_exc:  # noqa: BLE001 -- the error itself (e.g. SMTP down) may be why this fails
                    print(f"ERROR  could not send error notification: {notify_exc}", file=sys.stderr)

    if args.dry_run:
        for status_line, notified, seeded in results:
            print(status_line)
            for event in notified:
                print(f"  would notify: {format_event(event, show_streak=False)}")
            for event in seeded:
                print(f"  first run, seeding without notifying: {format_event(event, show_streak=False)}")
        return

    # Always save -- even a ticker that errored out partway through may have
    # already sent some of its events this run (see process_ticker), and
    # even if every ticker failed, whatever's left in `state` (unpruned,
    # since today_by_ticker has no entry for a failed ticker) must still be
    # written back rather than silently dropped.
    save_state(state_path, state, today_by_ticker)
    # A failed ticker still gets a line here (not just its own error email):
    # if the error email itself failed to send (e.g. the same SMTP outage
    # caused both), the heartbeat is the only message left that can surface it.
    notify_heartbeat(heartbeat_lines)
    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
