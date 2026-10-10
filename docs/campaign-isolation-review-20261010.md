# Campaign 初期化・証拠保全のローカル変更報告

対象は `fukuda-yuki/modernization-eval`（GitHub repository ID `R_kgDOUapanw`）、
remote は `https://github.com/fukuda-yuki/modernization-eval.git`。
基点は fetch した main `b81fc919360e6692c6de710b4d4fe8ed2547bc26`。
ブランチは `codex/campaign-isolation-20261010`。開始時の作業ツリーは clean。
隣の旧 `/workspace/sample2` は変更していない。push / Draft PR は未実施。

## 変更

- AGENTS/READMEで取得・評価・固定資材の検証機と定義し、現在の研究計画・コホート・分析・論文の正本を misc とした。旧文書・旧Skill・環境変数名を保持。
- `acquisition_pipeline init` を追加。明示planと、そのhashに結び付くユーザー承認receiptから、空ledger・ゼロusage・新時間原点・新pipeline UUID・独立rootを作る。genesisがconfig hashを固定し、resumeによる時間/予算のリセットを拒否。
- 件数とペア並列数は新planから取り、旧新100のresumeは既存値を保持する。既存Go endpoint/実行制約を維持し、新入口のモデルIDは承認planとprofileの一致を必須とした。旧callerのモデル固定は保持。新しいmodel/profile/科学条件は作っていない。
- 46番の個別除外receiptは旧resume用として保持。新campaignへは流用しない。取得済みの評価障害は保存物から回復し、品質による取り直しをしない。
- 既存manifest/receiptを最小拡張し、試行・materialize・dispatch・全試行資源・欠測を結合。完了attemptの資源加算は冪等。重複予約/採用は停止、unknown usage・欠測durationは明示保存する。
- 評価ID衝突/不正pathでは旧出力と新診断証拠を保持し、新結果を不採用として記録する。`rmtree`を除去。
- Linuxでtimeoutの子プロセス停止を確認できるよう、既存test helperのWindows専用tasklist/taskkill依存をOS別にした。判定規則は変更していない。

新100の100ペア/採用200・実モデル取得→評価→保存・pair14評価中のpair16取得・既存retry・
Release/proof gate除去は既実施の機能/実績であり、今回の新実装とは数えない。
個別回収、容量整理、旧Release削減を恒久自動機能へ拡張していない。

## miscとの契約照合

詳細は [初期化・producer契約](campaign-initialization.md)。join主キーは `run_instance_id`。
`run_id`はepochをまたぐretryで同じラベルになり得るため、独立Run数のキーにしない。

| 位置 | 追加フィールド | 必須・条件付き・未知の扱い |
| --- | --- | --- |
| 新config | `campaign_id`, `campaign_plan:{path,sha256}`, `campaign_approval:{path,sha256}`, `pair_count` | 新initでは必須。旧configへ遡及追記しない |
| genesis / epoch | `genesis.config:{path,sha256}` / `epoch.campaign_config:{path,sha256}` | 新campaignで必須。旧epochは保持 |
| materialized Run manifest | `acquisition:{slot,attempt,attempt_record,epoch,campaign_config}` | pipeline attempt記録が存在するときだけ追加。attemptは試行UUID、attempt_record/epochはpath+sha256。旧campaignのcampaign_configはnull可 |
| acquisition receipt | `runs[]` | 新たに保存するreceiptに全予約caseを含める。既存receiptの上書きなし |
| runs要素 | `run_instance_id`, `run_id`, `slot`, `task`, `condition`, `attempt`, `materialized` | 各要素で必須。未materializeでも予約UUID/課題/条件を保持 |
| runs要素 | `dispatch` | 既存pair journalのdispatch record、未記録ならnull。nullを確定無sendへ変換しない |
| runs要素 | `manifest:{path,sha256_at_acquisition}`, `missing_reason`, `usage` | 未materializeはmanifest/usage null、理由 `not_materialized`。materialize済みはmissing_reason null。manifest hashは取得checkpointの値で最終hashではない |
| runs.usage | `duration_seconds`, `raw`, `normalized`, `evaluations_index` | duration/normalizedは未知・未生成ならnull。rawは既存raw treeのhash map。indexは所在のみでhash保証ではない |
| acquisition.usage | `missing_duration_runs` | 追加。開始済みだがduration未観測のUUID一覧。`unknown_usage_requests`の欠測終端理由も保持。未知を0の確定観測へ変換しない |
| 採否/原判定/再評価/code-input-evaluator pins | 既存 `pipeline-evaluation.accepted/slot/attempt`, events, `evaluations/index.jsonl`のsequence、manifest/condition/epochのhash | 新しい判定コピーを作らず結合する。採用/未採用/評価未完了を区別。再評価はRun UUIDと資源を増やさない。最終引渡しは既存archive manifestで封印 |

今回の追加記録は私有引渡し用。public allowlistやRelease admission条件は変更していない。

misc `445c96e0956f77d8fcb3c0b43772e03578500a64` の受入契約との照合:

