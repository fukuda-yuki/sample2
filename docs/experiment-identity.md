# 実験ID・再評価ID・配布の境界

`research/experiment_identity.py`は、同じリポジトリで次の取得と保存生成物の再評価を分ける、モデルを呼ばない小さな保存アダプターです。既存の`next_phase.py`・`wave_*`の凍結済み取得手順は変更しません。このアダプターの試験合格だけで新しい100ペアの取得開始可とは判断しません。

## 実装済みの操作

| 操作 | 生成・検証する境界 |
| --- | --- |
| `create_campaign(base, campaign_id, ...)` | 新UUIDと固定plan SHA・評価版・評価器SHAを、`base/campaigns/<campaign_id>/campaign.json`へ排他的に記録。既存ID・保存先を再利用しない |
| `Campaign.create_run(label)` | 同じtask/labelでもcampaignごとに新Run UUID。`runs/<label>/output/`を専用保存先にする。Run metadataとcampaign bindingが違えば拒否 |
| `acquire_lease` / `request_stop` / `release_lease` | campaign専用`_control`に排他的lease markerと世代UUID。STOPはその世代の専用ファイル。別campaign・旧世代の操作を拒否。leaseは外部processの生存・終了確認を代替しない |
| `create_reassessment(...)` | アダプターで作ったsource RunのSHAを確認し、新assessment UUID・評価版・元Run UUIDへ別保存で結合 |
| `create_frozen_reassessment(...)` | 既存schema-2 Runのmanifest・condition・snapshotと実frozen treeを読取り、stopped/fixed、condition SHA、Run対応、SDK artifact SHAを検証。既存の32桁hex UUIDを保持し、新評価版・新assessment IDだけを`base/assessments/<label>/assessment.json`へ生成。原Run内の保存先は拒否 |
| `build_package` / `restore_package` | 明示的allowlistによるreport/data/code/REPRODUCEと相対path manifest。別フォルダー復元前にcampaign binding、全file hash/size、重複・大文字小文字alias・path traversal・drive path・symlink・file/directory衝突を検証。既存出力は上書きしない |

保存済み実験の`source_campaign_uuid`は呼出側が指定する実験識別子です。固定registryによる旧実験との対応をまだ検証していないため、frozen Runの結合metadataには`source_campaign_binding=caller_asserted_unverified`を記録します。原Run UUID・condition SHA・snapshot SHA・artifact SHAの検証と、旧実験をどのregistry UUIDへ対応づけるかの未確認状態を区別します。アダプター自身が作ったcampaign metadataへ結合する場合は`verified_local_campaign_metadata`です。既存のRun UUIDを作り直しません。再評価の評価出力は新assessment rootへ保存し、`outer.harness.evaluate.score_run`を原Runへ新評価器override付きで呼びません。実際の再評価runnerには、このmetadata bindingと別sandboxへの入力コピー・出力保存を接続する必要があります。

配布パッケージを検証するときは、信頼済みの別経路で得たZIP SHA256を`restore_package(..., expected_package_sha256=...)`へ渡してください。campaign UUIDとZIP内hashだけでは、manifestごと作り替えた配布物の出所を証明できません。復元アダプターはダウンロードしたコードを実行しません。

## 実行済みの有限受入試験

```powershell
python -B -X utf8 -m unittest research.tests.test_experiment_identity -v
```

7 test methodsは一時フォルダーだけで実行します。2 dummy campaigns・1 reassessmentで、同じRun labelでもUUID/root/output/public workspaceが分かれること、foreign/stale leaseとSTOP混線の拒否、partial原結果と再評価後処理faultを別保存して原Runの全file SHAが変わらないことを確認します。既存形式のhex UUIDを持つschema-2 frozen fixtureにも別保存再評価を結合します。

明示的に公開可能なtoy report/data/codeをZIP化し、別の匿名download相当フォルダーへ復元します。`code/recompute.py`をpackage外のworking directoryから実行し、toy `[2,3]`の結果`5`を確認します。改竄、manifestまで再hashした偽造の外部digest不一致、cross-campaign、traversal、symlink、重複・alias・path衝突は復元先作成前に拒否します。実際の匿名HTTP download・hosting・本番worker lease・process停止・200Run再評価・新モデル取得を実証する試験ではありません。

## 次取得前の統合ゲート

1. 新計画を固定し、新campaign genesisから割付を作る。旧v5 UUID生成・固定cohort path・v1〜v10 handoffを次実験へ流用しない。
2. dispatcher、resource supervisor、process ownership、STOP/ACK、journal、終了確認を新campaign UUID/root/generationへ結合する。foreign scope拒否と未知sendの停止・復旧を維持する。metadata leaseをOS/process fenceとして扱わない。
3. 評価器受入fixtureを合格させ、要求→check→oracle→実buildの対応を固定する。再評価runnerは入力コピー・新評価sandbox・新assessment outputのみを使い、元採点indexやadopted summaryへ書き込まない。
4. publication workspace・tag/asset名をcampaign UUID/評価版/package digestへ結合する。旧Releaseを置換せず、読者用[実験一覧](experiments.md)から固定report/data/code/reproduceへ辿れるようにする。
5. 新dispatcherを無モデルの有限2campaign試験に接続し、停止・partial・後処理fault・再開の境界、原本不変、正しい出力と未知状態を確認する。公開する正確なbytesについてprivate/secret/rights review後、実際の匿名download・別保存restore・再計算を確認する。

別リポジトリを作るだけでは、旧plan依存のUUID、絶対path、process fence、評価器の正しさ、公開物の対応は直りません。同じrepoを採用できる根拠はこの有限分離試験と将来の統合ゲートです。現在の旧driverを無変更で新campaignに使えるという主張ではありません。
