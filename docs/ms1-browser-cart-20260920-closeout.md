# PR #11 follow-up: classification and cleanup acceptance

**指定された2点の修正、通常評価から集計・終了状態までの回帰確認、既存結果への影響確認を完了した。削除評価の工程は完了と判定する。** 対象は `39662f15496738621340f3f65566af5143041e39`。着手時点でPR #11はマージ済みだったため、その内容と同一のmainに対する追加変更として扱う。新規モデル実行は行っていない。

## 変更と結果の区別

コントロール欠落・無効化は、正常に起動したブラウザーで開始状態を確認したうえで、`observe-unavailable`としてDOM・PNG・理由を保存し、生成物の不合格にする。クリックを実行していない証拠には`click-remove`や`clickedAt`を付けない。欠落の自動判定は、認識できる単純なカート行に削除コントロールも代替候補もない場合に限定した。別名の動作するボタンなど、セレクターで判断できない実装は`unsupported`の未完了となる。

2回追加して数量が3になるケースは、空カート・追加回数・表示を証拠にC-013/R-012の違反を残す。C-015の削除自体は`not_run_precondition`となる。既存HTTP不合格も保持する。未完了時の品質点はnull、確認済みの品質不合格はfailとして残し、`researchStatus`・`browserCartCases`・`evaluatorFaults`を別に扱う。ブラウザー起動障害、証拠欠測・改変、対象不一致を合格に戻す経路はない。

回収失敗は品質を変更せず、`operation_status=cleanup_failed`としてscore/rescore CLIを非成功終了させ、保存済み訂正バッチも停止する。`cleanup-browser`は所有マニフェスト・ラベル・実IDを確認し、残存資源の削除と不在確認だけを行う。処理中の排他とDocker呼び出しは既存処理を再利用した。回収に失敗したWindowsのbind mountがディレクトリーの改名を阻害する場合も、評価結果・索引・回収先を同じ場所に保持する。

## 実行した回帰

実HTTP遷移、実Chromium、通常の`score` CLI → HTTP評価 → ブラウザー収集 → 内側合成 → 保存・集計を通した。[実行スクリプト](../research/verify_browser_failures.py)は保存済み生成物の**使い捨てコピー**だけを加工して合成欠陥を作る。モデル実行・原生成物の変更・画面遷移のHTML置換は行わない。

| ケース | 集計の品質 | 評価範囲／運用 | score CLI | 証拠 |
|---|---|---|---:|---|
| 正常（explore-003） | pass / 100 | 完了 | 0 | [01](../artifacts/corrections/browser-cart-20260920-v1/r3/01/verification.json) |
| クリック可能だが無反応 | fail / 93.1 | 両操作を観測 | 0 | [02](../artifacts/corrections/browser-cart-20260920-v1/r3/02/verification.json) |
| コントロール欠落 | fail / 93.1 | 両ケース操作不能を観測 | 0 | [03](../artifacts/corrections/browser-cart-20260920-v1/r3/03/verification.json) |
| コントロール無効化 | fail / 93.1 | 両ケース操作不能を観測 | 0 | [04](../artifacts/corrections/browser-cart-20260920-v1/r3/04/verification.json) |
| 2回追加後の開始数量不正 | fail_critical / null | C-015未実施、C-016観測 | 1 | [05](../artifacts/corrections/browser-cart-20260920-v1/r3/05/verification.json) |
| 別名の削除ボタン（同じ処理へ接続） | null / null | unsupported、未完了 | 1 | [06](../artifacts/corrections/browser-cart-20260920-v1/r3/06/verification.json) |
| ブラウザー起動障害 | null / null | evaluator_fault | 1 | [07](../artifacts/corrections/browser-cart-20260920-v1/r3/07/verification.json) |
| PNG証拠欠測 | null / null | evaluator_fault | 1 | [08](../artifacts/corrections/browser-cart-20260920-v1/r3/08/verification.json) |
| HTTP不合格の後にブラウザー起動障害 | fail / null | 不合格保持＋evaluator_fault | 1 | [09](../artifacts/corrections/browser-cart-20260920-v1/r3/09/verification.json) |
| コンテナー削除失敗を注入 | pass / 100 | cleanup_failed | 1 | [10](../artifacts/corrections/browser-cart-20260920-v1/r3/10/verification.json) |
| ネットワーク削除失敗を注入 | pass / 100 | cleanup_failed | 1 | [11](../artifacts/corrections/browser-cart-20260920-v1/r3/11/verification.json) |
| 既知の合計表示不具合（preload-003） | fail / 93.1 | 従来判定を維持 | 0 | [12](../artifacts/corrections/browser-cart-20260920-v1/r3/12/verification.json) |
| 既知の無反応リンク（explained-004） | fail / 93.1 | 従来判定を維持 | 0 | [13](../artifacts/corrections/browser-cart-20260920-v1/r3/13/verification.json) |