- 新cohort manifestの `source_repository` は上記remote、`source_commit == source_revision` はconfig/epochの取得コードcommit。producerは既に確定commitを持ち、unknownを生成しない。同値pinの重複はmisc manifestへの投影時に行う。
- `conditions` は承認plan.assignments、`evaluator_revision` はRun.conditionのevaluation versionとbuild/hashを根拠とする。非空文字列検査だけでは評価器pinの証明にならず、evaluator SHA・assets・評価出力member hashまで必要。`reproduction` と受入用 `files`/`external_sources` は既存packによる最終bytesの封印後にmiscで組み立てる。今回cohort manifest/ZIPの新しい大形式は作っていない。
- `attempt_key` はproducerの試行UUID `attempt`。数値のcase.attemptや繰返し可能なrun_idと混同しない。producer receiptのslotはpair番号、assignment.slotはpair内の腕位置。miscの `slot`/`pair_id` はこの意味を確認して投影する必要があり、無確認の改名は行っていない。
- `selected` は同じslot/attemptに結合する保存評価receiptのaccepted、`dispatched_by_started_at`/`started_at` はRun manifest由来。journal dispatchは別のintent/所有権証跡である。manifestがないRunの開始はnullを許し、dispatch未知を確定無sendと扱わない。
- 非採用理由は取得receiptの `reason`/fault/error、保存評価classification、または `evaluation_pending`/`not_materialized`/未確定コードから作る。成功/採用後の最終除外理由はnull。今回追加したacquisition.reasonは返却された実際の技術状態名を保持し、例外時は `acquisition_interrupted` とerrorを残す。後段の判定を先取りして採否を原manifestへ書かない。
- 原判定・再評価はRun UUID、condition/artifact/evaluator hash、評価member/sequenceへ結合。歴史的null evaluation_idを再生成しない。新しいcode ZIPは今回未作成なので、commit/ZIP comment一致の受入は未検証。
- AN004の新100固有件数/条件、旧DS001のunknown pin、旧dataset_id/stagesは変更しない。producerの独立campaign入口はAN004を呼ばない。


## 非モデル検証

試験はLinux / Python 3.14.7、既存隔離環境を使用。
実Chromium fixtureはローカルの合成webアプリだけを対象にし、研究Runを再採点していない。

## 未実行・残件

- [私有依存23 test ID / member / hash依存](private-evidence-test-dependencies.md)。旧v5 lease-chain、保存Run/browser/server、zero-send証拠が必要。取得した新100archiveの実manifestには識別memberがない。原memberの期待hashは未提供と明記し、生成して埋めていない。
- Windows固有の24 research / 1 outer試験はLinuxでは未実行。
- 新campaignの実モデル/実Docker運用受入は未実行。必要なのは実際の承認済み計画・対応固定資材・所有資源/STOP/回復を含むその計画の有限受入。既存新100の実機実績を未実施へ降格せず、今回の新入口の受入と区別する。
- .NET評価器の判定コードは変更していないため今回その校正suiteは再実行していない。評価出力衝突はstand-in評価器で検証。
- 新規モデル取得、課金API、認証変更、実研究データのscorer再実行、main merge、原本/旧判定削除、push/PRは実施していない。

## 検証結果とログdigest

| 実行 | 結果 |
| --- | --- |
| research全体（unittest discover） | 943件、896成功、47 skip、error/failure 0。skipは私有23 + Windows24 |
| outer全体（実Chromium fixture有効） | 266件、265成功、Win32長パス1 skip、error/failure 0。5つの実ブラウザー合成fixture成功 |
| campaign/pipeline/live pilot/owned completion/profileの重点回帰 | 43件、42成功、Windows1 skip |
| 最後の技術状態reason保存とreceiptの重点再検証 | 14件成功。全体回帰の後のこの小差分は該当試験を再実行し、全体をもう一度走らせたとは扱わない |
| 私有証拠依存の明示実行 | 39件、合成16成功、私有23 skip。旧保存証拠の代替判定はしない |
| その他 | CLI help、変更Pythonのcompile、git diff --check成功 |

ログは実行環境の `/tmp/` に保存。これらはローカル検証でありGitHub CI結果ではない。

| ログ | SHA256 |
| --- | --- |
| `/tmp/modernization-research-verified.log` | `3fbb990b3fe65b2e20b968a3650ec86e17eaa465812323c3f615999ed56f0646` |
| `/tmp/modernization-outer-verified.log` | `416f020353cbfb65a9049085d57be03300efbda37db33013a065e1a94a9eb3ca` |
| `/tmp/modernization-target-final.log` | `b01b9c761415b337748afeb371872056476ae5fc51c040818701f126cf103371` |
| `/tmp/modernization-receipt-final.log` | `a7d85f54224891a0681a63853ceda5baa0c4fb00eb74662b89117ae1773ceea8` |
| `/tmp/modernization-private-tests.log` | `859b5eeb7e3cfbfa8c4b6dde69401aa2914ff1da51fdf03a75dc89c7327794eb` |
