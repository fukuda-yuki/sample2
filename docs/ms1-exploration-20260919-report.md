# MS1-001：既存6 Runの行動分析と探索バッチの中断報告

**既存6 Runの解析は完了。新規18 Runの採取は未完了である。**
初回18枠のうち2 Runが実装・計測を完了し、3枠目はDockerのネットワーク作成に失敗した。
合意済みの隔離障害時の停止規則でバッチを終了した。残る15枠は未実行、補充は0件である。
品質不合格や障害を取り除いて成功例だけを比較していない。

新規の2実行でも、大きなデータ原文のツール出力が多数の後続入力に残る現象を確認した。
一方、新規preloadはトークンが少ないが品質不合格で、ビルド修正が表示不備を残した。
**情報保持を制御するH2を優先候補とするが、次の主仮説の確定は保留する。**
新規explainedの行動、条件内の反復、品質判定の不一致を解消する証拠が不足している。

## 1. 何を固定し、どこまで実施したか

採取前の固定版はコミット `5fa49775c24a5462238f2ca6b05aab0f2001e4c1`。
[固定プロトコル](ms1-exploration-20260919-protocol.md)と
[機械可読計画](../research/protocols/ms1-001-exploration-20260919.json)に、
仮説、分類規則、停止・補充規則、ソース／環境／コードのハッシュを保存した。
通常の既存CLI `run` 経路を使い、モデル・予算・評価器・要求・入力内容を変更していない。

- MS1-001、公開29要件、評価1.2.0、deepseek-v4.1-flash、OpenCode 1.17.11。
- 各Run 1800秒、provider 600秒、同時実行1。新しい作業領域・状態領域・セッションを使用。
- 乱数seed：`2276221400835857104`。6ブロック順は下表のとおり、採取前に確定。
- 計画原本SHA-256：`7e4df4a319557b161368fe4fb1d68f5456229d2e6f5619e5ce37bbb58e0d318a`。
- 既存データは `runs/acceptance-64ad09cd85ca` の直下6件だけ。
  新規は `runs/exploration-20260919-ms1`。同名Runでも別のrun_instance_idであり、混ぜない。

| ブロック | 1番目 | 2番目 | 3番目 | 実施状態 |
|---|---|---|---|---|
| 1 | explore | preload | explained | 完了、完了、環境障害 |
| 2 | explained | preload | explore | 全枠未実行 |
| 3 | explore | explained | preload | 全枠未実行 |
| 4 | explained | explore | preload | 全枠未実行 |
| 5 | preload | explained | explore | 全枠未実行 |
| 6 | preload | explore | explained | 全枠未実行 |

実行は2026-09-19 00:53:44〜01:12:22 JST。各モデル実行の開始・終了・評価・保存完了時刻は
[18枠の実行台帳](../artifacts/exploration/20260919/ledger-final-v2/execution-ledger.csv)にある。
時刻原本はUTC。補充による置換、順序変更、モデル切替、有意差を理由にした追加はない。

## 2. 新規バッチの全試行

| 枠／Run | 呼び出し | input | output | input＋output | 評価1.2.0 | 状態 |
|---|---:|---:|---:|---:|---|---|
| 1 explore-001 | 60 | 4,286,645 | 50,720 | 4,337,365 | 100、29/29合格 | 実装完了・完全計測 |
| 2 preload-001 | 45 | 3,472,829 | 41,052 | 3,513,881 | 93.1、27/29合格 | 実装完了・品質不合格・完全計測 |
| 3 explained-001 | 観測0 | null | null | null | 0、1不合格・28 blocked | モデル起動前の環境障害 |
| 4〜18 | 未実行 | null | null | null | 未採点 | 未実行15枠 |

explainedの0点は空の成果物に対する評価結果であり、説明投入で生成した実装の品質ではない。
観測usageがないため、部分和もnullとする。低コスト成功や「0トークン」と扱わない。
explore/preloadは各1観測なので平均・中央値は個別値と同じ、標本SDはnull。
explainedは既知のRun総量0件で、平均・中央値・SDもnullである。
**全条件のusageが揃ったブロックは0組**。事前に定めた完全ブロックの条件差はすべてnull。
成功Runだけの補助集計には新規exploreの1件だけが入る。

停止原本：新規explainedの `evidence/runtime-error.json` に
`docker network create` の失敗と `all predefined address pools have been fully subnetted` が残る。
当時32ネットワークが存在し、完了した新規2 Runの専用ネットワークも残っていた。
現行 `outer/harness/runtime.py` はコンテナーを停止するが、専用ネットワークを回収しない。
この蓄積がアドレス枠を使い切った状態と対応する。
[調査時の状態](../artifacts/exploration/20260919/network-diagnosis.json)を保存した。
他タスクのネットワーク、停止コンテナー、原本は削除していない。

