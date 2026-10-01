<p align="center"><a href="README.md">English</a> | <b>日本語</b></p>

# Drawdown Watcher

株式・ETFの高値からの下落（ドローダウン）を監視し、あらかじめ決めておいた閾値に
達したときに通知するツールです。

Drawdown Watcherは、銘柄ごとに過去52週の最高終値を追跡します。設定した下落率に
達すると基準高値をロックし、そこからさらに深いLevelへの到達と、安値からの反発の
確定を監視します。普段相場を見ない人向けに作っているので、通知するのは次の
3つのタイミングだけです。

```text
NORMAL
  ↓ watch_threshold に到達
1. 「相場を見ておけ」     DRAWDOWN MODE（基準高値をロック）
  ↓ より深いLevelに到達
2. 「そろそろ底かも」     LEVEL 1 / 2 / 3
  ↓ 安値からの反発が持続
3. 「底を打った」         RECOVERY CONFIRMED（その後に安値を更新したら取り消し）
  ↓ 元の基準高値を回復
NORMAL
```

対象銘柄の例:

- SPXL
- SOXL
- TECL
- SPY / VOO
- 個別株

暴落を予測したり、投資判断を勧めたりするものではありません。あらかじめ決めた
ルールを監視するだけです。

## 状況

開発中です。判定ロジックとバックテストは完成しており、次は本番側（毎日の定期実行と
通知）です。考え方は[docs/strategy.ja.md](docs/strategy.ja.md)、システム設計は
[docs/architecture.ja.md](docs/architecture.ja.md)を参照してください。

## 設定

3倍レバレッジETFと分散型のインデックスファンドでは値動きの大きさがまったく違うため、
監視の閾値・Level・Recoveryの閾値は銘柄ごとに設定できます。形式は
[config/config.example.yaml](config/config.example.yaml)を参照してください。値は
例示用で、推奨値ではありません。`python -m src.threshold_sweep <銘柄>`で自分で
調整し、実際の設定はこのリポジトリの外に置いてください。

```sh
python -m src.backtest --config ../my-private-config/config.yaml
```

## バックテスト

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m src.backtest                 # config/config.example.yaml を使う
python -m src.backtest --refresh       # data/ のキャッシュを使わず再取得する
python -m pytest tests/
```

価格履歴は`yfinance`で取得し、`data/`にキャッシュします（gitignore対象で、
再配布はしません）。

## 免責事項

個人用の監視ツールであり、投資助言ではありません。自分で設定したルールに
該当したときに知らせるだけです。

## ライセンス

[MIT](LICENSE)
