# MS1 PMO委任・主要シナリオ実査と移行判定

**判定: 実査は完了。主要シナリオ検証ゲートは未達。24件中22 pass、2 fail、0 blocked。**
preloadとexplainedのS2で削除操作に公開要件違反があり、元評価の100点・passと一致しなかった。
原因を生成物まで特定し、独立したブラウザー証拠を反映する評価器の最小修正、回帰確認、別保存の訂正評価を完了した。
固定生成物の不具合は修正していない。次の2条件の実装・動作確認へ「ゲート通過」として進行する判定は出さない。
本実験・確認実験の採取は開始していない。

| 項目 | 記録 |
|---|---|
| 実施者 | PMO委任のCodexエージェント |
| human_review | **not_run** |
| agent_scenario_review | **fail**（explore: pass、preload/explained: fail） |
| 停止理由 | 生成物2件のR-014/R-015違反。人間の未操作は停止理由ではない |
| 実施日 | 2026-09-19 JST。開始15:33:26、主要ブラウザー実査15:36頃〜15:55、削除の独立条件追試16:04〜16:05、訂正評価18:24〜18:26、終了照合18:28:53 |
| 成果の所在 | [今回専用の証拠領域](../artifacts/reviews/ms1-pmo-20260919-153326/) |

本報告は指定された3固定生成物の主要操作を確認したもので、品質の統計的非劣性やモダナイズ全体の品質保証を意味しない。

## 対象の識別と保存境界

対象リポジトリは`fukuda-yuki/sample2`。作業開始時のHEADは`53fd09bb01d4b9937f9c324c2c11f12ece992f32`、
ブランチは`main`、未コミット変更は0件だった（[開始記録](../artifacts/reviews/ms1-pmo-20260919-153326/start.json)）。
指定資料が旧HEADにないため、レビュー指定コミット`cecb653394d8e5d256f6e639d12c01da94edb81d`から
`codex/ms1-pmo-scenario-review-20260919`を作成して実施した。既存変更の破棄はない。
PR #9のレビュー対象はこのコミットであることをGitHubから確認した。

以下はすべて`runs/exploration-20260919-ms1`内の新規探索バッチに属する。既存6 Runの同名Runは使っていない。

| 条件 | Run | Run instance ID | 固定成果物SHA-256 |
|---|---|---|---|
| explore | MS1-001-explore-003 | `94fe01fe7837446b9ae44a067b2a3512` | `3450bd90c9083cfb16209f8d0ae4653402ebc403c39b5c15f4acfa50aab7e412` |
| preload | MS1-001-preload-003 | `ba8c9937d5124871929533ea457aaa5b` | `9e3ccd2efb3f2f4cf5cfa0fdb6d785d248b299688d541e118c116e06165e7477` |
| explained | MS1-001-explained-004 | `d5cc289e22bc4a3b8ace55ad6b554132` | `d042853872a2e00f0ac5be8066a577111eaba5ad1d722e47db8d0e2dcab8382a` |

公開要件は各Runの保存済み`evaluation-assets/requirements.json`（1.2.0、29要件・30チェック）。
SHA-256は共通で`fbec6c9e370aa7690460d854c167e486ca7b88eb8f5f0305805ca4fe4a98b2e4`。
元評価IDは順に`MS1-001-3450bd90c908-1.2.0-001`、`MS1-001-9e3ccd2efb3f-1.2.0-001`、
`MS1-001-d042853872a2-1.2.0-001`。いずれも採取時評価は29/29、100点、passだった。

既存の`artifacts/delivery/DELIVERY-ja.md`、v3の移設検証・再判定結果を確認し、合格済みの
`work/relocated-ms1-correction-v3/artifacts/exploration/20260919/human-review-resumed-v1/<condition>/application`
を起動した。全1,277呼び出しの再監査、ZIPの再作成はしていない。
原本・v3の`review-targets.json`、instance ID、snapshot、元評価publishの全ファイルとの一致を開始前に検査した。