最終回帰は**13/13ケースで期待する分類・終了状態と一致**した。「13生成物が品質合格」という意味ではない。回収失敗2ケースとも、回収だけのCLI再試行がexit 0となり、評価JSON・ブラウザー証拠・固定コピーのハッシュは不変だった。再試行の全Dockerコマンドを保存した。モデル・評価器・ブラウザーを起動する操作はない。最終確認で、このラベルのコンテナー・ネットワークの残存は0件だった。

内側71検査、outer 151テスト、research 41テストも成功した。改変証拠・別対象の拒否、HTTP不合格の保持、所有権不一致・別ID・外部endpoint・Docker障害・排他、訂正バッチの回収待ち停止、品質不合格と全試行トークンの集計を含む。[ログとハッシュの総括](../artifacts/corrections/browser-cart-20260920-v1/closure-final.json)を正本とする。

最終コード確認で、評価器障害と回収失敗が同時に起きる場合に元の障害コードを保持するガードと、受け入れバッチの復元後再採点も回収失敗で停止するガードを追加し、単体・バッチ制御テストを実施した。これらはr3の単一障害ケースの品質判定を変更しない。内側評価器とcollectorのバイト列はr3から不変である。追試を行っていないケースを新たに実査したとは数えていない。

途中の試行は削除していない。`regression-v1`は6ケース確認後、コピー先のWindows長パス制約で中断した。`r2`は9ケース確認後、コンテナー削除失敗の注入でWindowsの改名失敗を検出した。この失敗を修正し、未改変の品質・観測を保持したまま残存資源だけを回収した。最終`r3`は新しい保存先で13ケースを確認した。途中結果を最終全件成功へ混ぜていない。

## 既存24生成物への影響

[読取専用監査](../research/audit_browser_corpus.py)でuniform-v3の48操作のreceipt・開始DOM・clickイベント・回収記録を照合し、今回の操作不能・開始状態不成立・回収失敗の該当は**0件**だった。保存評価から独立に数えて**9合格・15不合格**と一致した。全24生成物のブラウザー一括再実行も、評価結果の再訂正も不要だった。

[着手時監査](../artifacts/corrections/browser-cart-20260920-v1/impact-audit.json)と[終了時監査](../artifacts/corrections/browser-cart-20260920-v1/impact-final.json)のuniform-v3全ファイルハッシュは一致する。固定生成物822ファイル、保存済み評価・R-029訂正、条件・manifest・snapshot・トークン正規化記録の照合も一致した。代表選定を含む既存summaryも不変であり、トークン原本の再解析や再選定はしていない。

報告冒頭の従来不合格2件を基準評価と照合した結果、初回preload-001は**R-010**、初回preload-002は**R-016**だった。[前報](ms1-browser-cart-20260919-report.md)の「R-010が2件」を表記訂正した。点数・件数を推測で変更していない。

## 次の2条件

[入力仕様](ms1-catalog-return-two-condition-spec.md)に、初回リクエストへの投入時点、同一原本・抽出手順・ファイル・982バイトの確認情報、原文1〜360行／51,200本文バイト上限、同一再取得コマンドを具体化した。差分は大きな原文packetの併記だけである。品質合格率と全試行のprovider input＋outputを併記し、少ないトークンで失敗した実行を効率改善にしない。

オフラインの[入力例検証](../artifacts/corrections/browser-cart-20260920-v1/catalog-contract-example/offline-verification.json)では、抽出の決定性、全246件の順序・各値、共通部分のバイト一致、差分が追加packetだけであること、再取得出力の一致を確認した。実験側へのmount・初期入力接続、標本数／順序／予算／統計判断の固定、新規モデル実行は未実施である。これは今回依頼された仕様具体化と区別する。

`human_review: not_run`を維持する。全生成物の合格や、人間による追加操作を削除評価工程の完了条件には加えない。
