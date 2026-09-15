# 外側：実験実行基盤（最小経路）の仕様

対応 Issue: [#5](https://github.com/fukuda-yuki/sample2/issues/5)
状態: 仕様。実装は [`outer/`](../outer/README.md) に置く。**実モデル接続は本仕様の範囲外であり、`outer/` にモデルを呼ぶ経路は無い。**

## 0. この文書が主張しないこと

- 外側が動くことは、品質評価が妥当であることの根拠にならない。
- 非モデル検証（ダミー実行器・合成使用量）の合格を、実モデル実行の成立や本比較の成立と呼ばない。
- 「記録がある」ことと「実環境で検証した」ことを混同しない。§10 で両者を分けて書く。

## 1. 責務と、外側が越えない線

外側の責務は **開始状態の用意・条件適用・実行・停止・回収・成果物固定・採点呼び出し・保存・再集計** である。
測定手順と記録の信頼性を担い、**品質の正解基準は持たない**。

| 越えない線 | 実装上の担保 |
| --- | --- |
| 合否・配点を外側で再定義しない | 外側は評価器の `verdict` `quality` を**そのまま保存する**。外側でしきい値を設けない |
| `blocked` `error` を 0 や合格に読み替えない | `quality` が `null` のとき `0` を入れない。`blocked` は `blocked` のまま保存する |
| 品質とトークン量を混ぜない | 集計表で別の列にする（§7） |
| 評価器の出力を書き換えない | `evaluation.json` などを読み直して別ファイルを作ることはあっても、評価器の出力ファイルを編集しない |
| 内側の実装詳細に依存しない | 外側が知るのは §6 の受け渡し形式だけ |

## 2. 作業領域の分離

| 領域 | 実体 | 誰が見るか |
| --- | --- | --- |
| 研究管理 | `docs/`、`outer/conditions/` | 研究者 |
| 実装作業 | `runs/<run_id>/workspace/`、`runs/<run_id>/inputs/` | 実装エージェント |
| 非公開評価 | `inner/spec/`、`inner/evaluator/`、`inner/fixtures/` | 研究者のみ |
| 結果保存 | `runs/<run_id>/frozen/`、`runs/<run_id>/evaluations/`、`runs/<run_id>/usage/` | 研究者 |

原則:

- **実装役へ渡すのは、当該条件の許可リストに載った入力だけ**である。`inputs/` に `inner/` 配下・`docs/` 配下を
  入れることは実装側で拒否する（§3.2）。要件台帳・評価器・校正 fixture は入力にならない。
- `runs/` は `.gitignore` により追跡しない。**固定した成果物と採点結果を公開リポジトリへ入れない。**
- 非公開評価の実体は実装作業領域から見えない位置に置く。条件で明示しない限り、実装役は `inner/` を読めない。

## 3. Run の識別と条件

### 3.1 条件

条件は `outer/conditions/<task_id>/condition.json` に置き、`runs/<run_id>/condition.json` へ**写しを固定する**。
固定した写しの `sha256` を `manifest.json` に記録する。Run の後から条件ファイルを編集しても、
その Run がどの条件で走ったかは変わらない。

条件に必ず含める項目:

| 項目 | 内容 |
| --- | --- |
| `task_id` `task_title` | 課題の識別。評価器の台帳の `taskId` と一致しなければ採点を拒否する（§6） |
| `start_state` | 題材・参照リポジトリ・参照コミット・ライセンス表示 |
| `environment` | ランタイム、SDK 版、ネットワーク条件 |
| `migration_request` | 移行要求の文面 |
| `input_policy` | `allowlist`（渡してよい入力）と `denied`（渡さない入力） |
| `budget` | 実行上限。`kind` `value` `scope` を明示する |
| `agent` | 利用エージェント・モデル・エージェント版・ツール版 |
| `evaluation` | 固定する評価版と、台帳の `spec_sha256` |

**旧実験の条件名（`normal` `anti`）・旧採点分母・旧実行許可・旧モデル設定を持ち込まない。**
`agent` は初期値を `null` とし、**値が埋まっていなければ `start` を拒否する**。
ダミー実行器を使うときだけ `--synthetic` を付けて起動でき、その場合 `manifest.json` に
`model_called: false` と `synthetic: true` を記録する。`null` を勝手に既定値へ置き換えない。

### 3.2 入力の用意

`create` は許可リストに載った入力だけを `inputs/` へコピーし、`inputs-manifest.json` に
`相対パス → sha256` を記録する。次の場合は作成を拒否する。

- 許可リストに載っていない入力
- 解決後のパスが `inner/` または `docs/` の下にある入力
- リンク（シンボリックリンク・ジャンクション）を含む入力

### 3.3 Run の識別

`run_id` は `{task_id}-{condition_id}-{attempt:03d}`。`runs/<run_id>/` の作成は**排他**で行い、
既に存在すれば失敗する。**再試行で旧 Run を上書きしない。** 再試行は `attempt` を進める。

## 4. 実行・停止・回収

順序は **識別 → 入力固定 → 実行 → 停止確認 → 成果物固定** とする。
**停止を確認する前に成果物を固定しない。**

`manifest.json` に記録する実行の情報:

| 項目 | 内容 |
| --- | --- |
| `started_at` `ended_at` | ISO 8601 |
| `runner` | 実行器の識別子と版。`dummy` / `manual` のみ実装する（§9） |
| `agent` | 条件の写し。`model_id` `agent_version` `tool_versions` |
| `exit_code` | 実行器の終了コード |
| `end_reason` | `completed` / `agent_error` / `timeout` / `stop_unconfirmed` / `environment_failure` |
| `stop_confirmed` | プロセスが終了したことを確認できたか |
| `stop_method` | 確認の方法。`process_exit`（実行器のプロセスを回収した）/ `operator_process_check`（人が残存プロセスを確認した）/ `declaration_only`（宣言のみ。停止とみなさない） |
| `stop_evidence` | 確認の根拠。`declaration_only` では空にしない |
| `submission_fixed` | 成果物を固定できたか |
| `model_called` | モデルを呼んだか。ダミー実行器では常に `false` |

### 4.1 停止確認

実行器は「終了を宣言した」ことと「プロセスが終了した」ことを別に扱う。
宣言だけでは停止とみなさない。宣言のあとに子プロセスが残っていれば停止し、確認できなければ
`stop_confirmed: false`、`submission_fixed: false`、`end_reason: stop_unconfirmed` とする。
`stop_confirmed` が `false` の Run は採点しない。

### 4.2 成果物の回収手順

回収先は `runs/<run_id>/frozen/`。`workspace/` から次を**除外**してコピーする。

| 除外 | 対象 |
| --- | --- |
| ディレクトリ | `bin` `obj` `.git` `.vs` `node_modules` `TestResults` |
| 拡張子 | `.sqlite` `.sqlite3` `.db` `.db-shm` `.db-wal` `.user` |

**除外規則は評価器の成果物ハッシュの除外規則（`bin` `obj` `.git`）を含む上位集合でなければならない。**
除外しすぎると評価器が `bin` を成果物の一部として見てハッシュが変わる。除外規則と
除外した名前を `manifest.json` と `snapshot.json` に記録する。

**改行と BOM を回収時に固定する。** 対象は次の拡張子のテキストファイルで、
改行を LF に、先頭の UTF-8 BOM を除去する。

`.cs` `.csproj` `.cshtml` `.config` `.json` `.jsonl` `.md` `.txt` `.css` `.js` `.html` `.xml` `.razor` `.sln` `.props` `.targets` `.yml` `.yaml` `.csv` `.ps1` `.sh`

固定の理由は **評価 ID が成果物のバイト列に依存する**ためである。実装役の作業ツリーの改行コードが
環境で変わると、同じ実装でも評価 ID が変わり評価履歴が分断される。回収時に LF へ寄せておけば、
回収した成果物から同じ ID を再現できる。

`snapshot.json` には次を記録する。

| 項目 | 内容 |
| --- | --- |
| `collected` | 回収したファイルの `相対パス → {sha256, bytes}`（固定前のバイト列） |
| `frozen` | 固定後のファイルの `相対パス → {sha256, bytes}` |
| `normalized` | 改行・BOM を変更したファイルの一覧と変更の種類 |
| `artifact_sha256` | 固定後の `frozen/` に対する評価器と同じ算法の成果物ハッシュ（§6） |
| `artifact_sha256_collected` | 固定前の `workspace/` に対する同じ算法のハッシュ |
| `excluded_directories` `excluded_suffixes` | 実際に使った除外規則 |

固定の前後でハッシュが変わる場合がある。**変わったことと、その理由を記録する。**
`artifact_sha256_collected` と `artifact_sha256` が異なる場合、`normalized` が空であってはならない。

## 5. 使用量の接続

使用量の原本は実行器が書き出す `usage/raw/` とする。原本は**無改変で保存**し、
正規化の入力は原本から抽出した `usage/events.jsonl` とする。

正規化は sample1 の `normalize_usage.py` を移植した [`outer/harness/usage.py`](../outer/harness/usage.py) が行う。

| 原則 | 実装上の担保 |
| --- | --- |
| 欠測を 0 に置換しない | `total_tokens` は完全なときだけ数値、不完全なときは `null`。観測値は `observed_tokens` に別途残す |
| 取得できない値を 0 に変換しない | 個々のイベントの `usage` が欠けていれば `missing` に理由付きで積む |
| 二重加算を避ける | `request` 方式と `cumulative` 方式をセッション単位で排他。同じ `request_id` の重複は 1 回だけ数える |
| 累積の再送・巻き戻りを検出する | 累積が減ったイベントは例外にする（セッションを分けるべき状況） |
| 原本の完全性を主張しない | 呼び出し・セッションの網羅が確認できていなければ `missing` に `call_and_session_inventory_unverified` を積み、`usage_complete: false` にする |
| 子セッションの二重計上を避ける | `includes_children: true` のイベントはセッション別イベントと混在させない（例外にする） |

`usage/provenance.json` に、原本の出所、取得方法、`expected_sessions`、`inventory_complete` の根拠を記録する。
**`inventory_complete` の根拠を示せない限り `true` にしない。**

### 5.1 コンテキスト・トークンの記録要件との対応

| 要件 | 外側での扱い |
| --- | --- |
| リポジトリに存在する情報量 / 各モデル呼び出しの実入力 / Run 全体の累積 input・output token を別の概念として扱う | 3 つを別の欄にする。リポジトリの情報量は条件の `start_state` に記録する静的量、実入力は `usage/raw/` の原本、累積は `usage/normalized.json` |
| 初期の依頼文だけでなく、指示・履歴・ファイル取得・ツール結果・圧縮のどこまで観測できるかを明示する | `usage/provenance.json` の `observable` に、観測できる範囲を列挙する。取得ログだけから「全文が実入力に入った」と断定しない |
| 比較介入が実入力に反映されたことを確認する方法と限界 | 現時点で**未確認**。§10 の残件に置く |
| 実モデルをまだ動かしていない項目は未確認のまま残す | `manifest.json` の `model_called: false` と §10 |
| 追加推論・補助エージェント・要約・修正を含める | セッション別に合算する。子セッションを `expected_sessions` に明示しない限り含まれず、その場合は `missing` に積む |
| cache や reasoning の二重加算を避ける | 原本が `input_tokens` `output_tokens` を定義するときだけ数える。cache・reasoning の内訳は原本に別欄がある場合のみ保存し、合算に足さない |

## 6. 採点の委譲

外側は内側の評価器を CLI として呼ぶだけである。受け渡し形式は固定する。

| 入力 | 内容 |
| --- | --- |
| `--artifact <dir>` | `runs/<run_id>/frozen/` |
| `--out <dir>` | 新しい評価ディレクトリ（既存なら拒否） |
| `--spec <file>` | `inner/spec/requirements.json`（条件に固定したハッシュと一致することを確認する） |
| `--catalog <file>` | `inner/spec/catalog.json` |
| `--evaluation-version <v>` | 条件に固定した評価版 |
| `--sequence <n>` | 連番。**連番と評価履歴の管理は外側の責務**であり、評価器は履歴を持たない |

| 出力 | 内容 |
| --- | --- |
| `evaluation.json` | 1 評価分の結果。外側はこれを**そのまま保存する** |
| `results.jsonl` | 検査ごとに 1 行 |
| `evaluator-manifest.json` | 評価器・台帳・成果物のハッシュ |
| `evidence/` | `publish.log` `app-process.log` `http-*.log` |

### 6.1 1 評価 = 1 出力ディレクトリ

評価器は `evaluation_id` を成果物ハッシュから作るため、`--out` の時点では ID が分からない。
外側は一時ディレクトリへ出力させ、`evaluation.json` を読んでから
`evaluations/<evaluation_id>/` へ**移動**する。移動先が既に存在すれば失敗させる。
**同じ `evaluation_id` を 2 つ作らない。既存の評価ディレクトリを上書きしない。**

### 6.2 取り違えの検査

評価結果を受け取ったら、次を突き合わせる。1 つでも合わなければ、その結果を**有効な採点として記録しない**。

| 検査 | 期待 |
| --- | --- |
| 課題 | `evaluation.json` の `taskId` == 条件の `task_id` |
| 台帳 | `specSha256` == 条件に固定した `spec_sha256`。かつ実際の `inner/spec/requirements.json` の `sha256` と一致 |
| 成果物 | `artifactSha256` == 外側が `frozen/` から独立に計算した成果物ハッシュ |
| 評価版 | `evaluationVersion` == 条件に固定した評価版 |
| パス | `artifactPath` が `runs/<run_id>/frozen` を指す |

成果物ハッシュの算法は評価器と同一にする。**`bin` `obj` `.git` を除いた全ファイル**の
「`/` 区切りの相対パス + 半角空白 + 内容の `sha256`（小文字 16 進）+ `\n`」を
**相対パスの昇順**に連結し、その UTF-8 バイト列の `sha256`。
並び順は評価器と同じ比較規則にする（本実装の対象パスは ASCII のみ。非 ASCII の並び順は未確認）。

### 6.3 評価側の障害と実装品質の失敗

| 評価器の終了コード | `verdict` | 外側の記録 |
| --- | --- | --- |
| 0 | `pass` / `fail` / `fail_critical` / `blocked` | `scoring.state = scored`。`quality` をそのまま保存する |
| 2 | `error` | `scoring.state = evaluator_fault`。`quality` は `null`。**実行の失敗として扱わない** |

終了コード 2 は「評価器側の障害」であり、成果物の欠陥でも実行の失敗でもない。
`manifest.json` の `end_reason` を変更しない。

### 6.4 再採点

再採点は**成果物を変更せず**、新しい連番で新しい評価ディレクトリを作る。
`evaluations/index.jsonl` は追記のみとし、旧評価の行を書き換えない。
`run_id` と `evaluation_id` の対応は `index.jsonl` と `evaluations/<evaluation_id>/record.json` の両方に残す。

## 7. 記録と再集計

`runs/aggregate.json` を**保存済み資材だけから**作る。再集計は成果物を再評価しない。
次の列を**独立に**持つ。

| 列 | 値 |
| --- | --- |
| `execution.state` | `not_started` / `running` / `completed` / `agent_error` / `timeout` / `stop_unconfirmed` / `environment_failure` |
| `artifact.state` | `fixed` / `not_fixed` / `missing_workspace` |
| `scoring.state` | `not_attempted` / `scored` / `evaluator_fault` / `rejected_mismatch` |
| `quality` | 評価器の `quality` をそのまま。未採点は `null` |
| `verdict` | 評価器の `verdict` をそのまま |
| `usage.state` | `complete` / `missing` |
| `total_tokens` | 完全なときだけ数値。不完全なときは `null` |
| `observed_tokens` | 観測できた分。常に数値 |
| `issues[]` | 実行失敗・評価器障害・未採点・品質上の不合格・usage 欠測・取り違えを**別の項目として**並べる |

- **成功 Run だけに絞らない。** 失敗・未採点・欠測の Run も同じ表に出す。
- 未採点を 0 点や合格にしない。`blocked` を分母から落とさない。
- `observed_tokens` と `total_tokens` を同じ列にしない。

### 7.1 原本の保全と復元

固定した成果物・評価結果・使用量・条件は、sample1 の `preserve.py` を移植した
[`outer/harness/preserve.py`](../outer/harness/preserve.py) で **append-only のパッケージ**として保存する。

- パッケージ ID は**予約**され、失敗した試行も予約を残す。**同じ ID を再利用しない。**
- 既存パッケージを上書きしない。中断した書き込みは `-retry-<uuid>` を付けて別 ID にする。
- `verify` は余分なファイル・欠落・改変・索引の改変をすべて検出する。
- `restore` は復元後に全ファイルを照合し、receipt を残す。**receipt を改変すれば検出される。**
- 復元先はアーカイブの外に限る。

再集計は `runs/` の作業ディレクトリが失われても、アーカイブから復元した資材でやり直せる（§10-3）。

## 8. `runs/<run_id>/` の構成

```text
runs/<run_id>/
  manifest.json          Run の記録（実行・停止・固定の状態）
  condition.json         条件の固定写し（作成時点）
  inputs-manifest.json   実装役へ渡した入力の一覧とハッシュ
  inputs/                実装役へ渡した入力
  workspace/             実装役の作業領域
  frozen/                固定した成果物（評価対象）
  snapshot.json          回収前後のハッシュ、正規化の記録、成果物ハッシュ
  evidence/              実行器と評価器の標準出力・標準エラー
  usage/
    raw/                 使用量原本の写し（無改変）
    events.jsonl         正規化の入力
    normalized.json      正規化結果
    provenance.json      原本の出所・観測できる範囲・網羅性の根拠
  evaluations/
    index.jsonl          評価履歴（追記のみ）
    <evaluation_id>/     評価器の出力 + record.json
```

`runs/` は追跡しない。

## 9. 移植元（sample1）

参照コミット: `aa76384654bd64bf38cc5a9ada486fb8d3a559ca`。**`sample1` は変更しない。**

| 新パス | 移植元 | 方針 | 変更点 |
| --- | --- | --- | --- |
| `outer/harness/preserve.py` | `scripts/preserve.py` | **そのまま利用** | 課題固有の `pack_run` を新しい Run 構成に合わせた。`safe_name` の検証、予約、復元、receipt の検証は変えない |
| `outer/harness/usage.py` | `scripts/normalize_usage.py` | **そのまま利用** | 関数名・判定規則・`usage_complete` の扱いを変えない。モジュール名のみ変更 |
| `outer/harness/run.py` | `scripts/run_experiment.py` | **順序のみ採用** | 「識別 → 実行 → 停止確認 → 成果物固定」の順序と、停止未確認時に固定しない判断だけを引き継ぐ。`pilot` 命名・開始認可・Docker・予算ゲートは持ち込まない |
| `outer/harness/runner.py` | `scripts/fake_responses.py` | **考え方のみ採用** | モデルを呼ばない実行器という位置づけを引き継ぐ。旧実装はゲートウェイ（`/telemetry`）前提で単体では動かないため作り直した |
| `outer/harness/evaluate.py` | `scripts/evaluation_receipt.py` | **作り直す** | receipt の考え方（誰が・どの版で・どの成果物を採点したか）のみ採用。旧実装は Docker コンテナと旧アプリのログインに結合している |
| `outer/harness/aggregate.py` | `analysis/aggregate.py`、`docs/metrics.md` | **作り直す** | 「欠測を 0 に置換しない」「成功 Run だけに絞らない」原則のみ採用。旧集計列は持ち込まない |
| `outer/tests/` | `scripts/test_preservation.py` ほか | **作り直す** | 保全の不変条件（改変検出・ID 再利用禁止・中断復元・リンク拒否）を移植先で検証し直す |

採用しないもの: `copilot_parallel.py`、`copilot_batch.py`、`serial_acquisition.py`、`execution_scope.py`、
`copilot_scope.py`、`model_gateway.py`、`run_copilot.py`、`run_codex.py`、`telemetry_link.py`、
`verification_plan.py`、Docker 隔離一式、`reports/`、旧 Run 実体、旧条件名（`normal` `anti`）、
旧採点分母（`fixed_denominator: 57`）。

**旧実験のテスト成功は、移植後のコードの正しさの根拠にならない。** `outer/tests/` を実行して確かめる。

## 10. 検証の状態

非モデル検証の手順と記録は [`outer/verify/README.md`](../outer/verify/README.md) に置く。

### 10.1 非モデルで確認したこと

- 固定 → 採点 → 保存 → 再採点 → 再集計の経路
- **同一成果物・同一評価版・同一連番**での再実行が同じ `evaluation_id` を導き、既存を上書きせず重複として拒否されること
- **連番を進めた再採点**で `verdict` `quality` 成果物ハッシュが一致し、`evaluation_id` の差が連番だけであること
- 識別・停止・回収・欠測・失敗状態の扱い（ダミー実行器・合成使用量）
- 課題・台帳・評価版・成果物の取り違えの検出
- 原本の上書き防止、欠測の 0 置換防止、評価側障害を実装失敗として扱わないこと
- 非公開情報を入力として配布できないこと
- アーカイブからの復元と、復元した資材での再集計

### 10.2 実モデル接続でしか確認できない残件

`outer/` にモデルを呼ぶ経路は無い。次は**未確認**である。

1. 実際のエージェント実行での起動・完了宣言・停止の確認（タイムアウトと子プロセスの残存を含む）
2. 実際の使用量原本の形式と、`usage.py` の入力形式の対応。cache・reasoning の欄が原本にあるか
3. 呼び出しとセッションの網羅（`inventory_complete` の根拠）を実測で示せるか
4. 比較介入が実入力に反映されたことの確認方法
5. 実装役の作業ツリーの改行コード・BOM が環境で変わりうるか（§4.2 の正規化が実際に必要かを実測で確かめる）
6. 実行上限の値（条件の `budget` に実測にもとづく値を入れる）
7. `local-agent-monitor` の現行版との接続。**本仕様では接続していない。** 再開発を前提にしない

## 11. 限界

1. **1 課題・逐次実行の最小経路である。** 並列実行・複数課題・クラウド配備は含まない。
2. **ダミー実行器と合成使用量での検証であり、実モデルの実行を含まない。**
3. 使用量の正規化は、原本が `input_tokens` `output_tokens` を定義していることを前提にする。
   それ以外の定義の原本には対応しない。
4. `preserve.py` の `safe_name` は Windows の予約名（`CON` `NUL` など）を拒否しない。
   本リポジトリのパスでは問題にならないが、外部から与えるパッケージ ID には使わない。
5. 成果物ハッシュの並び順は評価器の比較規則に合わせているが、**非 ASCII のパスで一致するかは未確認**。
6. 集計は Run の数が少ない前提であり、統計的な扱いをしない。
7. 条件の `agent` を埋めないまま `--synthetic` で作った Run は、実モデル実行の記録として使えない。