| 条件 | 起動ファイル数 | 起動ツリーSHA-256 | エントリアセンブリ |
|---|---:|---|---|
| explore | 46 | `241edfb86338ab0512967c85ff9cfa90fefbbd9a48d827feae06a0cac0db637b` | MusicStore.Web.dll |
| preload | 45 | `4b7bae19e7333a5e8c990f9d21b08e4e6beebef4e3a5be000c9759d151b9d771` | MusicStore.dll |
| explained | 45 | `c991ca81f2651a224841566dcad448d9a144eea386944128861677e0d3d3682b` | MusicStore.dll |

ツリーハッシュは保存済み方式に合わせた相対パスと各ファイルハッシュの集約値。
詳細は[targets.json](../artifacts/reviews/ms1-pmo-20260919-153326/targets.json)と
[開始前照合](../artifacts/reviews/ms1-pmo-20260919-153326/integrity-before.json)にある。

## 実施方法

保存イメージ`sha256:a0bd46f3cebfc2502fe930cb50827379180b7c3f4f297d5a9e2f7201f38d5c3d`
（.NET SDK 8.0.425）を使用した。アプリは読み取り専用ルート・読み取り専用`/app`で起動し、
DBは今回新設した`artifacts/reviews/ms1-pmo-20260919-153326/<condition>/state/store.sqlite`へ保存した。
コンテナー名は`ms1-pmo-ms1-pmo-20260919-153326-<condition>`、ポートはexplore/preload/explainedの順で18401/18402/18403。
過去の`automation-state`・human-stateは使用していない。各`launch.json`に全起動引数を保存した。

ブラウザーAは既存のCodex内蔵ブラウザー、Bは既存Chromeの別Cookieコンテキスト。
条件ごとに今回固有の`.localhost`ホスト名を使用し、A/Bは同一オリジンへ接続した。
初期空状態、双方が異なる商品を保持する状態、変更・購入後の状態を実際のリンク・フォームで確認した。
S8の再起動後の購入は新しいホスト名の別セッションで実施した。
証拠は`*.png`、`*.dom.txt`、`*.browser.json`、`operations.jsonl`。ブラウザーJSONには現在のDOM、
表示テキスト、フォーム、当該オリジンのCookie、CDP通信イベント・レスポンス、コンソールを保存した。
Cookieを含む生証拠はローカルのGit除外領域に保管する。

DBは稼働中コンテナー内のSQLiteに`mode=ro`、`query_only=ON`、読み取りトランザクションで接続した。
WALを含む実DBを照合しており、稼働中DBファイルの不完全なコピーは判定に使っていない。
S5/S6は既存注文1と商品入りカートを用意してから別入力で実施した。
比較は件数だけでなく商品ID・数量・合計・注文ID集合・注文行全体。
[state-comparisons.json](../artifacts/reviews/ms1-pmo-20260919-153326/state-comparisons.json)に具体値を保存した。

購入入力は架空の氏名・住所・電話・`pmo-review@example.test`とFREE。外部決済・モデルAPIは使用していない。
S6は全3生成物でブラウザーがPOSTを送信し、サーバーが検証エラーを返した。
ブラウザー検証による送信抑止は発生しておらず、それをサーバー拒否の証拠に置き換えていない。

以下の表の証拠名は条件別ディレクトリからの相対パス。各画面の`.browser.json`には同名のPNG/DOM記録がある。
24件の期待値・観測値・判定・全証拠パスは[results.json](../artifacts/reviews/ms1-pmo-20260919-153326/results.json)にも記録した。

## 24件の結果

### explore — 8 pass

証拠基点: [explore/](../artifacts/reviews/ms1-pmo-20260919-153326/explore/)

