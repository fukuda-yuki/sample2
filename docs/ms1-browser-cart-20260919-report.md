# 削除操作の通常評価接続・保存済み24生成物への統一適用

2026-09-20追記: 操作不能の分類と資源回収失敗の伝播に関する追加修正・受け入れは[後続報告](ms1-browser-cart-20260920-closeout.md)を参照する。本報告のuniform-v3の研究結果は保持する。

**削除操作に関する評価の見逃し解消と、保存済み生成物への統一適用は完了。**
同じ最終手順で24生成物・48クリックを確認し、評価未完了は0件。
品質判定は採取時の22合格・2不合格から、**9合格・15不合格**になった。
13生成物でR-014・R-015が合格から不合格へ変わった。両削除ケース自体は11生成物で合格、13生成物で不合格。
従来から不合格の2生成物（初回preload-001はR-010、初回preload-002はR-016）は、削除に合格しても全体の不合格を維持する。
2026-09-20に保存済みのR-029訂正後評価と照合し、要件IDの表記を訂正した。集計値は変更していない。
別に、初回18枠の起動前障害1枠を「生成物なし」で保持する。ブラウザー不合格には数えない。

本報告はCodexエージェントによる自動実査であり、`human_review: not_run`。
固定生成物の修正・再生成、新しい研究用モデル実行、ZIP全体の再作成、トークン原本の全件再監査は行っていない。
以前の3生成物×8シナリオ実査の「24件」と、本報告の「24生成物」は異なる分母である。

## 条件別の変更前後

分母は各集団の**生成物が存在する件数**。初回18枠全体では合格5/18、生成物に限ると5/17。
起動前障害を分母から消した表ではなく、枠数・生成物数・生成物なしを併記した。
既存6件、初回18枠、補充を混ぜた条件効果の推定は行わない。

| 集団 | 条件 | 枠数 / 生成物 | 採取時HTTP合格 | R-029訂正後 | ブラウザー訂正後の品質合格 | 生成物なし |
|---|---|---:|---:|---:|---:|---:|
| 既存6件 | explore | 2 / 2 | 2/2 | 2/2 | 1/2 (50.0%) | 0 |
| 既存6件 | preload | 2 / 2 | 2/2 | 2/2 | 1/2 (50.0%) | 0 |
| 既存6件 | explained | 2 / 2 | 2/2 | 2/2 | 2/2 (100.0%) | 0 |
| 初回18枠 | explore | 6 / 6 | 6/6 | 6/6 | 1/6 (16.7%) | 0 |
| 初回18枠 | preload | 6 / 6 | 4/6 | 4/6 | 2/6 (33.3%) | 0 |
| 初回18枠 | explained | 6 / 5 | 5/5 | 5/5 | 2/5 (40.0%) | 1 |
| 補充 | explained | 1 / 1 | 1/1 | 1/1 | 0/1 (0.0%) | 0 |

これは同じ削除評価を適用した記述集計であり、他の全要件を新たにブラウザーで観測した合格率ではない。
単純なHTTP-onlyの集計は今後の研究品質合格に使用しない。

## Run別の変更前後

Run名の共通接頭辞は`MS1-001-`。同名Runは集団を分け、JSONでは完全なinstance IDで束縛する。
「R-029後」を今回のHTTP基準にし、C-015/C-016以外の判定は継承した。

