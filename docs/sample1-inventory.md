# sample1 再利用資産の棚卸しと最小移植範囲

対応 Issue: [#2](https://github.com/fukuda-yuki/sample2/issues/2)
調査基点: `fukuda-yuki/sample1` @ `aa76384654bd64bf38cc5a9ada486fb8d3a559ca`
調査日: 2026-09-15

## 0. 調査方法と、この文書が主張しないこと

- 調査基点のコミットを clone し、**ファイル内容の読解と機械的な計数**（行数、旧実験名の出現数、テストが import するモジュール）を行った。
- **sample1 のテストを再実行していない。sample1 のスクリプトを動かしていない。**
- したがって本表の「検証根拠」列は、**リポジトリ内に残る記録が主張している水準**であり、私が再確認した水準ではない。記録のパスを併記する。
- 「文書がある」「コードがある」「非モデル検証の記録がある」「実モデル実行の記録がある」を区別する。**記録があることは、現在の版で再現することの証拠ではない。**

検証水準の表記:

| 表記 | 意味 |
| --- | --- |
| `doc` | 文書のみ。実行記録なし |
| `code` | 実装コードがある。テストから参照されていない |
| `code+test` | 実装コードとテストコードがある。テスト実行の記録は見つからない |
| `non-model-record` | モデルを呼ばない検証の合格記録が残っている（記録パスを併記） |
| `real-run-record` | 実モデル／実 Run の記録が残っている（記録パスを併記） |

## 1. 旧実験専用の前提（`sample2` へ持ち込まない）

| 種別 | 具体 | 出現場所の例 |
| --- | --- | --- |
| 条件名 | `normal` / `anti`、`condition` 分岐 | `normal/spec.md`, `anti/spec.md`, `scripts/prepare_workspace.py`, `scripts/copilot_scope.py` |
| 介入 | AP-001（共通ルールと F-006 の承認閾値の不整合） | `scripts/prepare_workspace.py`(1), `docs/requirements-audit.md` |
| 題材 | 申請管理システム（20 機能、`F-001`〜`F-020`） | `normal/spec.md`, `evaluation/requirements-ledger.json` |
| 採点単位 | 57 評価 ID / 58 必須ケース / 固定分母 57 / ID 形式 `T-006-05` | `evaluation/*`, `config/experiment.json`(`fixed_denominator: 57`) |
| 実行系 | `codex-cli 0.153.0`、`gpt-5.6-luna`、`effort xhigh`、worker イメージ digest | `config/experiment.json` |
| 実行許可 | `authorized_scope`, `do_not_start`, `allowed_starts`, pilot-1 / pilot-2 / batch_id | `config/execution-scope.json` |
| 保管 | `C:\Users\mwam0\ResearchArchives\sample1`, `sample1-private-eval`, 復元ゲートの `package_id` | `config/execution-scope.json`, `docs/analysis-integration.json` |
| 旧 Run 実体 | `reports/`（258 ファイル、約 17.9 MB）、`docs/pilot-artifacts/`, `docs/pilot-2-artifacts/` | `reports/` |

`sample1` の旧データ・判断履歴・原本は変更も移送もしない。参照のみ。

## 2. 再利用一覧

方針の記号: `そのまま利用` / `修正して利用` / `作り直す` / `採用しない` / `保留`。

### 2.1 外側：実行・停止・回収

| 資産・元パス | 行 | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/run_experiment.py` | 260 | 実行の識別、エージェント起動、予算超過・エラーでの停止、成果物固定 | 中（`pilot` 命名 14 箇所） | `non-model-record`: `docs/protocol-integration.json`（`model_called: false`、isolation/error/timeout/descendant の 4 ケース） | 修正して利用 | 新課題の起動方法・停止条件・固定対象へ差し替え。記録は旧版のまま使わない |
| `scripts/run_copilot.py` | 221 | Copilot CLI 実行ラッパ、worker コマンド組立 | 中（`pilot` 18） | `code+test`: `scripts/test_copilot.py` | 保留 | 実モデル比較を始めるときに接続する。初期範囲では不要 |
| `scripts/run_codex.py` | 200 | Codex CLI 実行ラッパ | 低 | `non-model-record`: `docs/pilot-2-stop-guard-verification.json`, `scripts/test_usage_retention.py` | 保留 | 同上 |
| `scripts/run_cleanup.py` | 47 | 実行後始末 | なし | `code` | そのまま利用 | 対象パスのみ調整 |
| `scripts/copilot_recovery.py` | 128 | 中断 Run の回収 | 中（`pilot` 3） | `code` | 保留 | 中断が起きうる実行方式を採るときに移植 |
| `scripts/model_gateway.py` | 207 | 上流モデルゲートウェイ（usage 取得の原本） | なし | `non-model-record`: `docs/gateway-isolation-integration.json`, `docs/isolated-host-service-integration.json`, `code+test`: `scripts/test_gateway_protocols.py` | 保留 | 実モデル接続時の usage 原本。初期範囲では不要 |
| `scripts/fake_responses.py` | 50 | ダミー応答（モデルを呼ばない実行器） | なし | `code` | そのまま利用 | #5 の「ダミー実行器・合成使用量」検証に使える |

### 2.2 外側：作業領域の分離・配布

| 資産・元パス | 行 | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/prepare_workspace.py` | 63 | 条件別の配布物生成（配布フラグ） | **高**（`anti` 7、`AP-001` 1、アプリ名 1） | `code+test`: `scripts/test_protocol.py` | **作り直す** | 新課題の「実装役に渡す入力」を新規に定義する。旧条件名を持ち込まない |
| `scripts/check_isolated_host_access.py` | 40 | 隔離確認（host canary） | なし | `non-model-record`: `docs/isolated-host-service-integration.json` | 保留 | Docker 隔離を採る場合に移植 |
| `scripts/check_run_separation.py` | 48 | 同時 Run の資源分離 | なし | `non-model-record`: `docs/run-separation-integration.json` | 保留 | 並列実行を採る場合に移植 |
| `scripts/check_gateway_isolation.py` | 60 | gateway 経路の隔離確認 | なし | `non-model-record`: `docs/gateway-isolation-integration.json` | 保留 | 同上 |
| `scripts/check_offline_runtime.py` | 69 | オフライン実行の校正 | 低 | `non-model-record`: `docs/offline-runtime-integration.json`（旧イメージ固有） | 採用しない | 新課題で同等の校正をやり直す |

### 2.3 計測：usage・token と monitor の結び付け

| 資産・元パス | 行 | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/normalize_usage.py` | 68 | 上流 usage の正規化、`usage_complete` 判定、欠測を 0 に置換しない扱い | なし | `non-model-record`: `docs/model-smoke-integration.json`（`usage_complete: true`）、`code+test`: `scripts/test_protocol.py` | **そのまま利用**（最有力） | 原本の定義が変わった場合の対応表 |
| `scripts/telemetry_link.py` | 317 | Run と使用量原本・monitor の突合、測定の投影 | なし | `code+test`: `scripts/test_telemetry_link.py` | **そのまま利用**（最有力） | 新実験の Run 識別子体系へ接続 |
| `scripts/gateway_usage.py` | 71 | gateway 側 usage の集計 | なし | `code+test`: `scripts/test_gateway_protocols.py`, `scripts/test_usage_retention.py` | 保留 | 実モデル接続時に移植 |
| `scripts/check_monitor_link.py` | 64 | `local-agent-monitor` との接続確認 | なし | `code` | 修正して利用 | monitor 側の版・接続方法を確認 |
| `docs/token-accounting.md` | — | 総トークンの定義（累積、cache/reasoning の二重加算回避、欠測の非 0 置換） | 低 | `doc` | 知見として採用 | 定義を新仕様として書き直す |
| `docs/metrics.md` | — | Run 単位の集計と図、chart contract | 中（旧集計列） | `doc` | 修正して利用 | 欠測理由の扱いを維持 |

### 2.4 外側：保存・固定・復元・再集計

| 資産・元パス | 行 | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/preserve.py` | 232 | 原本保全、パッケージ化、許可リストによる対象限定 | なし | `code+test`: `scripts/test_preservation.py` | **そのまま利用**（最有力） | 保全対象の許可リストを新課題用に定義 |
| `scripts/preservation_gate.py` | 112 | 保全の不変性検査 | 低 | `non-model-record`: `docs/preservation-code-verification.json`（`unittest discover` 29→32 件 OK）, `docs/preservation-final-code-verification.json`（32 件 OK） | 修正して利用 | 新基盤のファイル集合で再検証する |
| `scripts/prepare_preservation.py` | 89 | 保全パッケージの作成 | 中（`anti` 1、`pilot` 5） | `code` | 修正して利用 | 条件名依存を除去 |
| `scripts/check_preservation_restore.py` | 145 | 復元物の照合（CSV/JSON/SQLite 再生成と突合） | 低（`57` 1） | `real-run-record`: `docs/preservation-restore-verification.json`, `docs/preservation-restore-isolated-verification.json`（ただし旧 batch の復元） | 修正して利用 | **旧 Run の復元成功は新基盤の復元証拠にならない** |
| `scripts/launch_restore_drill.py` | 56 | 復元ドリル起動 | なし | `non-model-record`: `docs/preservation-restore-isolated-verification.json` | 修正して利用 | 新基盤の復元手順で再実施 |
| `scripts/check_restore_namespace.py` | 58 | 復元側の名前空間ガード | 低 | `code+test`: `scripts/test_restore_namespace_guard.py` | そのまま利用 | — |
| `scripts/copilot_analysis_archive.py` | 117 | 分析成果物のアーカイブと許可リスト共用 | 低 | `code+test`: `scripts/test_copilot_analysis_archive.py` | 修正して利用 | 新実験の許可リストへ差し替え |
| `scripts/verification_plan.py` | 55 | 変更依存から必要な検証を導出 | 中（`pilot` 10） | `code+test`: `scripts/test_verification_plan.py` | 保留 | 最初の 1 課題では過大 |

### 2.5 外側：バッチ・並列・開始認可

| 資産・元パス | 行 | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/copilot_batch.py` | 612 | `plan` / `run` / `status` / `evaluate` / `export` / `recover` / `resume` / `extend` | **高**（`pilot` 24、`anti` 2） | `code+test`: `scripts/test_copilot_batch.py`, `scripts/test_copilot_evaluate.py` | 保留 | 1 課題の逐次経路には不要。N/K/limit と開始認可は新実験の設計時に再検討 |
| `scripts/copilot_parallel.py` | 220 | 並列実行と直列化 | 中 | `code+test`: `scripts/test_parallel_batch.py` | 採用しない（初期範囲外） | 並列が要件化した時点で再検討 |
| `scripts/copilot_scope.py` | 151 | 開始スコープ、契約生成 | **高**（`pilot` 17、`anti` 1） | `code+test`: `scripts/test_copilot_scope.py` | 保留 | 契約生成の考え方のみ参考 |
| `scripts/execution_scope.py` | 46 | 開始認可の記録 | 中（`pilot` 5） | `code+test`: `scripts/test_execution_scope.py` | 保留 | 旧 `allowed_starts` を新実験へ流用しない |
| `scripts/make_run_config.py` | 30 | Run 設定の生成 | なし | `code+test`: `scripts/test_execution_scope.py` | そのまま利用 | 設定項目を新実験用に定義 |
| `scripts/serial_acquisition.py` | 215 | 逐次取得の運用 | 高 | `code+test`: `scripts/test_serial_acquisition.py` | 採用しない | 旧運用固有 |
| `scripts/prepare_serial_acquisition.py` | 89 | 同上の準備 | 高 | `code` | 採用しない | 同上 |

### 2.6 内側：採点接続と評価版

| 資産・元パス | 責務 | 旧実験への依存 | 現在の検証根拠 | 方針 | 新環境での確認事項 |
| --- | --- | --- | --- | --- | --- |
| `scripts/evaluation_receipt.py` (61) | 採点の receipt 生成（誰が・どの版で・どの成果物を採点したか） | なし | `code+test`: `scripts/test_evaluation_receipt.py` | **そのまま利用**（最有力） | 結果スキーマを新仕様へ合わせる |
| `evaluation/result.schema.json` | 採点結果 JSONL のスキーマ（`run_id`, `evaluation_id`, `case_id`, `status`, `evidence`, `score_version`, `submission_hash`） | 低（`case_id: main/lower/upper`） | `doc` | 修正して利用 | `case_id` の区分を新課題に合わせる。`status` の `pass/fail/blocked/error` は維持価値が高い |
| `evaluation/evaluator-version.json` | 評価版のハッシュ束（`score_version`） | 高（`fixed_denominator 57`, `required_scored_cases 58`） | `doc` | 修正して利用 | 版管理の構造のみ引き継ぐ |
| `evaluation/case-manifest.json` | 採点単位の一覧 | 高 | `doc` | 作り直す | 構造のみ参考 |
| `evaluation/requirements-ledger.json` (167 KB) | 要件台帳（要求と検査の対応） | **高** | `doc` | 採用しない | 台帳という形式のみ参考 |
| `evaluation/validate-requirements.py` | 台帳の自己検証（57 ID の網羅など） | **高** | `non-model-record`: `docs/preservation-final-code-verification.json` の `PASS: 57 IDs ...` | 採用しない | 「台帳を機械的に検証する」考え方のみ採用 |
| `evaluation/prepare-app-container.py` | 評価用コンテナの準備 | **高**（申請管理アプリ固有） | `code` | 作り直す | 新課題の起動契約を定義 |
| `evaluation/calibration-summary.json` (40 KB) | 評価器の校正記録 | 高 | `doc` | 採用しない | 「正例・負例・別実装・評価側障害を記録する」形式のみ参考 |
| `evaluation/validity-registry-summary.json` | 採点有効性の台帳要約 | 高 | `doc` | 採用しない | — |
| `docs/evaluator.md` | 評価器の実行契約（分離、提出固定、障害分類、出力） | 高 | `doc` | 知見として採用 | **障害分類（`blocked`/`error`/`PRECONDITION_BLOCKED`）と「未評価を 0 点や合格にしない」原則を引き継ぐ** |
| `docs/meaningful-evaluation.md` | 実行・採点・妥当性・再採点・復元再集計の手順 | 高 | `doc` | 知見として採用 | 手順の骨格のみ。57 ID・AP-001 は持ち込まない |

### 2.7 内側：評価器本体（Playwright）

| 資産 | 所在 | 方針 |
| --- | --- | --- |
| `run.mjs`, `playwright.config.ts`, `tests/ui.ts`, `tests/application.spec.ts` | **リポジトリ外**（`<private-eval-root>`）。`evaluation/evaluator-version.json` にハッシュのみ記録 | **採用しない。新課題用に作り直す** |
| 校正 fixture（正例・負例・別実装） | 同上（非公開） | 考え方のみ採用。新課題の fixture を新規作成する |

`docs/evaluator.md` の記述によれば、採点コード・fixture・失敗内容・trace は研究者専用領域に置かれ、公開 Git へは入れない。この分離方針は `sample2` でも維持する。

### 2.8 ハーネス自体のテスト

| 資産 | 内容 | 検証根拠 | 方針 |
| --- | --- | --- | --- |
| `scripts/test_*.py`（24 ファイル） | ハーネスの非モデル検証（unittest） | `non-model-record`: `docs/preservation-final-code-verification.json` に `scripts` 32 件・`analysis` 25 件 OK の記録（`source_commit 4d763522...`） | 移植するモジュールのテストだけを持っていく |
| `analysis/test_*.py` | 集計・分析の検証 | 同上（25 件 OK） | 集計を移植する場合に併せて移植 |

テストが import する主なモジュール: `telemetry_link`, `preserve`, `gateway_usage`, `model_gateway`, `copilot_batch`, `copilot_scope`, `execution_scope`, `run_experiment`, `run_copilot`, `preservation_gate`, `copilot_analysis_archive`, `verification_plan`, `evaluation_receipt`。

### 2.9 文書・記録（採用しないもの）

| 資産 | 内容 | 方針 |
| --- | --- | --- |
| `docs/decision-log.md` (13 KB) | 旧実験の判断履歴 | 採用しない。参照のみ |
| `docs/pilot-results.md`, `docs/pilot-2-results.md`, `docs/pilot-2-stop.json` | 旧 pilot の結果と停止 | 採用しない。参照のみ |
| `docs/issue-acceptance-audit.md`, `docs/requirements-audit.md` | 旧受入・要件監査 | 採用しない。参照のみ |
| `docs/copilot-byok.md`, `docs/copilot-acceptance-20260908.md` | 旧実行環境の受入 | 保留（実行方式を決める時に参照） |
| `docs/experiment-design.md`, `docs/agent-roles.md`, `docs/reproduce.md`, `docs/run-protocol.md`, `docs/workspace-isolation.md`, `docs/preservation.md` | 研究設計・役割・手順 | 知見として採用。内容は新実験用に書き直す |
| `docs/*-incident.json`, `docs/original-loss-incident.json` | 障害記録 | 知見として参照（同じ失敗を避ける） |
| `reports/`（258 ファイル、17.9 MB） | 旧 Run の集計・図 | 採用しない |
| `analysis/`（12 ファイル） | 旧分析コード（`aggregate.py`, `measurement.py`, `plot.py`, `validity.py`, `collect_runs.py`, `calibrate.py`, `pilot_snapshot.py` + テスト 4 件） | 保留。`measurement.py`・`collect_runs.py` は旧実験名を含まず再利用候補、`aggregate.py`・`plot.py`・`validity.py`・`calibrate.py`・`pilot_snapshot.py` は `anti` を含み条件名に結合 |
| `config/*.json` | 旧実験設定 | 採用しない。`fixed_denominator: 57` 等を新仕様にしない |
| `normal/spec.md`, `anti/spec.md`, `implementation_prompt.md`, `antipattern_list.md`, `test_items.md` | 旧条件の入力 | 採用しない |

## 3. 最小移植案（最初の 1 課題＝ .NET モダナイズ）

初期範囲は **1 課題・逐次実行相当**。Docker 隔離・並列実行・モデルゲートウェイ・BYOK・開始認可ゲートは初期範囲に含めない（実モデル比較を始めるときに再検討する）。

| 段階 | 移植するもの | 根拠 |
| --- | --- | --- |
| 1. 固定と採点の一巡 | `evaluation_receipt.py`（採点 receipt）、`preserve.py` のハッシュ固定と許可リストの考え方 | 旧実験への依存がなく、テストがある |
| 2. 記録・再集計 | `result.schema.json` の `status` 区分、`docs/metrics.md` の欠測理由の扱い、`telemetry_link.py` の測定投影 | 「欠測を 0 に置換しない」「成功 Run だけに絞らない」原則 |
| 3. 実行の骨格 | `run_experiment.py` の**識別 → 実行 → 停止確認 → 成果物固定**の順序 | `docs/protocol-integration.json` の 4 ケースがこの順序を検証している |
| 4. ダミー実行 | `fake_responses.py`（モデルを呼ばない実行器） | #5 の接続検証を実モデルなしで行える |
| 5. 内側 | **移植しない。新規に作る**（`inner/`） | 品質評価仕様も評価器も課題固有であり、旧 57 ID の資産は正解基準にならない |

**今回移植しないもの**: 並列実行（`copilot_parallel.py`）、開始認可ゲート（`execution_scope.py`, `copilot_scope.py`）、バッチ運用（`copilot_batch.py`, `serial_acquisition.py`）、モデルゲートウェイと BYOK（`model_gateway.py`, `run_copilot.py`, `run_codex.py`）、Docker 隔離一式、`reports/` と旧 Run 実体、`verification_plan.py`。

## 4. 引き継ぐ知見と、再検証なしに引き継げない成功証拠

### 4.1 知見として引き継ぐ（実装の再現は必要、証拠の流用はしない）

- **欠測を 0 に置換しない。** `usage_complete` を独立状態として持ち、未採点は点数 null、有効な 0 点は 0 とする（`docs/meaningful-evaluation.md`）。
- **失敗・障害・不合格を独立に記録する。** 実行失敗、評価器障害、未採点、品質上の不合格、usage 欠測を別の列にする。
- **成功 Run だけに絞って集計しない。**
- **未評価を合格にしない。** missing/skip を合格にせず、未実行 ID を分母から落とさない（`docs/evaluator.md`）。
- **評価側障害と実装品質の失敗を取り違えない。** 起動不能・前提不成立は `blocked`／`PRECONDITION_BLOCKED`、評価器自身の障害は `error` で品質 null。
- **原本を上書きしない。** 再採点は新しい評価 ID を作り、旧評価履歴を残す。
- **モデルを呼ばない検証の合格を、実モデル実行の成立と呼ばない。**
- **配布物を条件ごとに限定する。** 実装役へ渡すのは当該条件で許された入力だけ。

### 4.2 再検証なしに引き継げない成功証拠

| 記録 | 内容 | 引き継げない理由 |
| --- | --- | --- |
| `evaluation/calibration-summary.json` | 旧評価器の校正成功 | 旧アプリ・旧 57 ID に対する校正であり、新課題の品質評価の妥当性の根拠にならない |
| `docs/model-smoke-integration.json` | 実モデル接続と usage 完全性 | 旧 worker イメージ・旧ゲートウェイ・旧モデルの記録 |
| `docs/preservation-restore-verification.json` ほか | 旧 batch の復元再集計成功 | 新基盤の復元証拠ではない。新基盤でやり直す |
| `docs/offline-runtime-integration.json`, `docs/browser-runtime-integration.json` | オフライン実行・ブラウザの校正 | 旧イメージ固有 |
| `docs/pilot-results.md`, `docs/pilot-2-results.md` | 旧 pilot の品質・トークン | 旧題材・旧条件の結果。新課題へ一般化できない |
| `docs/preservation-code-verification.json`（32+25 件 OK） | 旧ハーネスのテスト成功 | 移植先で再度テストを走らせない限り、移植後コードの正しさの根拠にならない |

## 5. 切り出しが難しい場合の代替案

1. `run_experiment.py` / `copilot_batch.py` は `pilot` 命名と開始認可に強く結合しており、そのままでは切り出しにくい。**切り出しに時間をかけるより、外側の最小 CLI を新規に書く。** 引き継ぐのはデータ形式（`snapshot.json` 相当、結果 JSONL、usage 正規化の考え方）と検証観点に限る。
2. `preserve.py` は旧実験名を含まずテストもあるため、**そのまま持ち込める可能性が最も高い**。ここが再利用できないと分かった場合も、外側の目的（原本の不変性・追跡可能性）はハッシュ固定と許可リストだけで最小実装できる。
3. 内側は**課題が決まる前でも骨格（起動・観測・判定・記録・再採点）を作れる**。課題固有部分（要件・期待値・fixture）は [#3](https://github.com/fukuda-yuki/sample2/issues/3) の仮決定後に埋める。
4. 外側の構築が重くなった場合、[#5](https://github.com/fukuda-yuki/sample2/issues/5) は**手動起動・固定成果物の単独採点**まで縮めて、内側の品質判定と記録の検証を先行させる。

## 6. `sample1` を変更せずに進める手順

1. `sample1` は clone して**読むだけ**。`git checkout` するのは調査基点コミットの参照のみで、ブランチを進めない・push しない。
2. 移植は「元パス → 新パス」の対応を本表に追記して行い、**移植元コミット `aa76384654bd64bf38cc5a9ada486fb8d3a559ca` と、移植時に実際に使った版を記録する**。
3. 移植したコードは新リポジトリ側でテストを再実行し、その記録を新リポジトリに残す。**旧記録を新コードの検証根拠として引用しない。**
4. `sample1` の Issue・記録・原本へ書き戻さない。

## 7. 未確認・保留

- 本表の行数は機械的な計数であり、実際の保守単位とは一致しない。
- 各モジュールの「切り出しやすさ」は**読解による推定**であり、実際に移植して動かすまで確定しない。移植の可否は #5 の実装時に判定する。
- `local-agent-monitor` の現行版・接続方法は本調査で確認していない。
- `sample1` の `analysis/` の中身は網羅していない。
- `sample1` の追跡ファイルに `LICENSE` / `COPYING` / `NOTICE` が存在しないことを確認した（`git ls-tree -r --name-only HEAD` で該当なし）。移植するコードのライセンス条件は、移植実施前に `sample1` 側で確認する。
