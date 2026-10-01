<p align="center"><b>English</b> | <a href="README.ja.md">日本語</a></p>

# Drawdown Watcher

Monitor market drawdowns from rolling highs and get notified when your
predefined thresholds are reached.

Drawdown Watcher tracks the 52-week closing high of each ticker. When a
configured drawdown threshold is reached, it locks the reference high and
monitors deeper drawdown levels and a confirmed recovery off the low —
then follows the rebound, so a good entry isn't sold too early. It's
built for someone who doesn't watch the market day to day, so it only
speaks up at a few points:

```text
NORMAL
  ↓ watch_threshold reached
1. "Pay attention"            DRAWDOWN MODE (reference high locked)
  ↓ deeper levels reached
2. "Maybe getting interesting" LEVEL 1 / 2 / 3
  ↓ rebound off the low holds
3. "It bottomed"              RECOVERY CONFIRMED (revoked if a new low follows)
  ↓ 2x from the bottom call
4. "Keep holding"             UPTREND ARMED (sell line: N% below the peak)
  ↓ falls N% from its peak
   "The uptrend looks over"   UPTREND EXIT
```

The periodic heartbeat states each ticker's current stage in concrete
numbers (peak, sell line, distance to it), so the rule never has to be
remembered.

Example tickers:

- SPXL
- SOXL
- TECL
- SPY / VOO
- Individual stocks

This project does not predict market crashes or generate investment
recommendations. It monitors predefined rules.

## Status

Work in progress. The detection logic, backtests, the daily runner
(`src/main.py`, email notifications), and its scheduled deployment (a
GitHub Actions workflow in the private repo) are implemented. See
[docs/strategy.md](docs/strategy.md) for the concept and
[docs/architecture.md](docs/architecture.md) for the system design.

## Configuration

Watch thresholds, drawdown levels, and recovery thresholds are configurable
per ticker, since volatility differs a lot between, say, a 3x leveraged ETF
and a broad index fund. See
[config/config.example.yaml](config/config.example.yaml) for the format —
its values are illustrative, not recommendations. Tune your own with
`python -m src.threshold_sweep <TICKER>` and `python -m src.exit_sweep
<TICKER>` (add `--synthetic` to test against decades of synthetic history
built from the underlying index), and keep the real config outside
this repo:

```sh
python -m src.backtest --config ../my-private-config/config.yaml
```

## Backtest

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m src.backtest                 # uses config/config.example.yaml
python -m src.backtest --refresh       # bypass the data/ cache and refetch
python -m pytest tests/
```

Price history is fetched via `yfinance` and cached under `data/`
(gitignored — not redistributed).

## Running it

```sh
cp .env.example .env   # fill in SMTP settings
python -m src.main --config ../my-private-config/config.yaml --dry-run
```

Drop `--dry-run` to actually send email for new events and a heartbeat (see
[docs/architecture.md](docs/architecture.md) "Notifications"), and persist
what's been notified so far to `--state` (default: `data/notified_state.json`).
Meant to be run once a day, after the US market closes; see
[docs/architecture.md](docs/architecture.md) "Deployment" for how it's
scheduled in production (a GitHub Actions workflow in the private repo).

## Disclaimer

This is a personal monitoring tool, not investment advice. It only notifies
you when rules you configured yourself are met.

## License

[MIT](LICENSE)