| ID | 要件／評価項目 | 期待値 | 観測値 | 判定 | 主要証拠（相対パス） |
|---|---|---|---|---|---|
| S1 | R-006/008/010/011; C-007/009/011/012 | 実リンクでHome→ジャンル→詳細→追加。商品・価格・件数表示 | Rock111件、商品1・8.99、追加後Cart(1)。各画面200、追加302。商品2詳細もS3で確認 | pass | `S1-01-home.browser.json`〜`S1-04-cart-one.browser.json`; `S3-01-second-product-details.browser.json` |
| S2 | R-012〜015; C-013〜016 | 1→2→1→0、合計が対応。3個26.97 | 数量1/2/1/0、合計8.99/17.98/8.99/0.00。3個26.97 | pass | `S2-01-quantity-two.browser.json`〜`S2-04-same-three-total.browser.json` |
| S3 | R-016; C-017 | 異商品が別行、合計一致、エラーなし | 商品1×2＋商品2×1、2行26.97。500・主キー違反なし | pass | `S3-02-two-products.browser.json`; `S4-before.db.json` |
| S4 | R-018/020/021/025; C-019/021/022/026 | FREEで302、整数注文番号・DB保存・空カート | Complete/1、order-number=1。Orders/OrderDetailsへ26.97と2明細保存。カート0 | pass | `S4-02-complete.browser.json`; `S4-after.db.json`; `S4-03-empty-cart.browser.json` |
| S5 | R-023; C-024 | 無効PromoCode後も商品・数量・合計・既存注文集合不変 | NOT-FREE POST→200検証エラー。商品1×2/17.98、Orders={1}が前後一致 | pass | `S5-01-cart-before.browser.json`; `S5-03-server-rejected.browser.json`; `S5-04-cart-after.browser.json`; `S5-before.db.json`/`S5-after.db.json` |
| S6 | R-024; C-025 | 空FirstName＋FREEも同じ保持。サーバー拒否を区別 | POST→200検証エラー。Bの商品2×1/8.99、Orders={1}が不変。送信抑止なし | pass | `S6-01-B-cart-before.browser.json`; `S6-03-server-rejected.browser.json`; `S6-04-B-cart-after.browser.json`; `S6-before.db.json`/`S6-after.db.json` |
| S7 | R-017/022; C-018/023 | A/B双方の商品が分離、A購入後もB保持。他人Completeは403/404・情報なし | A商品1×2/B商品2×1。A削除・注文2後もB×1/8.99。BのComplete/2は404、本文空 | pass | `S7-02-A-while-B-populated.browser.json`; `S7-04-B-unchanged.browser.json`; `S7-07-B-retained-after-A-purchase.browser.json`; `S7-09-B-http-complete.json` |
| S8 | R-005; C-006 | 同DB再起動後も注文・カタログ保持、新ID発行 | Orders={1,2}が再起動直後に残る。10ジャンル/246アルバム/Rock111不変。新ID3 | pass | `S8-before.db.json`; `S8-after-before-purchase.db.json`; `S8-final.db.json`; `S8-07-new-order.browser.json`; `S8.restart.container.json` |

### preload — 7 pass / 1 fail

証拠基点: [preload/](../artifacts/reviews/ms1-pmo-20260919-153326/preload/)

| ID | 要件／評価項目 | 期待値 | 観測値 | 判定 | 主要証拠（相対パス） |
|---|---|---|---|---|---|
| S1 | R-006/008/010/011; C-007/009/011/012 | 実リンクで遷移、商品・価格・件数表示 | Rock111件、商品1・8.99、追加302→Cart(1)。商品2詳細も表示 | pass | `S1-01-home.browser.json`〜`S1-04-cart-one.browser.json`; `S3-01-second-product-details.browser.json` |
| S2 | R-012〜015; C-013〜016 | 1→2→1→0と金額・件数が対応 | 数量は2→1→0、合計は17.98→8.99、Cartは2→1の古い値が残る。独立した1個開始でも再現。3個26.97は合格 | **fail** | `S2-02-quantity-one.browser.json`; `S2-03b-zero-stable.png`; `S2-03c-zero-reloaded.browser.json`; `S2-07-followup-one-before.browser.json`; `S2-08-followup-zero-stale.browser.json` |
| S3 | R-016; C-017 | 別商品2行、合計26.97、エラーなし | 商品1×2＋商品2×1、2行26.97。500・主キー違反なし | pass | `S3-02-two-products.browser.json`; `S4-before.db.json` |
| S4 | R-018/020/021/025; C-019/021/022/026 | FREE購入、整数番号・DB保存・空カート | 302→Complete/1、注文1/26.97/2明細保存、カート0 | pass | `S4-02-complete.browser.json`; `S4-03-empty-cart.browser.json`; `S5-before.db.json` |
| S5 | R-023; C-024 | 無効コードでも商品・数量・合計・Orders集合不変 | POST200検証エラー。Aの商品1×2/17.98、Orders={1}が不変 | pass | `S5-01-cart-before.browser.json`; `S5-03-server-rejected.browser.json`; `S5-04-cart-after.browser.json`; `S5-before.db.json`/`S5-after-S6-before.db.json` |
| S6 | R-024; C-025 | 空FirstName＋FREEで状態保持・サーバー拒否 | POST200検証エラー。Bの商品2×1/8.99、Orders={1}が不変。送信抑止なし | pass | `S6-01-B-cart-before.browser.json`; `S6-04-B-cart-after.browser.json`; `S5-after-S6-before.db.json`/`S6-after.db.json` |
| S7 | R-017/022; C-018/023 | 双方の商品分離、A変更後B不変、他人Complete拒否 | A商品1×2/B商品2×1。A削除・購入ID2後もB×1/8.99。B→Complete/2は404、本文空 | pass | `S7-02-A-while-B-populated.browser.json`; `S7-03-A-changed-stale-total.browser.json`; `S7-07-B-retained-after-A-purchase.browser.json`; `S7-09-B-http-complete.json` |
| S8 | R-005; C-006 | 再起動後注文・カタログ保持、新ID | {1,2}を新購入前に確認、カタログ10/246/Rock111不変、新ID3 | pass | `S8-before.db.json`; `S8-after-before-purchase.db.json`; `S8-final.db.json`; `S8-07-new-order.browser.json`; `S8.restart.container.json` |

