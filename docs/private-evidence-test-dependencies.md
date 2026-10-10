# PR #26 の私有証拠依存23試験

基点 `b81fc919360e6692c6de710b4d4fe8ed2547bc26`。PR #26 は934 testcaseの
複数実行ログを照合して911成功/23 skipと報告している。単一全体実行やGitHub CIの成功ではない。
今回のLinuxで同じ私有依存23 IDを実行し、23 skipを確認した。別のWindows専用skipとは分離する。
DLLを追加するだけでは下記の保存証拠を代替できない。

## 確認した保管範囲とhash

2026-10-10に misc の `research-storage/transfer-catalog.json` と私有assetの
ZIP中央directory/`MANIFEST.json`をread-only取得し、278,131 memberを照合した。
ZIP全体の再download/hash照合、展開、scorer実行はしていない。

- catalog掲載 `sample2-analysis-private.zip` SHA256:
  `8b6e3bed59e53a1f3d6adb3e2b2d8992e53de0d4141980e1598b08aa75b0890b`
- 実際に取得した `MANIFEST.json` SHA256: `2bfb462dd71aedc2b13b25305d7478a5cf868951fb75b6f658ecbc6b24fe98d4`
- 下記L/A/Zの識別member（phase8/9、boundary、handoff-v8、保存5067/5053、zero-send precheck、failed-recovery closeout）は全て未収載。
- ローカルにも `v5-go30m`、`evaluator-repair-evidence-20261006` はない。
  catalogは新100/第1回と固定runtimeの派生保存であり、旧v5全保存証拠の存在を保証しない。

各memberの期待SHAは、それぞれの未提供原本manifest/phaseのhash参照から取得する必要がある。
**未収載memberのhashは不明**。新100のmember hash、秘匿後の派生hash、新生成fixtureのhashで
埋めない。以下のパスは原保存rootからの相対member指定であり、旧ホスト絶対パスを公開しない。
復元時は先に別経路の原archive digestとmember manifestを受領・照合する。

## 依存member集合

| 集合 | 必要な私有archive memberとhashの結合 | 観測目的 |
| --- | --- | --- |
| L | `v5-go30m/artifacts/main-central-wave-v8-fixed-20261005/phase.json`、`artifacts/v8-lease-start-recovery-20261005/actual-empty-v8-boundary.json`、phase.batchの`_control/phase-handoff.json`と`phase-handoff-v2.json`〜`v8.json`。phaseのpredecessor参照をv3まで辿るphaseとresource_collector_acceptance。各期待hashは旧phase/handoff参照（未提供） | 実v8 lease所有者、連鎖完全性、無send境界、独立監視/公開metadataの来歴 |
| V10 | Lに加え`artifacts/main-central-wave-v9-fixed-20261005/phase.json`と、そのbatchの`_control/<phase_id>/wave-journal.jsonl`。期待hashは保存phase/handoff参照（未提供） | v10所有者、v9実journalを欠測として消さず公開metadataへ結合 |
| A | `v5-go30m/runs/source-info-v5-100p2/MS1-CONT-B-preload-5067/`と`CU1-ENR-D-preload-5053/`のmanifest、condition、snapshot、implementation/postprocess receipt、usage/raw、frozen tree、evaluations/indexとsequence 1 directory一式（evaluation/record、browser-intent、browser-server.log、cleanup、browser-school request/collector receipt等）。契約試験は`artifacts/main-go30m-current-fixed-20261004/bundle.json`とphase9も必要。hashは各snapshot/raw/record/intentの原参照（未提供） | 元判定/null/partial保持、owned Run・実request・例外・生成ソース・stop/cleanupの対応。再採点しない |
| Z1 | `evaluator-repair-evidence-20261006/failed-recovery-observer-startup-sealed-v1/closeout.json`とcloseout.inventory/plan/停止証跡が参照する全member。期待hashはcloseout内参照と原inventory（未提供） | zero-send prior closeout、unknown送信やtamper拒否、原本不変 |
| Z2 | `education-independent-trial-zero-send-precheck-v1/result.json`、`repaired-live-pilot-preparation-v1/fixed-plan.json`、`recovery-live-pilot-preparation-v1/fixed-plan.json`、`finite-pilot-bounded-stop-sealed-v1/closeout.json`、`failed-repaired-pilot-sealed-v1/closeout.json`、Z1と各参照先のmanifest/input/raw/native/ACK/inventory。期待hashは保存参照（未提供） | 実準備済みzero-send、元入力bytes、実送信2Run・native session・ACKのread-only照合 |

## test ID と観測目的

全IDは `research.tests.` から始まる。各行の期待hash/不足状態は上の集合に対応する。

