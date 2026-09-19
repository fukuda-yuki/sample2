# 品質評価器（`inner/evaluator`）

課題 `MS1-001` の成果物を入力に、[品質評価仕様](quality-spec.md) の要件台帳
（[`inner/spec/requirements.json`](../inner/spec/requirements.json)）に従って判定と根拠を返す実行プログラム。

- 実装: [`inner/evaluator/MusicStore.Evaluator/`](../inner/evaluator/MusicStore.Evaluator/)（C# / `net8.0` コンソール。NuGet 依存は `Microsoft.Data.Sqlite` のみ。§4.5.1 の保存契約を読み取り専用で観測するために使う）
- 版: `EvaluatorVersion = 1.0.0`、既定の評価版 `DefaultEvaluationVersion = 1.1.0`（[`Program.cs`](../inner/evaluator/MusicStore.Evaluator/Program.cs)、§6.2）
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
| `--evaluation-version` | 任意 | `1.1.0` | 評価版。評価 ID に含める |
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
- **見つからない場合と `dotnet publish` が失敗する場合は、成果物の欠陥である。** `R-001` を不合格にし、
  採点は続ける。静的な検査（`R-026` `R-027` `R-029`）は発行の前に済んでいるため、この場合も観測できる（§3）。
- `*.runtimeconfig.json` から起動アセンブリを特定できない場合も同様に成果物の欠陥である。
  起動できないために HTTP でしか観測できない要件は `blocked` になり、未評価として記録される。
- 評価側の障害として扱い、採点しないのは、**成果物の中身からは決まらない**次の場合だけである（§5）:
  台帳・カタログの読み込み失敗、台帳に載っている検査が実装に無い、成果物ディレクトリが存在しない、
  `--work` が空でない、`dotnet` が無い。
  **成果物のビルド失敗をこの一覧に含めない。** 含めると、実装の失敗が「判定できない」に化けて、
  不合格になるはずの成果物が採点されないまま記録される。

## 3. 実行の流れ

| 段階 | 内容 |
| --- | --- |
| A. 静的検査 | `csproj`・成果物ツリー・DB の位置だけを見る。**発行より先に実行する** |
| B. 起動 | 選んだプロジェクトを `dotnet publish` し、空きポートで起動、`GET /` が 60 秒以内に応答するまで待つ |
| C. 操作 | `Browse` → `Cart` → `Order` → `InvalidCheckout` → `Isolation` → `Restart` の順に固定手順を実行する |
| D. 判定 | 観測結果を 30 個の検査（`C-001`〜`C-030`）に通し、29 要件の判定に集約する |

- **静的検査を発行の前に置く。** ビルドできない成果物でも `R-026` `R-027` `R-029` は観測でき、
  ビルドの失敗は**成果物の欠陥（`R-001` の不合格）**として残る。発行の後に置くと、
  ビルドできない成果物で静的検査が前提を失い、**実装の失敗が評価側の障害に化ける**。
- **発行は成果物ディレクトリを書き換えない。** `dotnet publish` の既定では中間ファイルとビルド出力が
  プロジェクトの下（`obj/` `bin/`）に書かれるため、成果物を直接発行すると採点の前後で成果物の中身が変わる。
  成果物を作業ディレクトリへ複製し（`<work>/source`）、**複製に対して発行する**。発行の出力は
  `<work>/publish` に置く。採点の前後で成果物のファイル構成が変わらないことは
  [`outer/verify/verify.py`](../../outer/verify/verify.py) の `V-14` で確認する。
- 起動時の環境変数で `ConnectionStrings__MusicStoreEntities` を `<work>/store.sqlite` に固定し、
  `ASPNETCORE_ENVIRONMENT=Production` にする。**成果物の保存先は採点側が与える**（仕様 §4.1）。
- **`Restart` では、再起動の前後に注文行の存在を観測する。** 注文を作った後、`Stop()` の**前**に
  保存契約（仕様 §4.5.1）の `Orders` 表を `OrderId` で読み取り専用に引き、**行の存在を記録する**。
  同じ DB で起動し直して `GET /` が応答した後、**新しい注文を作る前**に同じ引き方でもう一度確認する。
  両方で同じ注文行が見つかったときだけ `R-005` を合格にする。
  表や列が無い場合は**保存契約違反**、評価器側の理由で読めない場合は**判定不能**（`error`）として
  区別して記録する。**観測できなかったことを合格にしない。**