S5のDB後照合には次のS6用Bカートも含むため、Carts表全体の件数不変とは主張しない。
Aの表示カートと既存注文行は不変、S6ではBのカートを個別に比較した。S7のAの合計表示不具合はS2へ計上した。

### explained — 7 pass / 1 fail

証拠基点: [explained/](../artifacts/reviews/ms1-pmo-20260919-153326/explained/)

| ID | 要件／評価項目 | 期待値 | 観測値 | 判定 | 主要証拠（相対パス） |
|---|---|---|---|---|---|
| S1 | R-006/008/010/011; C-007/009/011/012 | 実リンクで遷移、商品・価格・件数表示 | Rock111件、商品1・8.99、追加302→Cart(1)。商品2詳細も表示 | pass | `S1-01-home.browser.json`〜`S1-04-cart-one.browser.json`; `S3-01-second-product-details.browser.json` |
| S2 | R-012〜015; C-013〜016 | 1→2→1→0と金額が対応 | 削除リンクを押してもPOSTなし、数量2/17.98のまま。別の数量1開始も不変。HTTP診断では削除可能 | **fail** | `S2-02-quantity-one.browser.json`; `S2-03-quantity-zero.browser.json`; `S2-after-failed-clicks.db.json`; `S2-08-B-quantity-one-before-click.browser.json`; `S2-09-B-quantity-one-click-no-effect.png` |
| S3 | R-016; C-017 | 別商品2行、合計26.97、エラーなし | 商品1×2＋商品2×1、2行26.97。500・主キー違反なし | pass | `S3-02-two-products.browser.json`; `S4-before.db.json` |
| S4 | R-018/020/021/025; C-019/021/022/026 | FREE購入、整数番号・DB保存・空カート | 302→Complete/1、注文1/26.97/2明細保存、カート0 | pass | `S4-02-complete.browser.json`; `S4-03-empty-cart.browser.json`; `S5-before.db.json` |
| S5 | R-023; C-024 | 無効コードでも商品・数量・合計・Orders集合不変 | POST200検証エラー。商品1×2/17.98、Orders={1}が不変 | pass | `S5-01-cart-before.browser.json`; `S5-03-server-rejected.browser.json`; `S5-04-cart-after.browser.json`; `S5-before.db.json`/`S5-after.db.json` |
| S6 | R-024; C-025 | 空FirstName＋FREEで状態保持・サーバー拒否 | POST200検証エラー。B商品2×1/8.99、Orders={1}が不変。送信抑止なし | pass | `S6-01-B-cart-before.browser.json`; `S6-04-B-cart-after.browser.json`; `S6-before.db.json`/`S6-after-S2-one-unchanged.db.json` |
| S7 | R-017/022; C-018/023 | 双方の商品分離、A変更・購入後B不変、他人Complete拒否 | A商品1×2/B商品2×1からAに商品3追加。A注文2/26.97後もB×1/8.99。B→Complete/2は404、本文空 | pass | `S7-02-A-while-B-populated.browser.json`; `S7-03-A-added-third-album.browser.json`; `S7-07-B-retained-after-A-purchase.browser.json`; `S7-09-B-http-complete.json` |
| S8 | R-005; C-006 | 再起動後注文・カタログ保持、新ID | {1,2}を新購入前に確認、カタログ10/246/Rock111不変、新ID3 | pass | `S8-before.db.json`; `S8-after-before-purchase.db.json`; `S8-final.db.json`; `S8-07-new-order.browser.json`; `S8.restart.container.json` |

