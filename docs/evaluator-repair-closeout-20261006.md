# 評価器修正・終了確認の現在地

2026-10-06 06:15 UTC時点。旧実行の記録は上書きせず、[修正履歴](evaluator-repair-20261006.md)と区別して読む。固定評価ソースHEADは `381d7d16539a2960a363d45c897b572667b3f0bb`。以後の変更は本節・入口文書とtest fixtureに限定し、本番実装・凍結plan・原評価・原本を変更していない。

原取得は100ペア・200実送信で完了。正常163、operator stop33、provider failure3、timeout1、未送信・不明送信0。追加モデルrequestは0。旧採点と原Releaseを維持する。

保存評価は19試行・7 unique生成物。本文15評価はcomplete5（pass4/critical failure1）、partial7、observer fault3、quality数値5/null10。別保存HTTP-only4試行はbrowser未実施・validation ID null・quality nullのまま保持し、全19試行ではquality null14。最新4件のfault0を旧3件のfault消去に使わない。15の読み取り専用validation receiptは新取得Runや独立品質監査に換算しない。19試行のUUID/source/評価版/receiptを照合した対応表SHAは `df02c12ad039a6012d571e62638bab8b73629de09d011915ce28eddc751ca3c4`。

Music1.6 accepted DLL SHAは `eb62763802d6b11d0b5a5915f3454fb727775fbe76d6c3e24406082168938f0d`。HTTP exit2からbrowserへ進む厳密な分岐とnative TD投影を修正し、旧HTTP-only試行を保持したまま新UUIDで再実行した。schema2 readerは旧7評価とHTTP-only4試行のSHAを保持し、schema1 readerも別保存した。

非モデル運用は2 campaign・4 Run（正常3/意図した途中STOP1）と保存再評価1件を実施。実SDK lifecycle、8 owned container/4 networkの終了、observer ACK2/2、live resource146.1521593秒、原本8 tree/240,224 fileの実行後全bytes一致を確認した。実行前inventoryは既存証跡の明示的再利用であり、fresh prescanではない。4 Runと再評価1件は原200・保存評価19件に加算しない。独立終了proof SHA `5e15dbad1014dab2723b27544facfacb26f37ff81ae63e1dc4908db054a5f2eb`、最終運用result SHA `6684282b1e44a3a82a729598387fc1add8dd62efcf9a849e33918b8d70a7801e`。

## 検証と限界

全C#確認は338 assertion invocations（Music220/money58/Education60）と別のLegacy24 named casesがPASS。receipt SHA `534147a5d54c78c215640b38cf7c7fbbee0c6b1f1103b18339e7d9da5024f706`。Pythonはouter全247件（実local browser fixture5件を有効化）、serializer4件、匿名検証用33件がPASS。匿名検証テストのdownloadはmockであり、実匿名取得は別の証跡で確認する。

research初回全484メソッドはfail2記録（同じCLIメソッドの2 subcase）、error24記録。ログSHA `6701ad35ecc09b6d9428ae698c3d0f9bea9aff1108d04600c265196c116da0fc` を保全した。原因と処置は次の通り。

| 初回の失敗 | 原因と処置 | 保持した検証境界 |
| --- | --- | --- |
| valid CLIの2 subcase | parent sys.pathだけに既存SciPy依存を追加し、子CLIへ未伝播。固定の既存依存pathを明示伝播 | 新規install・計算実装緩和なし。valid/forged入力を再検査 |
| r3 setup19件・frozen pin確認1件 | 歴史的fixtureに現行sourceをコピーし、SHA guardが後続変更を正しく拒否。固定local Git blobとSHAを使うfixtureへ修正 | corrupt blob・改変source・改変planは拒否。凍結pinは不変 |
| 教育input adapter1件 | pinned upstream snapshot欠測で、input返却前にFileNotFoundError。外部source-root境界のみtest mock | 実prepare_assets/adapter、oracle root/DB混入の負例は有効。上流pin検証はこのtestの対象外 |
| preservation3件 | 旧mock先、歴史的仮想acceptanceと現行strict履歴の混在。fixture seamを更新し旧正例は固定旧版で検査 | 現行仮想履歴・権限なしcontractは拒否。production guardは不変 |

変更4モジュール全78件の再実行はPASS。初回PASSした未変更407メソッドと合わせて現行登録485件をexact setで覆い、未変更42 moduleのSHA一致も確認した。これは証跡の集合であり、全485件を一度に再実行した合格ではない。集合検査SHA `1e904ae32b785b2db1dc7781a2157b6ae5aa9c61e8c31841d73376dc91549a94`。独立レビューもfixture緩和なし・集合一致を確認した。

outer初回1 errorはnative tasklistのlocale decodeを行うtest helperで発生した。byte CSVのASCII PID判定に修正し全247件を再実行。実owned子processの生存・終了、command/OSError異常を「不在」に変えない負例を確認した。本番process監視の変更ではない。

private証跡はGit外の `evaluator-repair-evidence-20261006`、配布候補と対応表は `evaluator-publication-20261006`。絶対path、生ログ、DB、oracle、APIキーは公開しない。新adapterでの実model generation、100ペア規模、pair concurrency2、全200生成物の修正版再評価、human reviewは未実施。有限受入を品質改善・token改善・無制限の将来保証へ変換しない。新取得には別の有効な指示と固定planが必要である。

## 公開と残工程

[専用Release](https://github.com/fukuda-yuki/sample2/releases/tag/evaluator-acceptance-20261006-b014b3479c18)のphase A4資産は明示承認後に公開した。実匿名download・別folder restore・固定reader再計算・cleanupは成功し、productionの2 pair publication gateと4 Runフラグが完了した。phase A ZIP SHA `8ecde4b43db860b178764da8430a2bdfa58bcd1bc1c126a0eccbd71ea5028b1f`、manifest SHA `46fc4d9d4d626815c89fabe62a7c5d992ff372f3a1b2a1cc5454bf6d5f62614b`。公開したimmutable bytesは変更しない。

phase Bは最終gateと実phase A proofを反映した別packageとして封印・読取監査済み。ZIP SHA `4c8317200787fa0b1f3a1db5f81c33d56838edd92713c49a4dab38cf9fb5f61c`、manifest SHA `c748912f79da1459ff2d397418f22d06a8e15e890553c2081b721e267f82c8a6`、binding SHA `231ebcc946d6e85a91ca33847488e11fffdbb2d382b861945d4dec0fba3d6fa8`。追加4資産のuploadは自動承認レビューが「先の承認はphase A4資産を対象とし、追加payloadを含まない」として拒否した。Bのupload・実匿名復元は未実施。公開内容の差し替えや別経路による回避は行わない。ユーザー所有成果物の今回の公開許可とrepo全体の包括OSS licenseは別であり、LICENSE不在だけを公開禁止理由にしない。

残工程はB追加対象の明示承認、同一upload callの一度の再試行、B実匿名検証、最終公開入口、`merge --no-ff`統合、remote最終照合。現時点でB配布・最終統合完了とは報告しない。
