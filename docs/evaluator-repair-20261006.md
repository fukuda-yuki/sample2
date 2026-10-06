# 評価器修正と有限受入の状態

修正ソースは `6638246d8a0286647dfc338ca57efe8526c6504f` に固定した。原100ペア・200 Run、旧採点、凍結評価器、公開v1/v2の成果物は保全している。新モデル取得は行っていない。

## 修正と正解の根拠

| 現象・一次証拠 | 分類 | 新評価版の変更・有限の受入 |
| --- | --- | --- |
| 保存5073のStudents.EnrollmentDateとDepartments.StartDateで日付文字列だけが異なる | DB暦日意味と保存表現の混同。公開UIの日付形式とは別 | Education1.1.0で指定列のみ暦日比較。厳密な日付と空白/T区切りの午前零時、ゼロのみの小数秒を許容。非零時刻・非零小数・offset・不正日付を拒否。UIはYYYY-MM-DD厳密 |
| 作成IDを姓名一致のみで取得 | 既存行を選択し得る実装の危険。歴史的誤合格が発見済みという主張ではない | DB実行前後のID差分を使用。既存行、複数追加、削除、重複ID/DOMマーカーの負例 |
| WAL中の観測、読取不能、null/空文字 | 観測器故障と製品の値/schema不一致を分離する必要 | 一つの読取transaction、committed WAL、同時writer、typed snapshot、null/空文字、列名大小文字の試験。原SQLiteへ接続せずコピーのみを評価 |
| 保存5096の`/tmp/mvc-music-store/musicstore.sqlite` | データ保存先の名称だけでlegacy依存とした誤失敗 | Music1.4.0で名前の言及と実参照/起動を分離。元DLLで同じ保存treeから2件、新DLLで参照0/未解決0。読取不能・不明な依存はunknown、実legacy依存は負例 |
| 保存5053のCreate view欠落500、5067のAddToCart UNIQUE違反500 | 製品の要求操作の失敗。後続操作は未観測 | 実送信payload、対象origin/operation、応答status、hashに結合。確認済み失敗とobserver faultを独立保持。未実行のSave/削除から合否を作らない。partialのqualityはnull |
| 正しい500の後に壊れた証跡やbody-read faultを追加 | 確認済み失敗を消す回帰を独立レビューで再現 | 先に検証した事実を保持し、後続faultを別記録。foreign origin、無関係favicon500、unsupported Save、偽status、欠測の負例 |
| Music旧台帳の固定価格説明とDB対象外説明 | 台帳説明と変種別oracle/追加migration要求の矛盾 | 別保存の新台帳生成で説明を修正。要求/check ID・severity・migration oracle資産は維持。旧台帳と旧ラベルは不変 |

### 実行済みの検証

* Python初期有限受入83 test methods合格。再評価runner、独立境界、2 dummy campaigns＋1 reassessment、監査、browser/cleanup/prerequisiteを含む。
* Education実配備DLLの60 assertions合格。SDK8.0.425、同一compile pathで2回クリーンビルド一致、commit前後DLL/PDB一致。
* Music実配備DLLの94 tests、legacy走査24 tests合格。同SDK・同compile pathで2回一致、commit前後DLL/PDB一致。
* 実Chrome/PlaywrightのローカルHTTP fixture5件合格。正常操作、要求操作500、無関係500、unsupported操作を区別。実collector receiptとC#消費側の相互運用を確認。
* [原200件の結合監査](evaluator-binding-audit-20261006.md)：4,300要求/4,500checkの台帳・oracle・実DLL・生成物結合不一致0。Education旧DLL6件/診断DLL94件、Music100件。183件は別再評価の入力候補、17件は空生成物、20件は最終check結果行0。これは品質承認ではない。
* 独立した測定妥当性、実装/原本安全性、再取得/公開導線レビューを実施。同じモデル系列のレビューを独立専門家合意とは呼ばない。human reviewはnot_run。

## 別保存再評価の実行と採用判定

`research/saved_reassessment.py`は、旧Runのcondition/inputs/context/profiles/assets/snapshotを読み取り検証し、保存生成物・oracle/初期DB・新台帳・新DLLを新assessment rootへコピーする。新assessment UUIDと旧Run UUID/artifact SHAを結合する。旧Runの採点indexやadopted summaryへ書き込まない。既存assessment出力は再利用せず、STOP、不完全観測、後処理故障、foreignコンテナー、原本確認不能を合格にしない。

保存例5件を事前固定し、モデル呼出し0、HTTP scorer各900秒以内で実行した。各例は新しい評価実行なので、歴史的な未観測操作を復元するものではない。