explainedの`S2-02-quantity-one`/`S2-03-quantity-zero`は操作時に意図した状態を表すファイル名であり、
実観測は数量2のまま。後続S3の初期状態を整えるため、同一セッションの正しいRemoveFromCartへ補助POSTを行い、
数量1/0/2への変化を`S2-04/05/07-diagnostic-http-*`へ別保存した。これをS2のブラウザー合格には数えていない。
S3の商品追加・S4の購入は実リンク・フォームで実施した。S7では機能する追加操作でAを変更し、削除不具合を迂回して分離そのものを検証した。

## 不一致の原因と処置

| 区分 | 原因・元評価との関係 | 処置／残る事項 |
|---|---|---|
| 生成物違反: preload | `ShoppingCartController.RemoveFromCart`が`CartTotal`/`CartCount`を計算した後で`RemoveFromCart`を実行。画面JSは古いJSON値を表示。C-015/C-016は別GETで正しい状態を再取得し、元評価はpass | 固定コードは未修正。2→1と独立した1→0で再現、再読込で正常化する差も保存。将来の修正候補は削除後に合計・件数を計算する順序変更 |
| 生成物違反: explained | ViewのRemoveLinkは`href="#"`で、イベント処理・送信スクリプトがない。クリックでHTTPが発生しない。評価器の直接POSTだけは成功するため元評価はpass | 固定コードは未修正。数量2と数量1の双方で再現。将来の修正候補は削除POSTと画面更新の接続 |
| 評価器の見逃し | C-015/C-016が実際のクリック結果を観測せず、HTTP APIと再読込の状態だけで合格にしていた | `BrowserCartReview`を追加し、独立採取した操作前後DOM・PNGのハッシュ、instance/artifact/spec、時刻、同一tab/URL、正常な開始数量・合計を検証。HTTP判定と画面判定の両方を要求する別保存訂正を実施 |
| 実査環境 | 重複Rockリンクによるセレクター曖昧性、出力短縮処理のread-only API例外 | DOMを確認して対象を限定し、通常出力へ戻して同じ固定生成物で継続。初回の失敗は`environment-attempts.jsonl`へ保存 |
| 実査環境 | Chromeで他セッションCompleteへの画面遷移が`ERR_BLOCKED_BY_CLIENT`表示 | 最初の画面・通信失敗を保存。サーバーログで404/0 byteを確認し、同じBコンテキスト・同じオリジンの補助HTTPでも404/空本文を確認。画面エラーだけでR-022を合格にはしなかった |
| 対象外 | CSS・画像の404、一部画像なし | 公開要件にない外観条件を追加しない。リンク・操作が機能するかは個別に検証し、削除不具合は要件違反として判定 |

HTTP補助は公開要件の403または404という契約を用いた。403だけを要求していない。
CDPのChromeイベントには次の観測ファイルへ遅れて現れるものやイベントバッファの切り詰めがあり、
POST/redirect等は隣接記録・サーバーログも照合した。302は`requestWillBeSent.redirectResponse`も確認した。
全3条件の最終サーバーログは各`final.stop.server.log`、preload追試は`followup-final.stop.server.log`。

## 訂正評価・回帰と適用範囲

生成物・公開要件・介入条件は変更していない。`cartTotal`を新しい必須JSONフィールドにもしていない。
修正範囲はC-015/C-016に独立画面証拠を結び付ける任意入力と、その検証・カバレッジの明記。
証拠のない通常呼び出しは互換性維持のHTTP評価で、`browserCartCoverage: not_run_http_only`と未観測の説明を出す。
したがって**ブラウザー証拠なしの100点をUI合格と扱う問題は、通常運用への自動接続まで完了したわけではない**。
今回の3件の見逃しは証拠付き訂正へ反映済み。今後の自動採取に実ブラウザー操作を接続する作業は残る。
ハッシュは証拠の同一性を検査するが、操作の真正性は独立した採取者に依存する。今回の採取者は本エージェントである。