| 集団 | Run | 採取時 点 / 判定 | R-029後 点 / 判定 | 今回 点 / 判定 | C-015 / C-016 | 今回変わった要件 | 所在 |
|---|---|---|---|---|---|---|---|
| 既存6件 | explore-001 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/d4a6a43a411b427c94a03a6381ec8d8d/result/evaluation.json) |
| 既存6件 | preload-001 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/7fa942711f5c41e2a1b33ecfb6a9e20c/result/evaluation.json) |
| 既存6件 | explained-001 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/fec3c60e7a3945199aeb039acf8d7ced/result/evaluation.json) |
| 既存6件 | explore-002 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/15d48941fdf84554bdb099559d09b1c3/result/evaluation.json) |
| 既存6件 | preload-002 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/937fa66d44e544e393bfdb4d514db1d6/result/evaluation.json) |
| 既存6件 | explained-002 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/a7c33b6f65984441aa13fa1b1e7fc43b/result/evaluation.json) |
| 初回18枠 | explore-001 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/b84e23569d5e4248bdd0feb8199ef332/result/evaluation.json) |
| 初回18枠 | preload-001 | 93.10 / fail | 96.55 / fail | 96.55 / fail | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/758bb8cbfdf04d3a98233f8e97f0fea6/result/evaluation.json) |
| 初回18枠 | explained-001 | 0.00 / fail_critical | 0.00 / fail_critical | — | 対象外 | 生成物なし | 起動前障害を保持 |
| 初回18枠 | explained-002 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/f909c79b253b4dff995893fb61b40133/result/evaluation.json) |
| 初回18枠 | preload-002 | 96.55 / fail | 96.55 / fail | 96.55 / fail | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/547a6a7e3d30459b8e8ff7e4967a876f/result/evaluation.json) |
| 初回18枠 | explore-002 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/48a9e580da8742a1920a8764b7c7e9db/result/evaluation.json) |
| 初回18枠 | explore-003 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/94fe01fe7837446b9ae44a067b2a3512/result/evaluation.json) |
| 初回18枠 | explained-003 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/1f828ebd2c25483d806f9054b4ac0b74/result/evaluation.json) |
| 初回18枠 | preload-003 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/ba8c9937d5124871929533ea457aaa5b/result/evaluation.json) |
| 初回18枠 | explained-004 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/d5cc289e22bc4a3b8ace55ad6b554132/result/evaluation.json) |
| 初回18枠 | explore-004 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/77f61cd09dcf4d118c4316cbda39a4ac/result/evaluation.json) |
| 初回18枠 | preload-004 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/9398d6058ef3461993046065c8c3ce07/result/evaluation.json) |
| 初回18枠 | preload-005 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/2a319962abc14e038bf7bcb788242d82/result/evaluation.json) |
| 初回18枠 | explained-005 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/ae580ba78fe84f069e48c28db4c673bb/result/evaluation.json) |
| 初回18枠 | explore-005 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/b0a07817a6fe43b8abbd702ac124b49c/result/evaluation.json) |
| 初回18枠 | preload-006 | 100.00 / pass | 100.00 / pass | 100.00 / pass | pass / pass | なし | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/d285756c977847d38f2c9304687c1566/result/evaluation.json) |
| 初回18枠 | explore-006 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/fe7a9a0c70f74e318b9bb58a53f1f56f/result/evaluation.json) |
| 初回18枠 | explained-006 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/30ece9cdd86540e789f1c41b76fbe9ee/result/evaluation.json) |
| 補充 | explained-007 | 100.00 / pass | 100.00 / pass | 93.10 / fail | fail / fail | R-014, R-015 | [証拠](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/8dbd99428a1c4318b67f9e5db6187f55/result/evaluation.json) |

初回explained-001の`0 / fail_critical`は採取時の保存値をそのまま表示したもの。
今回の生成物品質として採用せず、技術障害・モデル未実行・生成物なしの別状態で保持した。
初回preload-001のR-029は訂正済みのpassを維持し、93.10→96.55の訂正を取り消していない。
explore-003／preload-003／explained-004の代表選定も固定したままであり、別の合格代表へ選び直していない。

## 通常経路と実施方法

通常の`outer.harness.evaluate.score_run`はHTTP/static評価を`http-only/`へ保存した後、
共通の`browser_cart.complete_evaluation`で実ブラウザーを起動し、innerの`BrowserCartReview`で判定する。
保存済み24件にも同じ採取・合成関数を使った。最終バッチは`uniform-v3`。
採取時評価と既存R-029訂正を入力とし、新しい結果を別ディレクトリへ保存した。
その他27要件は保存済み結果を継承し、24件の8シナリオ全再実査へは広げていない。

各ケースは独立したブラウザーコンテキストを作り、空カートを確認して、公開AddToCart経路で商品1を準備する。
C-015は1明細・数量2・17.98、C-016は別セッションで1明細・数量1・8.99を確認してから、
画面の削除リンクまたはボタンを実クリックする。C-015の失敗状態をC-016の前提には使わない。
同じ画面の表示DOMを200 ms間隔で読み、期待状態が500 ms継続し通信待ちがなくなれば確定する。
更新待機上限は10秒、クリック可能状態の待機は5秒、通常遷移の待機は15秒。
上限後に数量・合計が正しくなければ生成物の不合格となる。
操作後の手動リロード、別GETによる表示の置換、補助削除POST、JavaScript修復は行っていない。