| test ID | 依存 | 試験の観測目的 |
| --- | --- | --- |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_actual67_and_saved_school_evidence_no_gate_adoption.test_actual67_and_saved_school_evidence_no_gate_adoption` | A | actual67 and saved school evidence no gate adoption |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_changed_first_attempt_or_original_result_rejected.test_changed_first_attempt_or_original_result_rejected` | A | changed first attempt or original result rejected |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_contract_fault_set_handler_and_typed_gate_boundaries.test_contract_fault_set_handler_and_typed_gate_boundaries` | A | contract fault set handler and typed gate boundaries |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_http500_without_app_exception_or_source_or_request_rejected.test_http500_without_app_exception_or_source_or_request_rejected` | A | http500 without app exception or source or request rejected |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_music_mixed_exception_and_interleaved_request_rejected.test_music_mixed_exception_and_interleaved_request_rejected` | A | music mixed exception and interleaved request rejected |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_no_policy_or_other_fault_never_exempted.test_no_policy_or_other_fault_never_exempted` | A | no policy or other fault never exempted |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_school_mixed_fault_spec_other_view_or_foreign_attempt_rejected.test_school_mixed_fault_spec_other_view_or_foreign_attempt_rejected` | A | school mixed fault spec other view or foreign attempt rejected |
| `research.tests.test_app_failure_preservation.AppFailureTests.test_wrong_owned_identity_endpoint_and_cleanup_rejected.test_wrong_owned_identity_endpoint_and_cleanup_rejected` | A | wrong owned identity endpoint and cleanup rejected |
| `research.tests.test_lease_chain.LeaseTests.test_actual_saved_v8_chain_accepts_only8.test_actual_saved_v8_chain_accepts_only8` | L | actual saved v8 chain accepts only8 |
| `research.tests.test_lease_chain.LeaseTests.test_changed_hash_path_kind_rejected.test_changed_hash_path_kind_rejected` | L | changed hash path kind rejected |
| `research.tests.test_lease_chain.LeaseTests.test_competing_process_rejected_then_release_reacquired.test_competing_process_rejected_then_release_reacquired` | L | competing process rejected then release reacquired |
| `research.tests.test_lease_chain.LeaseTests.test_missing_intermediate_rejected.test_missing_intermediate_rejected` | L | missing intermediate rejected |
| `research.tests.test_lease_chain.LeaseTests.test_unsupported_successor_rejected.test_unsupported_successor_rejected` | L | unsupported successor rejected |
| `research.tests.test_lease_chain.LeaseTests.test_v9_absence_guard_rejects_existing_even_empty_journal.test_v9_absence_guard_rejects_existing_even_empty_journal` | L | v9 absence guard rejects existing even empty journal |
| `research.tests.test_lease_chain.LeaseTests.test_v9_campaign_chooses_independent_process_and_own_warmup.test_v9_campaign_chooses_independent_process_and_own_warmup` | L | v9 campaign chooses independent process and own warmup |
| `research.tests.test_lease_chain.LeaseTests.test_v9_only_after_handoff_and_old_markers_unchanged.test_v9_only_after_handoff_and_old_markers_unchanged` | L | v9 only after handoff and old markers unchanged |
| `research.tests.test_lease_chain.LeaseTests.test_v9_publication_uses_real_v3_ancestor_and_discloses_absence.test_v9_publication_uses_real_v3_ancestor_and_discloses_absence` | L | v9 publication uses real v3 ancestor and discloses absence |
| `research.tests.test_v10_successor.V10Tests.test_v10_campaign_uses_independent_monitor.test_v10_campaign_uses_independent_monitor` | L + V10 | v10 campaign uses independent monitor |
| `research.tests.test_v10_successor.V10Tests.test_v10_missing_intermediate_or_changed_binding_rejected.test_v10_missing_intermediate_or_changed_binding_rejected` | L + V10 | v10 missing intermediate or changed binding rejected |
| `research.tests.test_v10_successor.V10Tests.test_v10_only_owner_after_exact_handoff.test_v10_only_owner_after_exact_handoff` | L + V10 | v10 only owner after exact handoff |
| `research.tests.test_v10_successor.V10Tests.test_v10_publication_retains_real_v9_journal.test_v10_publication_retains_real_v9_journal` | L + V10 | v10 publication retains real v9 journal |
| `research.tests.test_education_readiness_trial.ActualSealedSources.test_actual_prepared_zero_send_original_bytes_inputs_and_ack_readonly.test_actual_prepared_zero_send_original_bytes_inputs_and_ack_readonly` | Z2 | actual prepared zero send original bytes inputs and ack readonly |
| `research.tests.test_readiness_recovery.RecoveryControls.test_actual_zero_send_prior_closeout_and_unknown_sent_tamper_reject.test_actual_zero_send_prior_closeout_and_unknown_sent_tamper_reject` | Z1 | actual zero send prior closeout and unknown sent tamper reject |

## 安全なfixtureで実施できる範囲

同じ実行の残り16試験は recovery の合成fixtureで成功した。別途、campaign初期化と
既存pipelineの合成fixtureで、承認/状態分離・retry UUID・低品質保持・全試行資源・保存後復旧を
確認した。これを欠けた旧証拠23件の合格へ振り替えない。元データの再生成・旧判定変更はしない。

保管資料の追加受領が必要なのは上の具体的member群と原archive/member hashである。
旧ホストに依存する絶対path参照を復元する方法も、原byte列を変更しない読取りアダプターまたは
適切な隔離環境で別途確認する。新campaignの実装・合成回帰はこの未提供資料に依存しない。
