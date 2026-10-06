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

* Python有限受入83 test methods合格。再評価runner、独立境界、2 dummy campaigns＋1 reassessment、監査、browser/cleanup/prerequisiteを含む。
* Education実配備DLLの60 assertions合格。SDK8.0.425、同一compile pathで2回クリーンビルド一致、commit前後DLL/PDB一致。
* Music実配備DLLの94 tests、legacy走査24 tests合格。同SDK・同compile pathで2回一致、commit前後DLL/PDB一致。
* 実Chrome/PlaywrightのローカルHTTP fixture5件合格。正常操作、要求操作500、無関係500、unsupported操作を区別。実collector receiptとC#消費側の相互運用を確認。
* [原200件の結合監査](evaluator-binding-audit-20261006.md)：4,300要求/4,500checkの台帳・oracle・実DLL・生成物結合不一致0。Education旧DLL6件/診断DLL94件、Music100件。183件は別再評価の入力候補、17件は空生成物、20件は最終check結果行0。これは品質承認ではない。
* 独立した測定妥当性、実装/原本安全性、再取得/公開導線レビューを実施。同じモデル系列のレビューを独立専門家合意とは呼ばない。human reviewはnot_run。

## 別保存再評価と実行ブロック

`research/saved_reassessment.py`は、原Runのcondition/inputs/context/profiles/assets/snapshotを読取り検証し、生成物・oracle/初期DB・新台帳・新DLLを新assessment rootへコピーする。新assessment UUIDと旧Run UUID/artifact SHAを結合する。原Runの採点indexやadopted summaryへ書き込まない。既存assessment出力は再利用せず、STOP、部分観測、後処理故障、foreignコンテナー、原本確認不能を合格にしない。

保存例5件を事前固定し、モデル呼出し0、HTTP scorer各900秒以内での受入を計画した。対象はCU-D-explore-5073、CU-C-explore-5080、CU-D-preload-5053、MS-A-preload-5096、MS-B-preload-5067。各例は新しい評価を行うもので、歴史的な未観測操作を復元するものではない。

**この5件の実行は起動前に自動承認レビューで拒否され、実行0件。** 拒否理由は「各ケースで`repair_spec.write(...)`により元Runの`evaluation-assets/requirements.json`を直接書き換え、原本保全の承認範囲を超える」とされた。

コードの実際の引数は、原ファイルをsource、独立した`evaluator-repair-evidence-20261006/saved-acceptance-stages/<Run>-requirements.json`をdestinationとする。`repair_spec.py`の`write`はsourceとdestinationが同じなら拒否し、sourceは`read_json`、destinationは`write_new_json`で排他的作成する。原ファイル不変と既存destination拒否の試験も通っている。拒否後は同じ実行を再送せず、根拠と正確な操作を親へ報告した。assessment stageは未作成。

修正コードと有限fixtureの受入は完了しているが、**実保存アプリのLinux隔離実行と新評価版による別保存再評価の受入は未完了**。このブロックを解消して保存例の終了・cleanup・原本不変を確認するまで、新100ペア取得可とは判断しない。

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
| Music postcommit receipt | `3070ae7de5669d6b2a400ff89b20c04e87bf15e0fb2d182b186be2ecf8d6cf87` |
| 実装/原本安全性レビューreceipt | `b26f142e67ecebf633b8be286e3dcb2d880eaa807d3aca62c52f61c98587c967` |
| 固定した保存例5件計画 | `a7553dd4f7332fba3820e7a346acf62430a32b671ec73fb86e48019f5f084c3d` |

研究分析部分では`.agents/skills/research-analysis/SKILL.md`、`scientific-critical-thinking/SKILL.md`とSIGSOFT General/Benchmarkingを使用した。一次資産・測定定義・有限校正の検討に適用し、基盤修正やworkerへのSkill導入の許可とは扱っていない。