- `--work` が既存で**中身がある場合は評価側の障害**として採点しない。前の実行の DB を引き継ぐと、
  「毎回空の DB から始める」という初期条件（仕様 §4.1）を満たさなくなるためである。
- 各操作の HTTP 応答は `evidence/http-*.log`、起動ログは `evidence/app-process.log`、発行ログは `evidence/publish.log` に残す。
  発行ログの先頭には**発行した複製の位置**（`SOURCE`）を書く。**採点した成果物と発行したソースを証跡から引ける**ようにするためである。
- 証跡の書き出しは `finally` で行う。**途中で失敗しても証跡を残す。**

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

**同じ評価器ビルドの下では、成果物のハッシュが同じで、評価版と条件が同じなら、判定は安定する**（仕様 §6）。
同じ成果物を再採点すると新しい評価 ID が発行され、以前の記録は上書きしない。

### 6.2 評価版と評価器ビルドは別のものを指す

判定の再現性には 2 つの前提がある。混同しないよう分けて扱う。

| 何の同一性か | 何で表すか | 何が変わると上がるか |
| --- | --- | --- |
| **判定の意味**（検査集合・合否規則・配点・分母） | `evaluation_version` | 意味が変わったときだけ。証跡の形式やログの追加では上げない |
| **採点したビルド** | `evaluatorSha256`（評価器が `Assembly.Location` から求める） | 評価器をビルドし直すたび |

`evaluatorSha256` は**ソースの版ではなく、ビルドしたもの**を指す。同じソースでも
ビルドしたパスが変われば値が変わる（[`inner/calibration/README.md`](../inner/calibration/README.md) §4.1 に
実測がある）。**ソースファイルのバイト列（改行コード）でも変わる**（同 §4.2 に実測）。
同じマシン・同じパスでの作り直しでは同じ値になることを確認しているが、
別のマシンや別のパスでの一致は期待しない。
**この値の一致を「同じ意味の判定をする評価器である」ことの根拠に使わない。**
記録に使う値は**追跡ファイルを書き換えていないクリーンな作業ツリー**で測り、
**記録コミットの後で作り直して同じ値になることを確かめる**（同 §4.3。外側の検証では
`bin` `obj` を消した作り直しを `V-0b` が確認する）。

**ビルドしたコミットは値に混ぜない。** 実際には**コミットが 2 つの経路で値に入っていた**。
どちらも既定で有効であり、両方を切らないと値はコミットのたびに動く。

| 経路 | 何が起きるか | 切る指定 |
| --- | --- | --- |
| `AssemblyInformationalVersion` | アセンブリに `1.0.0+<コミット>` が入る | `IncludeSourceRevisionInInformationalVersion` = `false` |
| sourcelink 文書 → 移植可能 PDB | SDK が `obj/…/MusicStore.Evaluator.sourcelink.json` を作る。中身は `…/raw.githubusercontent.com/<owner>/<repo>/<コミット>/*`。Roslyn がこれを **PDB に入れ**、アセンブリはその **PDB の id をデバッグディレクトリに持つ**ため、**コミットがアセンブリのバイト列まで間接的に届く** | `EnableSourceLink` = `false` |

その既定のままでは、**文書だけのコミットでも値が変わる**（`45a2b4a` で測った値と `6675e19` で
測った値が食い違った）。すると測定値を記録するコミット自身が次のビルドの値を変えてしまい、
**記録した値と、その記録を含むコミットが一致しえない**。
1 つ目だけを切った状態でも値はコミットのたびに動いており、値の中にコミットの文字列が無いことから
2 つ目の経路を特定した（`-p:EnableSourceLink=true` でビルドすると値が変わり、
`false` ではコミットをまたいで同じ値になる。実測は
[`inner/calibration/README.md`](../inner/calibration/README.md) §4.2 §4.3）。
評価器はこの属性も sourcelink 文書も読まないため、
`MusicStore.Evaluator.csproj` で両方を切って**値がソース・パス・SDK だけで決まる**ようにした。
`AssemblyInformationalVersion` が `1.0.0` になること、`SourceRevisionId` を与えても値が変わらないことを
確認している。
**この変更は判定の意味を変えないので `evaluation_version` は据え置く**（本節の規則）。
ビルドしたコミットは、条件の `evaluation.evaluator_build.source_commit` に追跡用として残す。