最小の次の環境対処は、保存完了・所有者・停止を確認したRunの専用ネットワークを
回収する運用／処理を用意し、モデルを呼ばずに隔離・回収を校正することである。
現在のバッチを条件変更後に続行せず、新しいバッチとして採取計画を定める必要がある。

## 3. 既存6 Run：322呼び出しの再集計

gatewayの保存SSEをトークンの正本とし、request ID・tool call ID・run_instance_idで
送信入力、usage、OpenCodeの行動を対応付けた。322呼び出しと532ツール行動に結合漏れ・重複・
usage不一致はない。診断試行と復元コピーは分母に入れていない。全6件の評価は100点である。
inputにはcache read、outputにはreasoningが含まれるため再加算しない。
この記録で内訳の定義が異なるOpenCode側の数値とは混用していない。
主指標は料金ではなくprovider報告トークン数である。
既存説明文をそのまま使い、今回の投入情報を作る追加LLM呼び出しはない。
既存説明文の過去の作成トークンは不明であり、準備まで含む方法全体の効率は未評価である。

| Run | calls | input | output | 合計 | 平均input/call |
|---|---:|---:|---:|---:|---:|
| explore-001 | 62 | 4,048,388 | 57,180 | 4,105,568 | 65,296.6 |
| explore-002 | 52 | 3,160,186 | 43,466 | 3,203,652 | 60,772.8 |
| preload-001 | 38 | 2,526,844 | 46,186 | 2,573,030 | 66,495.9 |
| preload-002 | 54 | 4,096,295 | 52,945 | 4,149,240 | 75,857.3 |
| explained-001 | 45 | 3,342,070 | 40,441 | 3,382,511 | 74,268.2 |
| explained-002 | 71 | 4,380,332 | 38,941 | 4,419,273 | 61,694.8 |

| 条件（既存のみ、各2件） | 平均＝中央値 | 標本SD | 最小〜最大 |
|---|---:|---:|---:|
| explore | 3,654,610 | 637,751 | 3,203,652〜4,105,568 |
| preload | 3,361,135 | 1,114,549 | 2,573,030〜4,149,240 |
| explained | 3,900,892 | 733,101 | 3,382,511〜4,419,273 |

Q1/Q3、input/output別分布、個別値、補助集計は
[集計表](../artifacts/exploration/20260919/final-display-v2/summary.json)と
[実行済み再現ノート](../artifacts/exploration/20260919/final-notebook-v3/analysis.html)で確認できる。
ばらつきは観測値の記述であり、効果の信頼区間ではない。

### 入力増加と保持

初回inputはexplore 8,028、preload 15,578、explained 8,167 tokensで、同条件の既存2件で一致した。
全実行8 Run・427呼び出しで初期promptの保持を確認した。preloadの20ブロック、
explainedの説明1ブロックも、それぞれ実行されたすべてのリクエストに残る。
system messageは9,733文字、ツール定義は15,661文字で固定。
user messageの文字量はexplore 3,967、preload 34,391、explained 4,715である。
この文字量は正規化JSONの長さであり、provider tokenの部分内訳ではない。

後続入力では生成コードを含むassistant履歴と、ソース／コマンド出力のtool履歴が増えた。
単一文章の因果的な寄与は算出していない。
大きな文脈圧縮は確認できず、既存explained-002のcall 4で2メッセージのhash variantが
消えた例は、部分的な履歴差として記録した。初期promptは残り、全体の圧縮とは断定しない。

![既存6件の入力長](../artifacts/exploration/20260919/final-display-v2/existing6-input.png)

![既存6件の累計](../artifacts/exploration/20260919/final-display-v2/existing6-cumulative.png)

### 各Runの行動との対応

