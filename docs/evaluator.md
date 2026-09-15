# 品質評価器（`inner/evaluator`）

課題 `MS1-001` の成果物を入力に、[品質評価仕様](quality-spec.md) の要件台帳
（[`inner/spec/requirements.json`](../inner/spec/requirements.json)）に従って判定と根拠を返す実行プログラム。

- 実装: [`inner/evaluator/MusicStore.Evaluator/`](../inner/evaluator/MusicStore.Evaluator/)（C# / `net8.0` コンソール、NuGet 依存なし）
- 版: `EvaluatorVersion = 1.0.0`（[`Program.cs`](../inner/evaluator/MusicStore.Evaluator/Program.cs)）
- 評価の妥当性の根拠と限界は [品質評価仕様 §7](quality-spec.md#7-評価器の妥当性の根拠と限界) に記録している。

## 1. 呼び出し方

```
MusicStore.Evaluator --artifact <dir> --out <dir>
                     [--spec <requirements.json>] [--catalog <catalog.json>]
                     [--evaluation-version <v>] [--sequence <n>] [--work <dir>]
```

| 引数 | 必須 | 既定 | 内容 |
| --- | --- | --- | --- |
| `--artifact` | 必須 | — | 採点対象の成果物ディレクトリ |
| `--out` | 必須 | — | 評価記録の出力先。無ければ作成する |
| `--spec` | 任意 | 実行ファイルから上方探索して `inner/spec/requirements.json` | 要件台帳 |
| `--catalog` | 任意 | `<spec のディレクトリ>/catalog.json` | 期待する初期カタログ |
| `--evaluation-version` | 任意 | `1.0.0` | 評価版。評価 ID に含める |
| `--sequence` | 任意 | `1` | 評価 ID の連番 |
| `--work` | 任意 | `<out>/work` | 発行・DB・作業ディレクトリ |

- `--spec` を明示するときは、台帳と同じディレクトリに `catalog.json` が無ければ `--catalog` も明示する。
- 未知の引数、値の欠落は usage を標準エラーに出力し、終了コード `1` で終わる。

実行例（校正スクリプトと同じ形）:

```powershell
dotnet .\inner\evaluator\MusicStore.Evaluator\bin\Release\net8.0\MusicStore.Evaluator.dll `
  --artifact .\inner\fixtures\reference --out .\runs\cal-ref-001
```

**成果物ディレクトリの中に研究用の文書を置かない。** 成果物ハッシュは成果物ディレクトリ配下の
全ファイル（`bin` `obj` `.git` を除く）を対象にするため、中の文書を編集すると
同じ実装でもハッシュが変わる（[`inner/fixtures/README.md`](../inner/fixtures/README.md)）。

**ハッシュはバイト列の同一性であり、実装の同一性ではない。** 改行コードが変わればハッシュも変わる。
成果物のソースは `.gitattributes` で LF に固定してあるので、記録したハッシュを再現するには
作業ツリーを `git checkout` が書き出す改行コードに揃えておく必要がある
（[`inner/calibration/README.md`](../inner/calibration/README.md) §2.1）。

## 2. 採点対象の選び方

成果物ディレクトリ配下を走査し、`Microsoft.NET.Sdk.Web` を SDK に持つ `csproj` を起動対象にする。

- 複数ある場合は**相対パスの短いもの**を選ぶ（規則であって、実装の優劣判断ではない）。
- 見つからない場合、`dotnet publish` が失敗する場合、`*.runtimeconfig.json` から起動アセンブリを特定できない場合は、
  成果物の欠陥としてではなく**評価側の障害**として扱い、採点しない（§5）。

## 3. 実行の流れ

| 段階 | 内容 |
| --- | --- |
| A. 起動 | 選んだプロジェクトを `dotnet publish` し、空きポートで起動、`GET /` が 60 秒以内に応答するまで待つ |
| B. 操作 | `Browse` → `Cart` → `Order` → `InvalidCheckout` → `Isolation` → `Restart` → `Static` の順に固定手順を実行する |
| C. 判定 | 観測結果を 30 個の検査（`C-001`〜`C-030`）に通し、29 要件の判定に集約する |

- 起動時の環境変数で `ConnectionStrings__MusicStoreEntities` を `<work>/store.sqlite` に固定し、
  `ASPNETCORE_ENVIRONMENT=Production` にする。**成果物の保存先は採点側が与える**（仕様 §4.1）。
- 各操作の HTTP 応答は `evidence/http-*.log`、起動ログは `evidence/app-process.log`、発行ログは `evidence/publish.log` に残す。

## 4. 判定の状態

検査の状態は 4 つ（仕様 §5.2）。

| 状態 | 意味 |
| --- | --- |
| `pass` | 期待どおり |
| `fail` | 期待と異なる。成果物の欠陥 |
| `blocked` | 前提不成立のため判定に進めない。成果物の欠陥とは呼ばない |
| `error` | 評価側の障害。成果物の品質を判定できない |

要件の状態は、その要件に属する検査から次の優先順で決まる:
`error` > `fail` > `blocked` > `pass`。

**`blocked` を `fail` に置き換えない。** 前提が成立しない入力を「要件違反」として数えると、
成果物の欠陥ではないものを欠陥として記録してしまう。`blocked` は品質点の分母に残し、
未評価範囲として `uncheckedScope` に列挙する。

## 5. 全体判定と品質点

```
error が 1 つでもある            → verdict = error, quality = null
それ以外                          → quality = 丸め(通過要件数 × 100 / 要件総数, 2 桁)
  重大要件（severity = critical）の失敗がある → verdict = fail_critical
  それ以外の失敗がある                       → verdict = fail
  失敗は無いが blocked がある                → verdict = blocked
  それ以外                                   → verdict = pass
```

- **評価側の障害があるときに品質点を返さない。** `0` に置き換えると「出来が悪い成果物」と
  区別できなくなるため `null` にする。終了コードは `2`。
- 重大要件は 9 件（`R-001` `R-002` `R-005` `R-012` `R-013` `R-018` `R-022` `R-026` `R-027`）。
  一覧と理由は仕様 §5.3。
- `quality` は「29 要件のうち何割を通したか」であり、モダナイズ品質全般の点数ではない（仕様 §7.2）。

## 6. 出力

`--out` の直下に次を書く。

| 出力 | 内容 |
| --- | --- |
| `evaluation.json` | 評価 1 回分の結果（下記） |
| `results.jsonl` | 検査ごとに 1 行（`requirementId` `checkId` `input` `expectation` `observation` `judgement` `evidence`） |
| `evaluator-manifest.json` | 評価器・台帳・成果物のハッシュ、選んだプロジェクト、発行先、DB パス、ポート、アプリのプロセス ID、検査 ID の突合結果 |
| `evidence/publish.log` | `dotnet publish` の標準出力・標準エラー |
| `evidence/app-process.log` | 起動したプロセスの標準出力・標準エラー。起動のたびに `===== app process (pid <PID>, url <URL>, started <時刻>) =====` の行を先に書く（下記） |
| `evidence/http-*.log` | 操作ごとの HTTP 要求・応答の抜粋 |

### 6.1 アプリのプロセスを後から特定できるようにする

評価器は成果物のアプリを子プロセスとして起動する。**評価器自身が強制終了されると
`Dispose` に到達せず、アプリが残ることがある**（実際に 1 度起きた）。
そのとき「どのプロセスが残ったのか」を後から突き合わせられるよう、次を残す。

- `evidence/app-process.log` の先頭行に `pid` と `url` を書く。**`Stop()` ではなく `Start()` で
  書く**ため、評価器が道連れにされなくても残る。
- `evaluator-manifest.json` の `appProcessIds` に、起動したアプリのプロセス ID を起動順に並べる
  （`appProcessId` は最後の 1 つ、`port` は使用したポート）。再起動を挟む評価では 2 つ以上になる。

この記録は**特定のためのものであり、残骸の除去ではない。** 残骸を止めるのは
呼び出し側（外側の実行基盤）の責務である（[`docs/outer-harness.md`](outer-harness.md) §6.3）。

`evaluation.json` の主な項目:

| 項目 | 内容 |
| --- | --- |
| `evaluationId` | `{課題ID}-{成果物ハッシュ先頭12桁}-{評価版}-{連番}` |
| `taskId` `taskTitle` `specVersion` | 台帳から取得。台帳が読めない場合は `taskId` を `unknown` にする |
| `specSha256` `artifactSha256` | 台帳と成果物のハッシュ。成果物の同一性は `bin` `obj` `.git` を除いた全ファイルの「相対パス＋内容ハッシュ」から求める |
| `sourceRepository` `sourceCommit` | 台帳に固定した旧実装の版 |
| `startedAt` `finishedAt` | 実行時刻（ISO 8601） |
| `verdict` `quality` | §5 の規則 |
| `requirementCount` `passedCount` `failedCount` `blockedCount` `errorCount` | 要件の集計 |
| `criticalFailed` | 落ちた重大要件 |
| `uncheckedScope` | 未評価（`blocked`）と判定不能（`error`）の要件と理由 |
| `evaluatorFaults` | 評価側の障害の内容 |
| `requirements[]` | 要件ごとの判定・重大度・根拠・期待・落ちた検査 |

**成果物のハッシュが同じで、評価版と条件が同じなら、判定は安定する**（仕様 §6）。
同じ成果物を再採点すると新しい評価 ID が発行され、以前の記録は上書きしない。

## 7. 終了コード

| コード | 意味 |
| --- | --- |
| `0` | 判定を返した（`pass` `fail` `fail_critical` `blocked` のいずれか） |
| `1` | 呼び出し方の誤り（引数の欠落・未知の引数） |
| `2` | 評価側の障害。`evaluation.json` は `verdict = error`、`quality = null` で書かれる |

- 成果物が要件を満たさないことは異常終了ではない。**成果物の失敗は終了コード `0` で返す。**
- 終了コード `2` でも `evaluation.json` と（空の）`results.jsonl` を書く。採点できなかった事実を記録に残すため。

## 8. 台帳との突合

評価器は起動時に、台帳に載っている全検査 ID が実装に存在することを確認する。
存在しない検査 ID があれば**採点せず**評価側の障害として `error` を返す。
これにより「台帳に書いたが実装していない要件」を黙って通さない。

## 9. 限界

1. **正例を評価器と同じ作業者が書いている。** 正例が通ったことは妥当性の根拠にならない（仕様 §7.2-1）。
2. **旧実装を実行していない。** `legacy` を根拠とする期待値はコード読解に基づく（仕様 §7.2-2）。
3. **静的な検査の限界。** `R-029` は成果物ツリーの走査によるヒューリスティックであり、間接的なラッパー化を証明しない。
   `R-026` `R-027` は起動対象プロジェクトの `csproj` に限る（仕様 §7.2-3）。
4. **観測範囲の限界。** 注文合計（`Order.Total`）は旧実装の HTTP 契約から観測できないため評価対象外とし、
   かご合計で代替している（仕様 §2.1、§7.2-4）。
5. **校正は部分検証である。** 用意した fixture は課題の全誤りを網羅しない（仕様 §7.2-5）。
   校正の記録は [`inner/calibration/README.md`](../inner/calibration/README.md)。
6. **採点対象外の品質は測っていない。** 仕様 §2.1 の項目について、良いとも悪いとも主張しない。