最初の起動は自動承認レビューが原本への台帳上書きと解釈し、起動前に拒否した。親から明示的な承認証拠を受領し、sourceが読み取りのみ、destinationが別rootへの排他的作成であることを5絶対パス・全祖先のsymlink/junction不在・包含なし・原本全ファイルinventoryで再確認した。指定どおり同一tool callを一度再試行し、承認された。拒否された試行から実行は発生していない。

実5件は隔離Linux scorer、実Chrome/Playwright操作、新評価DLLによる合成まで終了した。原本全ファイルinventory不変・所有コンテナー/network終了を5件すべてで確認した。API呼出し・新取得Run増分は0である。

| 保存Run | 新assessment ID | 新評価の観測結果 | 採用範囲 |
| --- | --- | --- | --- |
| CU1-ENR-D-explore-5073 | `87f0b75ecef9413298476dcb2c581cf1` | complete、pass、quality 100 | Education1.1.0で日付保存表現と実Create/Edit/Saveを観測 |
| CU1-ENR-C-explore-5080 | `d67a445fe95e41f1992e1a57f7a0e4f1` | complete、fail_critical、quality 83.33 | 不正日付POSTの302をE-008/E-010で負例として保持 |
| CU1-ENR-D-preload-5053 | `e1ff7ff17c5a465e8224d098c2b5156d` | incomplete、fail_critical、quality null | Create viewの500を保持。未実施Saveまで合格にしない |
| MS1-CONT-A-preload-5096 | `305ce31cc5214615abfcd720987e5f40` | complete、pass、quality 100 | Music1.4.0で保存先名とlegacy依存を区別し、実削除を観測 |
| MS1-CONT-B-preload-5067 | `fd4038d13dbd47eaa1b70a2d5aa6e6bd` | incomplete、fail_critical、quality null | AddToCartの500を保持。C-015は観測、C-016は未観測 |

5件のraw `evaluatorFaults` は空である。5067のbrowser終了コード2は、C#合成器のresearchStatus不完全時の通常終了分岐であり、観測器故障とは別である。元の包括的operation status `evaluation_partial_or_fault` は書き換えない。

実行により、Education外側の採用ゲートが旧receipt schema 1だけを受け付け、新1.1.0のschema 2の完全観測を拒否する結合不備が見つかった。最初の5件の結果・raw出力・旧controller inventoryを保全し、1.0.0→整数schema 1、1.1.0→整数schema 2を要求する修正と、要求hash・UUID/artifact/spec/版・所有loopback origin・faultの境界試験を追加した。修正後の採用判定は別validation IDの読み取り専用派生receiptに記録し、評価器やアプリを再実行しない。これは同じ5件の採用判定の修正であり、新評価実行数・新Run数を増やさない。

最終の読み取り専用検証はcontrollerのbytesを固定して5件すべて終了した。完全観測として採用3件（pass 2件、critical failure 1件）、部分観測2件（品質null、確認済み製品失敗を保持）、observer fault 0件である。元の5 assessment rootと原本の全ファイルinventoryは検証前後でも不変だった。

| 保存例 | 最終validation ID |
| --- | --- |
| 5073 | `116c60bbf9ce4ca4b36a646f68e1d9fc` |
| 5080 | `356152c49a8d46f9a74f00a7be429993` |
| 5053 | `c704781cea81481da7c8803d44c74a77` |
| 5096 | `4aca5bb315684f5781092d2ea86437db` |
| 5067 | `6b71c87e508a49d1a806c27719760586` |

`revalidate`は原評価版/spec、HTTP baselineの評価JSONとcheck行両hash、実DLL/manifest、spec/artifact/UUID、HTTPとbrowserのcleanup owner/resource集合を照合する。評価時のcontroller inventoryと現在の検証実装SHAは別記録である。否定fixtureで発見したbaseline hashと旧spec/versionの拒否不足も修正し、独立レビューで再現fixtureが拒否されることを確認した。

再検証の入口は `python -B -X utf8 -m research.saved_reassessment revalidate <保存assessment root> <別rootの新receipt.json> --repo <修正checkout>`。既存receiptへの上書き・同じrootへの保存は拒否する。private保存例の入力資産はこの報告書へ添付しない。

### 実負例で判明した削除前提の不備と別版修正

5067ではHTTP側のAddToCartが500で失敗し、空cartのままid=0でRemoveFromCartを送って404になっていた。1.4.0のHTTP C-015/C-016は削除前提の数量・実record IDを検証せずfailを付け、合成器がそのfailを保持した。新ブラウザーではC-015のクリック自体は成功し、C-016はAdd失敗により未実施だった。したがってraw R-014/R-015のfailは実削除失敗の証拠にはしない。全体のfail_criticalは独立したAddToCart HTTP500で確実であり、partial/quality nullは維持する。