訂正バンドルは保存イメージ/SDK 8.0.425でネットワークなしにビルドした。
DLL SHA-256: `7c9b7960bc95880571f619f9a698494fbfb24116d6890dde50389468cbf8b3b4`。
**回帰テスト56件合格、ビルド警告0・エラー0**。古い合計、無反応リンク、空の前提、改変証拠、
別Run/別仕様/別成果物、別セッション、逆転時刻、HTTP異常を画面passで隠すケースを確認した。
最初のテストビルドはテスト側Program名の衝突で失敗し、名前空間指定で修正した。
初回ログは`evaluator-build/`、成功結果は[evaluator-build-2/](../artifacts/reviews/ms1-pmo-20260919-153326/evaluator-build-2/)に保持した。

各条件で同じ訂正バンドルを用いたHTTPのみの対照評価（sequence 901）と画面証拠付き訂正評価（902）を、
元の読み取り専用成果物・元仕様・保存イメージ・毎回新しいDBで実行した。これは新規研究Runではない。

| 条件 | 元評価 | 訂正コードのHTTP対照 | 画面証拠付き訂正 | 変更した要件 |
|---|---|---|---|---|
| explore | 100 / pass / 29合格 | 100 / pass | 100 / pass / 29合格 | なし |
| preload | 100 / pass / 29合格 | 100 / pass | **93.10 / fail / 27合格2不合格** | R-014、R-015 |
| explained | 100 / pass / 29合格 | 100 / pass | **93.10 / fail / 27合格2不合格** | R-014、R-015 |

6評価ともerror/blockedは0、元仕様・成果物・訂正DLLの同一性検査に合格。
他27要件の判定に変更はない。[訂正比較一覧](../artifacts/reviews/ms1-pmo-20260919-153326/correction/summary.json)、
各`correction/<condition>/<mode>/result/evaluation.json`、`comparison.json`、`intent.json`に全結果・引数・ハッシュがある。
元の採取時評価、既存R-029訂正評価、v3受渡し記録には書き戻していない。
今回の結果から探索全体の合格率や中央値を再計算することもしていない。

## 終了確認と次の判断

[終了時ハッシュ照合](../artifacts/reviews/ms1-pmo-20260919-153326/integrity-final.json)で、
元3 Run全体1,791ファイル、v3 frozen 103ファイル、v3起動物136ファイル、既存確認用起動物136ファイルが
開始時と一致した。元/v3のreview-targetsも不変。公開要件・凍結プロトコルの変更はない。

[終了記録](../artifacts/reviews/ms1-pmo-20260919-153326/closure.json)で、今回の3アプリコンテナーは停止済み。
6つの訂正評価コンテナーも終了・削除済み。確認用ブラウザータブは閉じた。
各`state/store.sqlite`と付随ファイルは今回の領域に保持し、読み取り専用の`integrity_check=ok`、Orders={1,2,3}を確認した。
DB・Cookie記録・PNG・生ログ・ビルド失敗を含む詳細証拠はローカルに残し、Gitへ追加していない。
ソース修正と報告は上記ローカルブランチの未コミット差分で、push・PR作成・外部公開はしていない。

今回のユーザー指示に従い、既存2文書へ「PMO委任のエージェント実査で工程を進める」旨を追記した。
過去の人の実施記録やNot run欄は変更していない。

**次段階へ進むために残るのは、固定2生成物の不合格を研究上どう扱うかと、実操作を通常評価へ接続する範囲の決定である。**
現行の「24件すべて合格」基準ではこのゲートを閉じられない。画像不足や人間未実施を理由に止めているのではない。
推奨は公開要件・条件を維持し、まずC-015/C-016の実ブラウザー観測を通常評価へ接続する限定作業を次のIssueとして切り出し、
既存生成物2件は不合格のまま保存すること。固定物を修正・差し替えてこの実査を合格にする扱いはしない。
不合格を許容して次の2条件比較へ進む基準変更、または生成物を改めて採取する方針は研究判断であり、本作業では実施していない。
