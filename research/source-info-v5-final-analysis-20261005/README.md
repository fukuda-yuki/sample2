# 今回の100ペア・200原割付の再分析

対象は `source-information-two-families-20261003-v5-100p2` です。原割付bundleのSHA256は
`f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334` です。
Music StoreとContosoUniversityの2つの固定source family、4つの固定variantに各25ペアを割り付けています。
既存のRelease `result` のMusic Store単独cohortと混ぜません。

研究目的は、初期source情報の提示が要求品質とRun全体のprovider input/output tokenにどう関係するかを調べることです。
早期終了・品質低下でtokenが減っただけの結果を改善とは扱いません。100ペアは100種類の独立アプリケーションではありません。

## 統計表をofflineで再計算する

Windows、CPython **3.14.4** を使用します。分析計算はPython標準ライブラリのみです。
再計算コマンドが実行する4つの分析CLIは、provider、モデル、評価器、Docker、Git、downloaderを呼び出しません。
APIキーは必要ありません。Linux対応は今回の範囲外です。

1. 今回専用Releaseから `analysis.zip` を取得し、新しいフォルダーへ展開します。
2. Release本文に記載された `MANIFEST.json` のSHA256を別の信頼経路として控えます。ZIP内の値を無条件に信頼しません。
3. 展開したpackage rootで、PowerShellから次を実行します。出力先はpackageの外の、まだ存在しないフォルダーにします。

```powershell
python -B -X utf8 .\code\reproduce_public_analysis.py `
  --package-root . `
  --expected-manifest-sha256 '<Release本文のMANIFEST SHA256>' `
  --out '..\recalculated-new'
```

readerは全packageファイルのサイズ・SHA256を検証し、4つの分析CLIを実行します。
全14結果ファイルについて、元の公開結果と生成されたbyte・SHA256が完全に一致しなければ失敗します。
`actual-recalculation-receipt.json` が成功結果です。途中出力があるだけでは成功扱いしません。
出力先の再利用や元の公開表の上書きは行いません。

## データと結果

| 場所 | 内容 |
|---|---|
| `data/public-dataset.json` | 全200原割付、UUID、arm、variant、実取得phase、実行・評価・品質・usage状態 |
| `data/public-check-audit.json` | 固定要求checkの原判定、証拠hash、派生状態、手動監査の有無と限界 |
| `data/all-100-public-pairs-catalog.json` | 全100公開pairの元UUID、Release、manifest・ZIP/part・公開review・scanのURL、サイズ、SHA256 |
| `data/public-model-identity.json` | 全200の要求/応答model metadata、未観測状態、request件数。provider内部実行の証明とは区別 |
| `data/public-stop-ledger.json` | 全200の終了理由と保存STOP・明示target scope。共通STOPから製品不良の原因やtrigger Runを推定しない |
| `results/core/` | 全割付の品質bounds、全Run token、variant/family、27欠測token scenario、phase・実時間overlap |
| `results/supplementary-results.json` | 全要求check、分布、順序、実行・採点・quality・usageによる7つの選択条件 |
| `results/exploratory/` | ratio/log ratio、影響、trim/winsor、variant/family除外、session/wave依存感度 |
| `results/tables/` | 全200Run・100ペア・要求check・27scenarioのCSVと検証記録 |
| `report/research-report-ja.md` | 原証拠監査、各分析結果、競合説明、制限、対処案 |
| `environment.json` | 実再計算環境と取得環境参照。分析hostと測定workerを区別 |

`contract/` の指示・protocol・来歴は、元の固定設計と公開用派生資料の記録です。
来歴内の「実完了・公開未実施」は、その資料の準備時点を指します。最終取得の状態はmanifestの完了receipt SHAとreportで区別します。
元のsingle-pair設計と、その後に明示的に許可された実wave/cap、取得後の分析・共有依頼を混同しません。

tokenの主な比較は **preload − explore** です。input＋outputを一度だけ加えます。
cache input、reasoning outputはその内数であり、もう一度加算しません。
usage不完全なRunの全Run tokenは `null`、観測partialは別fieldです。partialを検証済み下限とは呼びません。
CSVの `null` は0や空文字ではありません。

品質の派生判定では全必須checkの有限な観測を扱います。
全要求passとcritical failureは別のendpointです。原verdictや数値scoreも保持します。
raw fail・blocked・未採用・評価器faultを自動的に製品違反へ変換しません。
checkごとのsource・原観測を確認しても判断が決まらない場合はunknownを残します。
public-check-auditのhash鎖を再計算できることは、原品質証拠を独立に再監査したことを意味しません。

主な解析は全200を分母に維持します。complete-case、両Run成功、別family、外れ値処理は条件付き・探索的な結果です。
全27の欠測token scenarioと利用不能なcellを公開します。都合の良い条件だけを主結果として選びません。
欠測全Run tokenの正当な有限上限がなければ、全割付token差は点識別できません。
request/call数は独立Run数ではありません。独立pair・clusterの仮定と実観測の区別はreportに記録します。

## 原公開pairの証拠を取得する

全統計表の再計算には、全pairのダウンロードは不要です。
原公開証拠を確認する場合は、同じReleaseのcatalog SHA256を使用し、次を実行します。

```powershell
python -B -X utf8 .\code\download_verified_public_pairs_v2.py `
  --catalog .\data\all-100-public-pairs-catalog.json `
  --expected-catalog-sha256 '<Release本文のcatalog SHA256>' `
  --pair all `
  --out '..\all-public-pairs-new'
```

`--pair 91` のように1ペアだけを指定することもできます。
readerは既存sample2のHTTPS Releaseを匿名取得し、全size/SHA、結合ZIP、全展開ファイル、元pairとUUIDの割付を検証します。
公開reviewとscanも元SHAで取得します。内容を実行せず、モデル・評価器を呼び出しません。
受信・展開・部分的なファイル生成だけでは完了ではありません。全指定pairのreceiptを確認します。
通信障害でpartial出力が残った場合は保持し、別の新規出力先で再取得します。これは公開済みbyteの再取得であり、新規サンプリングではありません。

`current-all100-public-data-collection.zip` は、これら既存公開pair ZIP/parts・manifest・公開review・scan、同じcatalog、同じ分析ZIPを集約したものです。
`COLLECTION-MANIFEST.json` は各収録資産のsize/SHA256を記録します。余分なRelease資産は自動収録しません。
分析ZIPの公開レビューreceipt・cohort結合と、各pairの匿名再取得・全SHA確認は別々に検証します。

## 公開範囲と権利

全200原割付は公開表とcatalogに残します。秘密、native auth、所有state、非公開oracle/評価DB/runtime/binary、再配布条件を確認できない素材は公開copyから除外します。
各pairのMANIFESTとTHIRD-PARTY-NOTICESにhash・理由・影響を記録し、private原本を保持しています。
公開copyはprivate原本の全byteではありません。数値のoffline再計算、保存品質証拠の独立監査、全評価器の環境再現は別の達成範囲です。
省略された素材について、full evaluator replayや完全な画像観測再現の成功を主張しません。

MS-PL、OpenCode MIT、教育課題のApache 2.0など、各資産の既存noticeとlicenseを保持します。
sample2の公開状態だけから、新しいrepository全体またはデータ全体の包括的な再利用licenseを推定しません。
AIによる公開privacy/rights確認と有限な自動scanの限界をreportに記載します。`human_review` は `not_run` です。