既に実行した1.4.0のDLL・台帳・assessment出力を保持し、修正は別評価版1.5.0へ分ける。C-015のHTTP削除前にはalbum 1の単一行・数量2・正の実record ID、C-016の前にはC-015後の単一行・数量1・現在の正の実IDを要求する。前提不成立なら削除POSTを送らずblockedとする。HTTP JSONが未観測のままブラウザー成功だけでcompleteにはしない。独立したブラウザー失敗はHTTP観測故障と併記できる。既存1.4.0の結果のラベルを書き換えない。

1.5の有限受入は削除前提とその合成境界を対象とする。新配布DLLで115 tests、Python側の関連101 testsが通過した。SDK8.0.425の同一compile pathで2回のforced buildはDLL/PDB一致を確認した。実結合の確認には、先の5件とは別の固定計画で保存5067/5096の2件を使用する（モデル呼出し0、新取得Run増分0）。quantity/record IDが不成立ならPOSTを送らないこと、C-015後に変わった実IDをC-016で使うこと、旧1.4の分岐を保つことをHTTP dispatch spyで検証する。HTTP未観測から独立ブラウザー失敗を保持しても、未観測scopeを別に残しpartial/nullを維持する。これらはC-014やcheckout全体の因果的な失敗帰属を一律に保証するものではない。

## 次取得を判断する境界

[実験一覧](experiments.md)からreport/data/code/reproduceへ進める。同じrepoの[ID/保存/配布アダプター](experiment-identity.md)で、2 dummy campaignsの新UUID/root/lease世代/STOP/output/publication分離と、再評価の別保存、旧bytes不変、別フォルダーrestore/toy再計算を確認した。元実験のregistry UUID対応はcaller asserted/unverifiedと明示している。

新dispatcherへの接続、実workerのSTOP/ACK/process終了・復旧、公開する正確なbytesの権利/秘密確認と実匿名downloadは別の開始前ゲートである。既存v5/v1～v10の凍結取得系を新campaignへ流用しない。新repoの作成だけでもこれらは直らない。

静的走査で全間接起動を証明せず、有限の要求操作以外のHTTP500を自動で品質失敗へ変換しない。Education E-002の一般的依存解決、長時間lock、未試験の業務操作、将来の無故障は保証しない。再評価で合格数が変わっても製品改善やtoken改善と呼ばない。

## 証跡

private証跡はGit外の`evaluator-repair-evidence-20261006`、`education-checks-temp/education-1.1.0-final`と作業treeのignored `artifacts/`に保管した。原oracle、DB、生ログをこの報告へ添付しない。

| 証跡 | SHA256 |
| --- | --- |
| 原200結合監査 | `a09113c86f0a80404600a5b660cb57f0e7168132dee201468a25a70ade4156e2` |
| Education配備DLL | `ff09d9f6e8446685fc9ce8217ea2fe2ce9d80f8f11c081a899dd3a494902bb12` |
| Education postcommit witness | `b1192bef1ca6351041373eb661295a8a6376a29252b03929cd2a797665b6f764` |
| Music配備DLL | `76874e46940f7816a56e93c36391d3213f790335a1bd6e0409ae5515c36c478e` |
| Music1.4 postcommit receipt | `3070ae7de5669d6b2a400ff89b20c04e87bf15e0fb2d182b186be2ecf8d6cf87` |
| Music1.5配布DLL | `8fed5989f4e000beafb24bdf8b9c5713ede90ce730775ce9eda8e7bbcb7f4852` |
| 実装/原本安全性レビューreceipt | `b26f142e67ecebf633b8be286e3dcb2d880eaa807d3aca62c52f61c98587c967` |
| 固定した保存例5件計画 | `a7553dd4f7332fba3820e7a346acf62430a32b671ec73fb86e48019f5f084c3d` |
| 承認再試行前の5絶対パス・原本inventory確認 | `38bc3b9c5c406b9ed159e73d5e8a0686a06c653d7991f1a70443691256e601f6` |
| 最初の実5件結果（採用ゲート修正前、保全） | `e3d17fbf8b39a5635bdd56c1fd6bf3b83ded9b8acb75e251436005cca5496e18` |
| 最終5件の読み取り専用検証aggregate | `ae53064ae488546470e499beb57b1b2314986994344ae44b087682231a5ad26d` |
| 検証前の原本・assessment全bytes確認 | `dca5e532828839deca7373899cded551e048365a13deda4d31b57261167f5856` |

研究分析部分では`.agents/skills/research-analysis/SKILL.md`、`scientific-critical-thinking/SKILL.md`とSIGSOFT General/Benchmarkingを使用した。一次資産・測定定義・有限校正の検討に適用し、基盤修正やworkerへのSkill導入の許可とは扱っていない。