アプリ自身の遷移を観測するため、同じオリジンでJSON本文ページへ遷移するexplained-003も
画面更新の不合格として扱う。異なるRun・成果物・仕様・tab/originや、欠損・改変された証拠は評価器障害。
HTTP合格だけでは採用せず、集計でもreceiptと参照DOM/PNGのハッシュを再照合する。
未観測時は研究用quality/verdictをnullとし、元の申告値を別欄で保持する。
異なるcollector・ブラウザー条件は通常の比較集計でも別の識別情報を持つ。

## 実動対照と回帰検証

| 確認 | 最終結果 | 証拠 |
|---|---|---|
| 通常のscore_run→実ブラウザー→aggregate：explore-003 | 100 / pass | [通常経路対照](../work/bcn3/summary.json) |
| 同：preload-003の古い合計 | 93.10 / fail、C-015/C-016ともfail | 同上 |
| 同：explained-004の無反応リンク | 93.10 / fail、C-015/C-016ともfail | 同上 |
| 同：CDN jQueryを利用するpreload-005 | 100 / pass。生成物未修正 | 同上 |
| 通常経路で存在しないブラウザーを指定 | evaluator_fault、adopted=false、quality/verdict=null | [起動障害](../work/bcf1/summary.json) |
| 保存した実ブラウザー証拠のPNG欠測・instance不一致 | 両方error / quality=null / exit 2。HTTP合格へ戻らない | [証拠障害](../artifacts/corrections/browser-cart-20260919-v1/evidence-fault-controls/summary.json) |
| 通常集計で成功証拠のコピーからPNGを外す | 100/pass→evaluation_incomplete、quality/verdict=null | [集計対照](../artifacts/corrections/browser-cart-20260919-v1/aggregate-fault-control/summary.json) |
| 合成DOM・判定合成の回帰 | 64件合格、保存イメージでビルド警告0・エラー0 | [ビルドログ](../artifacts/corrections/browser-cart-20260919-v1/build-v2/stdout.log) |
| outerの回帰 | 137件合格 | [ログ](../artifacts/corrections/browser-cart-20260919-v1/outer-tests-release.log) |
| researchの回帰 | 39件合格 | [ログ](../artifacts/corrections/browser-cart-20260919-v1/research-tests-release-v3.log) |

通常経路対照は保存生成物の使い捨て検証コピーに対して行った。研究用の新しいRunやモデル実行ではない。
合成DOMテストを実ブラウザー操作の代わりにはしていない。代表3件の実PNGもエージェントが確認した。

## 識別情報と保存範囲

| 項目 | 値 |
|---|---|
| 公開仕様 / evaluation contract | 1.2.0、29要件・30チェック、不変 |
| 公開仕様SHA-256 | `fbec6c9e370aa7690460d854c167e486ca7b88eb8f5f0305805ca4fe4a98b2e4` |
| 評価器実装版 / DLL SHA-256 | 1.1.0 / `eb08394284434133a5d0c7c296b97eb38d11ddd2c45549d0d5bef9ccc3c5b50a` |
| collector版 / SHA-256 | 1.0.1 / `e02bd037941cc830bad033d19d8aa3005e05cf5d6a72198fd2420012d37ea048` |
| Chromium / 実行ファイルSHA-256 | 149.0.7827.55 / `b798f9e53a98d29eb7f36f8c409f905d3184780a04d2bcb56989067194784bd1` |
| Playwright / Node | 1.62.1 / v24.15.0 |
| 表示条件 | headless、1280×900、en-US、UTC |
| アプリ・評価器環境 | 保存Docker image `sha256:a0bd46f3cebfc2502fe930cb50827379180b7c3f4f297d5a9e2f7201f38d5c3d`、SDK 8.0.425 |
| 通信条件 | ブラウザーの通常読み込み。外部スクリプトのURL・HTTP status・本文ハッシュも保存。外部scriptの観測障害は未完了 |

