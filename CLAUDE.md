# Drawdown Watcher

## 変更時に注意すべき設計

- `src/state_machine.py`の`episode_high`と`reference_high`は、一本化できそうに見えるが
  意図的に別変数にしている。`episode_high`はNORMAL_RESUME判定専用で局面中は不変、
  `reference_high`はLevel・Recovery判定用でRENEWED_DECLINE時に再ロックされる。一本化すると、
  再アラート局面が元より低い高値でNORMAL_RESUMEしてしまい、元の高値がまだ52週以内に
  残っている場合、翌日に誤って元の高値基準でDRAWDOWN MODEへ再突入する不具合が再発する。
  詳細は[docs/strategy.md](docs/strategy.md)の「Staying alert during a long episode」を参照。

- 本番運用では状態（mode・reference_high等）を保存せず、毎日全期間の価格データで
  `state_machine.run()`を再計算し、通知済みイベントとの差分だけを通知する方式を採る。
  レバレッジETFの分割・併合対応、バックテストとの一致、状態の最小化を同時に満たすための
  意図的な設計。詳細は[docs/architecture.md](docs/architecture.md)の
  「Statelessness and stock splits」を参照。

- 上昇の追跡（`track_uptrend`）は、「2倍までは何があっても持つ」ように見えるが、
  2倍に届く前に`RECOVERY_UNDERCUT`が出たら降りる（`UPTREND_EXIT`、理由は`undercut`）。
  この例外は消さないこと。消すと、長い下落相場（合成系列の2000〜2002年）で底打ちに
  乗った分を数十年、または資金がほぼゼロになるまで持ち続ける。過去15年の実データでは
  この問題が表に出ないため、必ず`--synthetic`でも確認する。詳細は
  [docs/strategy.md](docs/strategy.md)の「After the bottom」を参照。

## 公開範囲

- このリポジトリはpublic。実際に運用する銘柄別の閾値・その調整根拠（バックテストで得た
  頻度・局面ごとの数値など）・バックテストレポートは、隣のprivateリポジトリ
  `../drawdown-watcher-private`で管理する。こちらの`config/config.example.yaml`や
  `docs/strategy.md`には例示用の値と仕組みの説明だけを書き、実際の値を書き戻さない。
- 実際の値でのバックテストは`python -m src.backtest --config ../drawdown-watcher-private/config/config.yaml`。
- `README.md`・`docs/strategy.md`・`docs/architecture.md`は英語版が基本で、日本語版
  （`*.ja.md`）を併置している。片方を変更したら、もう片方も同じコミットで更新する。