`evaluation_version` は `evaluationId` に入るが、`evaluatorSha256` は入らない。
**評価器を差し替えて評価版を据え置くことは許すが、無言で続けてはならない。**
据え置くときは、意味が変わっていないことを校正の再実行で示し、
[`inner/calibration/README.md`](../inner/calibration/README.md) に記録する。

**逆に、判定の意味が変わる改訂では評価版を上げる。** 本改訂（`1.0.0` → `1.1.0`）がそれにあたる。
`R-005` の観測方法を「再起動前後の注文番号が異なること」から「保存契約（仕様 §4.5.1）の
注文行が再起動の前後で残ること」に変えたため、**同じ成果物の判定が `pass` から `fail_critical` に
変わりうる**。実装を仕様に合わせるだけの修正（同 §4.4 の 5 点）とは区別し、
[`docs/decision-log.md`](decision-log.md) D-17 として記録している。

外側の実行基盤は、採点のたびに**呼び出した評価器のハッシュを自分で実測**し、
`record.json` と `evaluations/index.jsonl`、集計表の `scoring.evaluator_sha256` に残す。
条件の `evaluation.evaluator_sha256` に値を入れておくと、固定値が使われる
（`null` は「固定しない」。固定しなくても実測値は毎回記録される）。

**固定するときは、値だけを入れてはならない。** この値はビルドしたパスと SDK に依存するため
（[`inner/calibration/README.md`](../inner/calibration/README.md) §5-13、本節の実測）、別のパスで
ビルドした評価器ではすべての採点が一致しなくなる。
条件の `evaluation.evaluator_build` に、ソースの位置・アセンブリ・ビルドコマンド・
**ビルドに使った SDK の版**・固定値の出所を書く。固定値があって `evaluator_build` が
欠けている場合、外側は採点を始める前に条件の誤りとして拒否する。

