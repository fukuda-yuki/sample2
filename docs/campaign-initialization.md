# 新 campaign の初期化と producer 契約

研究計画・科学的割付・コホート・分析・論文は misc の正本を参照する。
この入口は既存Run部品による1条件または2条件の割付を扱い、条件・モデル・件数を提案しない。
旧新100の `initialize(repo, summary_path, root)` と既存 `run config.json` は保持する。
public Release は取得 admission の条件ではなく、解消済みの gate を追加しない。

## 初期化

```text
python -m research.acquisition_pipeline init /absolute/plan.json --approval /absolute/approval.json --repo /absolute/checkout
```

`research.campaign_initialization.FIELDS` の全項目を明示する。未知項目や旧 summary、
epoch、承認文言、UUID、累積 usage の持込みを拒否する。新しい科学計画のサンプル値は
提供しない。承認ファイルは `authorized: true`、`approved_by: "user"`、
`authorization_reference`（実際の指示への参照）、`campaign_id`、`plan_sha256` を必要とする。
これは既存のローカル承認 receipt と同じ信頼境界であり、ユーザーの電子署名認証ではない。
エージェントが承認を創作してよいという意味ではない。

| 計画項目 | 境界 |
| --- | --- |
| `kind`, `campaign_id`, `output_root` | 2条件は `approved_acquisition_campaign_v1`、1条件は `approved_single_condition_campaign_v1`。未使用の絶対保存先。source/protected root と祖先・子孫関係を持たない |
| `pair_count`, `pair_concurrency` | 正の明示件数、既存 engine の1または2ペア並列。評価 worker は既存の1本 |
| `assignments` | 1始まり連続 `pair` と kind に一致する数の `cases`。case は `task`, `condition`, `pair`, `slot`, `attempt`, `run_id`。2条件は同一task・異なる2条件。1条件は全割付で1つの条件名を使用し、各割付のslotは1。UUIDは各epochで新規生成 |
| `runtime_by_task`, `task_revision`, `settings` | 指定された既存profileとの一致。既存Go endpointと balance OFF・paid fallback OFF を保持。新入口だけが承認planのmodel IDを `profiles.resolve` へ渡し、指定profileとの一致を要求する。旧呼出しのDeepSeek固定は保持。新モデルprofileの作成・取得は行わず、万能providerへ拡張しない |
| `bounds` | `live_pilot.BOUNDS` の全キーと `max_pair_attempts`。全て正の整数。max_pairs/max_runs は件数と一致。run/provider秒はruntime profileと一致 |
| `protected_roots`, `runtime_locks`, `browser_pin`, `resource_monitor`, `resource_probe`, `thresholds` | 明示した保護先・path/hash付き固定資材。既存の資源監視・所有権・評価器bindingを維持 |

clean commit、承認hash、入力計画、固定資材の検証後に、空の accepted/attempted ledger、
ゼロusage、新しい時間原点・pipeline UUID と config、そのhashを固定するgenesis receiptを作る。初期化時にモデル・評価器を起動しない。
`run` は承認と genesis を再照合する。実送信には別途その計画の有効な実行指示が必要。
今回のコード修正の依頼は実送信許可ではない。

1条件でも既存の保存上の `pair_count` / `pair` / `max_pairs` / `max_pair_attempts` は
割付枠を数える。対照Runは生成しない。`max_runs = pair_count`、同時Run数は
`pair_concurrency`（同時割付枠数）となる。2条件の件数・保存形式は従来どおり。
単一条件のtemplate・観測phase・予約bindingには `cases_per_assignment: 1` を記録し、
再開時に幅の変更を拒否する。未送信・技術障害・低品質と全試行資源は既存receiptへ保持する。
`staged-explore` の追加入力は明示partitionと固定server/API経路を使用する。
要求分割・証跡・未受入の範囲は[固定CLIの能力確認](staged-input-capability.md)を参照する。

