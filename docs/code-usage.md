# 取得・評価コードの利用と検証

このリポジトリは旧名 `sample2` の履歴を引き継いだ `modernization-eval` です。
最新の取得・評価実装を Git で管理します。原本データ、実行時の設定、固定済みの
評価バイナリは別の保存資材であり、ソースを clone しただけでは揃いません。

## 入口

| 用途 | 入口 | 必要なもの |
| --- | --- | --- |
| 取得と評価の並行処理 | `python -m research.acquisition_pipeline` | 承認された固定計画、`config.json`、入力・評価・ブラウザーの固定資材、実行環境 |
| 保存済みペアの評価・保存 | 同モジュールの `evaluate` | 当該試行の記録、生成物、元の固定コントローラーと評価資材 |
| 個別Runの採点 | `outer/harness/evaluate.py` の `score_run` | Runの固定入力・生成物・評価資材、所有資源と停止の証跡 |
| catalog原本のsnapshot・抽出・梱包 | `research.catalog_cohort_snapshot` / `extract` / `bundle` | それぞれの `--help` に示す保存済み原本・出力先 |
| catalogの集計・保存証拠確認 | `research.catalog_cohort_analysis` / `evidence` | snapshot、分析用依存パッケージ（集計のみ） |
| 過去のwave運転・4ペアの回収 | [tools/acquisition](../tools/acquisition/README.md) | 当時の専用設定と保存環境。新規実験の入口ではありません |

catalogの5モジュールは第1回catalogコホート用です。新100のデータ形式へそのまま
適用できるとは扱いません。各名前は `research.catalog_cohort_` で始まります。

## 新しいcheckoutからの確認

Python 3.14、Git、.NET SDK 8.0.425（`global.json`）を用います。
ブラウザー収集の実行には Node.js、Playwright、Chromium が別途必要です。

```powershell
git clone https://github.com/fukuda-yuki/modernization-eval.git
cd modernization-eval
python -B -X utf8 -m research.acquisition_pipeline --help
python -B -X utf8 -m research.catalog_cohort_bundle --help

# 研究側の試験・集計用依存を隔離して導入
python -m venv .venv-analysis
.\.venv-analysis\Scripts\python -m pip install -r research/requirements-confirmatory.txt

# モデル送信を伴わない回帰試験
python -B -X utf8 -m unittest discover -s outer/tests -p 'test_*.py'
.\.venv-analysis\Scripts\python -B -X utf8 -m unittest discover -s research/tests -p 'test_*.py'
dotnet run --project inner/evaluator/MusicStore.Evaluator.Tests --configuration Release
dotnet run --project inner/evaluator/Education.Evaluator.DiagnosticsChecks --configuration Release
dotnet run --project inner/evaluator/LegacyScan.Tests --configuration Release
node --test inner/browser/education-identity.test.cjs
```

一部試験は非公開の保存証拠がなければ skip します。実ブラウザーのローカルfixture
試験は、`NODE_PATH`、`SAMPLE2_BROWSER_EXECUTABLE` を利用するインストール先に設定し、
`SAMPLE2_LIVE_BROWSER_FIXTURES=1` を指定すると実行できます。試験の成功は、
元の研究データの再採点や新しいモデル取得の完了を意味しません。

catalog集計も同じ分析用環境を使います。

```powershell
.\.venv-analysis\Scripts\python -B -X utf8 -m research.catalog_cohort_analysis --help
```

## 固定計画を使うとき

`run <config.json> --repo <checkout>` は実モデル取得を開始する操作です。
単なる確認には `--help` と上記試験を使います。新しい取得を行うには、その取得に
有効な指示、計画、累積上限と資材が必要です。過去の完了済み設定をそのまま
新しい研究の設定にしません。

保存済み評価は当該epochの `source_commit` と `source_pins`、入力・評価・ブラウザーの
ハッシュを照合します。固定コントローラーは `git worktree add --detach <path> <commit>`
で復元できますが、記録内の絶対パスが存在しなければ復元・対応付けも必要です。
ハッシュ検査を外したり、過去の固定記録を新checkoutの値で上書きしたりしません。
保存評価の失敗は新規モデル送信へ振り替えません。

実行の詳細は [acquisition pipeline](acquisition-pipeline-20261008.md)、
原本の保存先は [miscの保管カタログ](https://github.com/fukuda-yuki/misc/blob/main/research-storage/transfer-catalog.json)
と[復元手順](https://github.com/fukuda-yuki/misc/blob/main/research-storage/README-ja.md)を参照します。
保管先のアクセス権が別途必要です。ZIPのソースsnapshotとGitの履歴は別の保管物です。

取得時の固定コードは `afd5f083c93d2df832ed86e855cfc006f0ad726f`、最終保存評価の
復旧コードは `6693733c8a37a966cb360cd57afc0508a1cc9230` です。後者は前者を
履歴に含みます。過去文書の `sample2`、日付付きパス、固定版の記述は当時の来歴です。