各Runのreceiptに実行条件・時刻・tab ID・前後DOM/PNG・観測完了条件を保存した。
各`browser-intent.json`は起動引数・元のHTTP評価/resultsハッシュ・実行publish全ファイルのハッシュを保持する。
起動物は採取時archiveのpackage.jsonと照合し、固定成果物と同じ対象であることを検査した。
各`evaluator-manifest.json`は合成に使った評価器・仕様・成果物・継承元を記録する。
固定生成物822ファイル、manifest/snapshot/condition、元評価、R-029基準、normalized usageの保存照合がすべて一致した。
トークン値は以前の25枠の表と完全一致し、欠測は欠測のまま。使用量原本の再解析・全件再監査はしていない。
原本・固定物は読み取り専用入力で扱い、既存のarchive/referenceと保存済み評価を変更していない。

集計正本は[uniform-v3/summary.json](../artifacts/corrections/browser-cart-20260919-v1/uniform-v3/summary.json)。
各行にはcohort、完全なRun/instance ID、採取時・R-029後・今回の点と判定、変わった要件、証拠ディレクトリがある。
原本との最終照合・条件一致・対象数・未完了0の確認は[closure-v3.json](../artifacts/corrections/browser-cart-20260919-v1/closure-v3.json)。
保存結果の再読込時も元生成物・公開仕様のハッシュで照合し、結果自身の申告値に依存しない。
Cookieを含みうるDOM/trace・DB・生ログはGit除外のローカル領域に保持し、公開PRへ追加しない。

## 評価環境の訂正履歴

最初の接続ではDocker internal networkが公開portを作らず、次に未設置のChromium既定パスを参照した。
いずれも生成物の不合格にせず、`controls`/`controls-v2`に評価器障害として保持した。
長いWindows出力パスで検証コピーの作成にも失敗したため、通常経路の検証作業先は短い`work/bcn*`へ変更した。
JSONページ遷移を対象不一致として扱った初版も保持し、同一オリジンの観測結果として判定を修正した。

さらに最終照合で、初期collectorの全off-origin遮断がpreload-005のCDN jQueryを止める誤不合格を発見した。
これは公開契約にない制約なので撤去した。`uniform-v1/v2`と暫定8合格・16不合格は保持するが最終集計には使わない。
最終collector 1.0.1で24生成物の削除2ケースをすべて採り直し、同じ条件の`uniform-v3`へ揃えた。
preload-005だけがこの環境訂正で合格へ戻り、今回指定された2欠陥は引き続き不合格となった。
生成物の修理で合格にしたものはない。外部リソースの将来の不変性までは保証せず、実行時の版・hashを観測記録とする。

## 再現と次段階

既存NodeモジュールとChromiumのパスを環境変数`NODE_PATH`、`SAMPLE2_BROWSER_EXECUTABLE`で指定する。
新しい出力ディレクトリを使って、モデルを呼ばず再現できる。取得済みデータを上書きするオプションは設けていない。

```powershell
python -m research.browser_rejudge `
  --inventory artifacts/corrections/ms1-20260919-v1/baseline/inventory.json `
  --prior-corrections artifacts/corrections/ms1-20260919-v1/rejudgement-v1 `
  --prior-quality artifacts/corrections/ms1-20260919-v1/summary-v1/quality-impact.json `
  --bundle artifacts/corrections/browser-cart-20260919-v1/build-v2/bundle `
  --out artifacts/corrections/browser-cart-new-verification
```

判定コードのみの訂正には`--observations <採取済みバッチ>`も使えるが、採取条件を変更する場合は新しい実観測を行う。
今回の最終版では、CDN読み込み条件も揃えるため全24件を同じcollectorで観測した。

削除評価に関する未完了はない。2条件のカタログ返却範囲比較を中止する理由にはせず、次は2条件の仕様具体化と実験条件の固定へ進める。
新規モデル実行は開始していない。生成物全件の合格、人の実施、他のUIシナリオ全再確認を本工程の完了条件には追加しない。

[PR #10](https://github.com/fukuda-yuki/sample2/pull/10)のTesting欄も訂正し、当時実施した56件の回帰・3生成物の実査・6訂正評価と、
PR作成時には再実行していない事実を分けた。過去のPRに今回の24生成物検証を遡って実施済みとは記載していない。
変更前後とGitHub読み戻しは[pr10-body](../artifacts/corrections/browser-cart-20260919-v1/pr10-body/)へ保存した。