| Run（既存） | 入力増加・呼び出し反復の観測 | 根拠 |
|---|---|---|
| explore-001 | 初期のSampleData取得後に最大+14,707。53,025文字の出力が54呼び出し先まで保持。115行動／62呼び出し、複数ツールをまとめた要求21件 | call 8〜9、agent.jsonl:48 |
| explore-002 | SampleData取得後に最大+18,896。53,025文字が49回保持。99行動／52呼び出し、複数ツール要求14件 | call 3〜4、agent.jsonl:13 |
| preload-001 | 初期入力は大きいが71行動／38呼び出し。SampleDataが36回保持。未変更範囲再取得は確定0件。最初のbuild分類call 12はrestoreを含む | call 2〜3、agent.jsonl:7 |
| preload-002 | 85行動／54呼び出し。未変更4範囲を再取得。call 33の51,295文字の起動ログが21回保持され、次入力は+18,667 | agent.jsonl:134、reads.csv |
| explained-001 | 2つのSampleDataを同じ要求で読み、それぞれ53,025／53,013文字を40回保持。次入力+29,059。92行動／45呼び出し。自作テストのGET/POST誤りで確認が反復 | call 5〜6、agent.jsonl:26〜27、call 30/37〜39 |
| explained-002 | 70行動／71呼び出しで複数ツール要求0件。他のexplainedより平均入力は小さいが呼び出し数が多い。シェル取得51,112文字が67回保持 | call 3、agent.jsonl:12、全call表 |

根拠の `agent.jsonl` は各Runの `evidence/agent.jsonl`、call番号は時刻順に採番したgateway要求。
正確なrequest ID・tool call ID・原本相対パスは
[既存呼び出し表](../artifacts/exploration/20260919/pilot-v1/calls.csv)、
[行動表](../artifacts/exploration/20260919/pilot-v1/actions.csv)、
[範囲別再取得表](../artifacts/exploration/20260919/pilot-v1/reads.csv)にある。

preload-002の入力がpreload-001より多いのは、54/38という呼び出し数の差と、
75,857/66,496という平均入力長の差の両方に対応する。
ただし差を事前投入だけに帰属できず、ログ保持・生成コード・確認行動も異なる。

再取得は浪費と判定しない。2つの同名SampleData原本は143行位置で異なり、先頭アルバムと
登録順も異なる。必要なID制約を守るにはこの違いが重要で、単純な重複除去は不適切である。
シェルの加工・変数・未同定範囲は判定不能として保持した。既存の未分類行動7件は
[個別注記](../research/pilot-case-review.json)で意味を補い、固定ラベルを上書きしていない。
`FAILED 0`を含む文字列も検出されるため、test_failure_text件数をテスト失敗数とは呼ばない。

## 4. 新規2実行で繰り返されたことと品質

新規exploreはSampleDataの53,025文字を55回保持し、次入力が+16,386だった。
新規preloadはSampleData 53,013文字を42回、SQLを抽出表示した51,244文字を38回保持し、
SQL出力の次入力は+18,700だった。大きな出力の保持は新しい2実行でも観測された。
シェルで「必要そうな行」を抽出しても出力量が大きい例である。

| 新規Run | 取得行動 | 修正ラベル | 行動数／calls | 複数ツール要求 |
|---|---:|---:|---:|---:|
| explore-001 | 34 | 10 | 112／60 | 13 |
| preload-001 | 20 | 2 | 71／45 | 15 |

ラベルは複合・重複を許す。1要求に複数目的があるため、usageを行動へ按分していない。
修正は失敗の証明ではなく、回数差も条件の効果を確定しない。
新規preloadは初期投入済みShoppingCart.csの未変更範囲を1回再取得した。
ほかに部分重複1件があり、残る不明な範囲も表に残した。

品質上の具体例は以下のとおり。

- preload call 32でViewComponentの `Content` 引数数によるCS1501が2件。
  call 33でHTMLのcontent type引数を削除し、call 34でビルド成功。
  最終画面ではHTMLが文字列として表示され、Cartとジャンルメニューのリンクが壊れていた。
  保存評価のR-010/C-011不合格と対応する。エージェント自身の文字列検査はこれを合格とした。
- preloadのR-029/C-030は `MvcMusicStore.sln` の名前だけを根拠とする。
  参照先は新しいSdk.Web/net8.0である。`LegacyScan` のmodern project除外がcsprojに限定され、
  slnの参照先を見ないため、偽不合格を疑う具体的な評価上の欠陥がある。
  元の93.1点を変更したり、仮の補正点を主集計へ入れたりしていない。
- explainedの未実行は品質比較に使える失敗実装ではない。

[新規事例台帳](../research/new-case-review.json)に原本のtool call IDを残した。
人の確認用には[起動・シナリオ対応表](ms1-exploration-20260919-human-review.md)を用意した。
エージェントによるホーム画面確認は実施したが、人の受入確認は未実施である。

## 5. 次の研究判断