新 campaign では旧評価除外 receipt による再取得を許可しない。通常経路は技術障害だけを fresh UUID で
再試行し、取得できた生成物の評価障害は保存物の復旧へ送る。低品質は保持・採用され、品質に
基づく取り直しをしない。未知send/中断取得は資源回収を確認するまで停止する。

段階入力は1条件のkindだけで扱い、`staged_inputs` と `staged_retry` の両方を追加する。
`staged_inputs` は全taskのpartitionファイルへのpath/hash参照。元の最終要求、section全文、
初回/追加section ID、境界transportとsnapshot policyを固定し、workerへ渡すのは初回分だけ。
公開リポジトリへ実partition本文や承認receiptを追加しない。
`staged_retry` は `known_pre_dispatch_retries`（0または1）と `after_dispatch_retries`（0）の明示値。
known preparation failureのreceiptと送信不存在の証拠が揃わなければ、新UUIDも発行せず保留する。
成功・失敗・未到達を理由に送信後の取得を取り直さず、全試行資源を保持する。
追加入力の到達状態は `normalized.staged_input` にあり、初回到達と追加未到達を区別する。
この状態を集計するときは、未到達Runを分母から黙って落とさない。

## misc に渡す最小追加項目

新しい大きな保存形式は作らない。既存の config、Run manifest、acquisition/evaluation receipt、
pair journal、評価index、raw/normalized usage を組み合わせる。これらは私有証拠の引渡し契約で、
公開allowlistを広げない。単独の選択済みRun一覧だけでは全試行資源の根拠にならない。

| 意味 | 既存項目と追加箇所 |
| --- | --- |
| campaignと承認 | configに `campaign_id`, `campaign_plan`, `campaign_approval`, `pair_count`。epochにhash付き `campaign_config` |
| Run/slot/task/condition/attempt | Run manifest の `run_instance_id`, `assignment`。追加 `acquisition` が slot、試行UUID、attempt record/epoch/config参照を結合 |
| materialized/dispatch/欠測 | 既存 `pipeline-acquisition.json` に `runs` を追加。全予約caseを含め、manifest参照の有無・journal dispatch・`not_materialized` を分離 |
| 採用/不採用 | `pipeline-evaluation.json` の accepted、slot、attempt と events の accepted を結合。未評価は未採用、技術障害は acquisition の fault/error、評価除外は既存classification。未評価を品質不合格へ変換しない |
| 原判定/再評価 | Runの `evaluations/index.jsonl` と各record/outputのhash・sequence。元Run UUIDを維持して別sequenceへ記録。異なる評価器での再評価は既存別保存アダプターを使う |
| 全試行資源 | acquisition の usage は不採用試行も含む。追加 runs.usage はduration、raw tree hash、normalized参照、評価indexの所在。再評価は資源加算しない。完了attemptの再登録は同値なら冪等、差異なら停止 |
| コード・入力・評価器 | config/epochのsource_commit/source_pins、manifestのcondition/input/profile/assets/context/prompt hash、conditionのevaluator_build/sha、snapshot、評価recordを保持 |

`runs[].manifest.sha256_at_acquisition` や normalized 参照は取得保存時点のhashである。後段でmutable manifestが
更新されれば、最終archive manifestと区別して扱う。評価indexの所在はhash保証を意味しない。
引渡し時は既存pack/manifestで最終byte列を封印する。原判定や取得時snapshotを上書きしない。

評価IDは所有済み evaluations 配下の安全な単一名だけを受け付ける。衝突/不正ID時は
一時出力・stdout・browser/work証拠を削除せず、不採用record/indexを保存する。

## 検証の限界

合成fixtureは状態分離、fresh UUID retry、低品質保持、全試行usage、再開・重複防止、
承認/計画改変拒否を確認する。実Docker・モデル・私有評価器の新campaign受入は別工程。
旧保存データの再採点、旧記録の改変や新しい科学条件の承認は実施しない。