固定値と一致しないビルドでの採点も、例外で捨てずに `rejected_mismatch` の記録として残す。
`record.json` の `mismatches` に固定値と実測値の両方が入るため、
**静かに通ることも、診断できないまま消えることもない**。
詳細は [`docs/outer-harness.md`](outer-harness.md) §6.4。

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
   **旧実装の成果物名・旧実装を指定する起動記述・旧フレームワークの信号で判定し、名前空間やアセンブリ名の語だけでは判定しない。**
   IIS Express also hosts ASP.NET Core. A standard `launchSettings.json` profile
   is not a legacy dependency; the IIS Express signal requires an explicit
   `MvcMusicStore` legacy path. This corrects the first real-model diagnostic's
   R-029 false failure without changing the published success contract (1.1.0).
   [Microsoft's ASP.NET Core launch-profile documentation](https://learn.microsoft.com/en-us/visualstudio/debugger/how-to-enable-debugging-for-aspnet-applications?view=vs-2022)
   includes both Kestrel and IIS Express profiles.
   名前を `MvcMusicStore` に保っただけの正常な実装は合格する
   （[`inner/calibration/README.md`](../inner/calibration/README.md) §4.4）。
   **コメント・説明文の旧名称も判定の根拠にしない。** 走査の前にコメントを除去し、
   残った旧名称は診断情報（`legacy_mentions`）として記録するだけにしている。
   文字列リテラルは残すため、**旧実装を起動する記述は引き続き検出する**
   （`neg-legacy-wrapper` は `fail`、`var-legacy-comment-mention` は `pass`。同 §4.5）。
   この区別も字句解析に基づく近似であり、**動的な起動経路（リフレクション、外部コマンドの
   文字列組み立て）は依然として検出しない。**
   `R-026` `R-027` は起動対象プロジェクトの `csproj` に限る（仕様 §7.2-3）。
4. **観測範囲の限界。** 注文合計（`Order.Total`）は旧実装の HTTP 契約から観測できないため評価対象外とし、
   かご合計で代替している（仕様 §2.1、§7.2-4）。
   `R-005` は保存契約（仕様 §4.5.1）の `Orders` 表の行を**読み取り専用で**観測し、
   再起動の**前**に存在した注文行が、同じ DB で再起動した**後**も存在することを確認する。
   注文を削除して採番だけ継続する実装は `fail_critical` / `R-005` になる
   （`neg-wipe-orders-only`。同 §4.5）。
   **確認しているのは注文行の存在だけであり、金額・住所・明細の内容や複数注文の順序は確認していない。**
   表や列が無い場合は「注文が消えた」事実と区別して**保存契約違反**として記録し、
   評価器側の理由で読めない場合は**判定不能**（`error`）として別に記録する。
   `R-005` の合格を「注文が失われない」ことの完全な証明として使わない。
5. **校正は部分検証である。** 用意した fixture は課題の全誤りを網羅しない（仕様 §7.2-5）。
   校正の記録は [`inner/calibration/README.md`](../inner/calibration/README.md)。
   評価版 `1.0.0` では負例のうち 1 件（`wipe-orders-only`）が**見逃すことを期待として固定されていた**。
   その記録は履歴として残し、評価版 `1.1.0` では `fail_critical` になることを実測している（同 §5-17、§4.5）。
6. **採点対象外の品質は測っていない。** 仕様 §2.1 の項目について、良いとも悪いとも主張しない。
7. **表示の検査が正規化するのは、引用符の流儀と `=` 前後の空白までである。** 属性を `"` で書いても `'` で書いても
   同じ結果になること（同 §4.4）、`id="cart-total"` と `id = "cart-total"` が同じ結果になること、
   属性の順序を変えても結果が変わらないことは確認している（同 §4.5）。
   一方、要素の入れ子の変え方、改行の入れ方など、**他の等価な書き方については宣言したケースが無い**。
   表記差を許容することと値の誤りを見逃すことは別であり、空白を許容した表記のまま数量を誤らせた
   `neg-whitespace-wrong-quantity` は `fail_critical` になる（同 §4.5）。
8. **発行が成果物を書き換えないことは、正例 1 件の成果物でしか確認していない。**
   `V-14` は `bin` `obj` をプロジェクト直下に置く既定の SDK 構成で測っている。
   出力先を変えた成果物、複数プロジェクトを含む成果物では確認していない
   （[`outer/verify/README.md`](../outer/verify/README.md) 限界 19）。

## Evaluation 1.2.0 observation repair

The current task publishes the order DOM marker and denial statuses rather than
assuming an English sentence. Duplicate, missing, commented and incorrect order
markers cannot satisfy R-021. A 200 completion response to a different session
cannot satisfy R-022 even when it uses another label. R-023/R-024 compare the
cart's album/quantity pairs and total, require a checkout form input, and compare
read-only order-ID snapshots around invalid checkout. Each rejection has its own
session. See the predeclared calibration matrix for localized positive cases
and cart mutation/order creation negative cases. The evaluator refuses to pair
the 1.2.0 ledger with a historical evaluation version. Saved 1.1.0 Runs continue
to use their original frozen evaluator/assets; the old schema 1 default is kept.

A real preload diagnosis also exposed a filename-only R-029 false failure.
A retained `MvcMusicStore.csproj` is inspected as XML: a .NET 8+ Web SDK project
is not classified as the old application solely by that filename. Actual
Framework projects and explicit legacy launch commands remain negative cases.
Static legacy detection remains a documented heuristic, not proof against
arbitrary obfuscated wrappers.
# Independent browser evidence for cart removal (PMO review)

The optional pair `--browser-cart-evidence <receipt.json> --review-run-instance-id <id>`
adds independently collected, post-click browser DOM observations to C-015/C-016.
Both the existing HTTP check and the browser observation must pass. A later GET
cannot replace the captured post-click screen. Public requirements and JSON field
requirements are unchanged; `cartTotal` is not made a mandatory response field.

The schema and validation are in `BrowserCartReview.cs`. A receipt declares an agent
actor, artifact/spec hashes, Run instance ID, and exactly two removals. Each removal
references hashed before/after browser JSON and screenshots under the receipt's
directory. Captures must have the same tab and origin, start at the cart URL, have
increasing timestamps, and show the correct populated starting state. Invalid provenance is an evaluator error,
not a product failure. Hashes verify byte identity; the independent collector is
trusted for action attribution and screenshot authenticity.

Without a receipt, compatibility scoring remains HTTP-only and emits
`browserCartCoverage: not_run_http_only`; it does **not** establish UI acceptance.
With valid evidence it emits `agent_observed_C-015_C-016`, the receipt hash and Run
instance ID. This original adapter is now connected to the automatic runner below.
`research/pmo_scenario_correction.py` saves isolated controls and corrections from
the three PMO review targets without changing original evaluations or research Runs.
See [the review report](ms1-pmo-scenario-review-20260919.md) for actual browser
observations, remaining limitations, and the gate decision.

## Required browser phase for research evaluation 1.2.0

`outer.harness.evaluate.score_run` first saves the HTTP/static evaluation under
`http-only/`, then calls `browser_cart.complete_evaluation`. A read-only copy of
that evaluation's published application runs in the original Docker image with
a fresh SQLite database, a dedicated bridge (outbound masquerading disabled),
and an ephemeral port bound to host loopback. The browser loads the application's
subresources normally, including external scripts; their URL, response status and
body hash are recorded. Failed external-script observation is incomplete, not a
product failure. No local-only dependency requirement is imposed on submissions.
The fixed source and evaluator assets are never writable application mounts.

`inner/browser/cart-review.cjs` uses an installed Playwright and Chromium. Set
`NODE_PATH` when Playwright is supplied outside local Node module resolution;
`SAMPLE2_BROWSER_EXECUTABLE` selects an existing executable explicitly. Optional
`SAMPLE2_NODE` selects Node. Missing prerequisites produce evaluator faults, not
an HTTP-only fallback. See the [installed-browser API](https://playwright.dev/docs/browsers)
and [isolated contexts](https://playwright.dev/docs/api/class-browser#browser-new-context).
No browser or model is downloaded or dispatched by the scorer.

Each check has a new browser context. Preparation uses the public AddToCart route
before verifying exactly one row with quantity 2 or 1 and total 17.98 or 8.99.
The collector clicks the row's visible removal link/button (public identifier,
accessible name, or removal form), and reads the same live page every 200 ms.
It stops after the expected visible state remains stable for 500 ms with no
outstanding requests, or after 10 seconds. Navigation has a 15-second limit and
click actionability a 5-second limit. Application navigation and asynchronous
updates are observed; no collector reload, separate post-click GET, direct
removal POST, injected handler, or application patch supplies the after-state.
The receipt records DOM, visible DOM projection, PNG, timestamps, network events,
Playwright trace, browser/library/executable identity, and these timing conditions.

The same-origin page reached by the application is the observed result. A form
that navigates to a raw JSON document fails the visible-cart requirement; it is
not an evaluator fault. An origin/tab/Run/artifact/spec identity mismatch or
missing/corrupt evidence is an evaluator fault. Both populated preconditions are
validated independently by `BrowserCartReview`.

`--browser-cart-baseline <directory>` composes the two captures with a bound,
complete saved HTTP result set. It never executes unrelated scenarios, cannot
turn an HTTP failure into a pass, and inherits all other requirements unchanged.
The result includes the baseline evaluation/results hashes and observation scope.
This lets saved R-029 corrections remain the baseline for a subsequent browser
correction without rewriting any acquisition files. The evaluator implementation
is 1.1.0; the public spec and evaluation contract stay 1.2.0.

HTTP-only compatibility output has `researchStatus: incomplete`. Ordinary research
scoring requires observed evidence and complete evaluation before adoption.
Aggregation rechecks the receipt and every referenced DOM/PNG hash rather than
trusting a stored `pass` or coverage string. Historical HTTP-only scores remain
available as `reported_http_or_prior_quality/verdict`; research `quality/verdict`
are null when browser verification is absent. Research summaries also exclude
saved HTTP-only passes from quality-pass counts. No acquisition output is edited.

Actual positive, defective, launch-fault and evidence-fault controls, the 24-artifact
application and reproduction commands are in the [uniform correction report](ms1-browser-cart-20260919-report.md).