[仮説台帳と確認実験の設計案](ms1-exploration-20260919-hypotheses.md)で、
H1（事前投入と取得）、H2（大出力保持）、H3（行動のまとめ方・反復）の支持例・反例・未確認を整理した。
現時点の優先候補はH2のうち**大量のカタログ原文をモデル文脈へ渡す範囲の制御**である。
原文を同じ場所に保持し、同じ機械処理を行ったうえで、全文併記と短い共通サマリーを比較する案を記した。
実装や追加計測はしていない。

これは主仮説確定や有効性の確認ではない。新規explainedの観測がなく、各条件の反復も不足し、
評価の偽不合格を解消していない。確認実験の反復数はまだ決められない。
環境回収の校正、品質の不一致の解決、探索の不足証拠を集める新バッチの判断を先に行う。
比較条件を変えながらこのバッチへ追加し続けることはしない。

## 6. 再現性、検証、納品

研究用の解析・集計・可視化・台帳・再現ノート・確認用起動スクリプトを追加した。
検証機本体、評価器、要求、固定イメージは変更していない。

- **原本照合：** 既存322＋新規105＝427呼び出し、532＋183＝715行動。
  実行された8 RunのID結合・usageに不一致なし。
- **欠測：** 起動前失敗の1 Runにはnative記録、started/terminal原本、セッションがない。
  解析監査の4件の欠測指摘を残し、成功扱いで消していない。
- **独立検算：** 別実装でSSE usageと保存ハッシュ3,463件を再確認し、不一致0件。
  元の既存6 Runの2,440件も再確認した。
- **採取後の修正：** v1.0.1で、usage未観測時の空部分和表示を0からnullへ修正。
  旧解析 `new-v1` も保存。既存6件の再解析で4表が元の結果と完全一致した。
  変更記録は [post-freeze-changes.md](../research/post-freeze-changes.md)。
- **検査：** 欠測／0、SSE内訳、複合行動、範囲再読込、成功例選別、中央値同値、順序・補充制限の14テストが通過。
  再現ノートは実行済み、HTMLと図表は表示確認済み。

主なファイル：

| 成果物 | 場所 |
|---|---|
| 呼び出し・行動・範囲・Run表 | `artifacts/exploration/20260919/pilot-v1`、`new-v1.0.1` |
| 実行・補充台帳（全18枠） | `artifacts/exploration/20260919/ledger-final-v2` |
| 条件別分布・ブロック差・図 | `artifacts/exploration/20260919/final-display-v2` |
| 実行済みipynb／HTML | `artifacts/exploration/20260919/final-notebook-v3` |
| 原本独立検算 | `artifacts/exploration/20260919/independent-check-v1.0.1.json` |
| 納品ファイルのチェックサム | `artifacts/exploration/20260919/delivery-manifest.json` |
| 新規Run保存パッケージ | `runs/exploration-20260919-ms1/_archive`、各Runの `archive-reference.json` |
| 人の確認材料 | 本報告と同じdocsのhuman-review文書、`artifacts/.../human-review` |
| 研究正本への修正案 | [反映案](ms1-exploration-research-protocol-proposal.md)（未反映） |

原本再抽出は次のとおり。出力は未使用のディレクトリ名にする。

```powershell
python -m research.analyze --runs-dir runs/acceptance-64ad09cd85ca --cohort existing6 --out artifacts/reproduce/existing
python -m research.analyze --runs-dir runs/exploration-20260919-ms1 --cohort primary18 --plan research/protocols/ms1-001-exploration-20260919.json --out artifacts/reproduce/new
python -m research.ledger --batch runs/exploration-20260919-ms1 --out artifacts/reproduce/ledger
python -m research.validate --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --out artifacts/reproduce/check.json
.\artifacts\exploration\analysis-env\Scripts\python.exe -m research.summarize --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --plan research/protocols/ms1-001-exploration-20260919.json --out artifacts/reproduce/display
.\artifacts\exploration\analysis-env\Scripts\python.exe -m research.notebook --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --summary artifacts/reproduce/display/summary.json --out artifacts/reproduce/notebook
```

Python環境の固定リストは `artifacts/exploration/20260919/analysis-environment.txt`。
解析だけなら標準ライブラリ、図とノートには保存した研究用環境を使う。
これらの再現コマンドはモデルや評価器を呼ばない。
本納品はローカル保存であり、GitHubへの公開や研究正本の更新は実施していない。

## 参考

最終成果物とトレースを併用する観点は
[Anthropicのエージェント評価解説](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)に対応する。
実行時期の偏りを抑える順序設計には[NISTのブロック化](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm)を参照した。
確認の反復数は必要精度・意味のある効果・資源に基づいて別途正当化する。
[Lakensの反復数設計](https://lakens.github.io/statistical_inferences/08-samplesizejustification.html)
