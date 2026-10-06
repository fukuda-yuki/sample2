# 評価器修正の公開投影と再計算

`research/evaluator_publication.py` は保存assessmentの公開可能な最小投影と、
公開JSONだけからの報告値再計算を担当する。標準ライブラリだけを使い、provider・
評価器・browser・Docker・Gitを呼ばない。原100ペアの公開物を置き換えない。

現行readerはschema2である。schema1の凍結sourceは
`research/public_readers/evaluator_publication_schema1.py`へbyte一致で保存した
（SHA `636bbef89e836db6b75d590168082530f4e3f062a54506535b10c4e2e0ce5f28`）。
旧7assessment rowとそのcanonical SHAは変更しない。

入力は明示したassessment root、固定validation receipt SHA、事前計画である。
`normalize_assessment`は固定validation digestとassessment全体のbyte inventory、保存出力・baseline両hashを照合し、UUID、親Run UUID、
artifact/spec/DLL SHA、計画commitの宣言、台帳IDと判定ラベル、coarse確認だけを出力する。
DB、private oracle、要求入力値、観測本文、生ログ、画像、評価器binary、ホストpathは
出力しない。source campaign registry UUIDは未検証なのでnullを維持する。

既存7件は5種類の保存生成物へ結合した7つの評価実行である。後から実行した評価版は
新assessmentを追加し、既存行を書き換えない。validation IDは採用ゲートの別検証で
あり、評価実行や新取得を増やさない。非モデル運用の2campaign・4dummy Run・1assessment
は別の種類として記録し、研究サンプルへ加算しない。

`derive`は実公開行の要求・check inventory、版、来歴、coarse確認を検証する。
現行の両評価器と同じ等重みの要求品質をcompleteに限って再計算し、critical failureを
別に判定する。severityを数値weightへ変換しない。partial・faultはquality nullを
維持する。bound reported failureと未観測scope・cascade warningは別fieldに残し、
すべてのraw failを独立に確認した製品不良へ変換しない。criticalの報告failラベルと
未観測ラベルも別配列で再計算する。

`observation_scopes`はassessment IDに結合した別の公開sidecarである。checkの
`unknownObservations` / `observationFaults`とoutputの未観測・障害markerをcoarse
booleanへ投影する。private本文は出力しない。Failと未知・障害scopeが同時に存在しても
未知scopeを消さず、complete qualityへ昇格させない。旧7公開rowのbytesとSHAは維持する。
sealed packageには全assessmentのscope sidecarが必須である。

## Sealと公開後gate

`seal_package`はoperatorが固定した次のpolicyを要求する。

```text
package_id
expected_assessment_ids          # 実行済み全件の正確な集合
expected_assessment_versions     # assessment ID -> 正確な評価版
required_history_assessment_ids  # 保全する原7assessment、重複なし
required_history_row_sha256      # 原7公開行のcanonical JSON SHA
required_evaluation_versions     # 新分類revisionを含む必須版
required_phase                  # prepublication / final
expected_unvalidated_attempt_ids # 旧HTTP-only 4 UUIDの正確な集合
required_unvalidated_attempt_row_sha256 # 保全する旧4公開行のcanonical SHA
expected_attempt_followups       # 旧HTTP-only UUID -> 指定する直接followup UUID
```

新revisionの評価が未完了、operational receiptが未提供、IDの欠測・余分・衝突がある
場合はsealしない。prepublication版Aは公開gate未完了をそのまま示す。rootがAを実際に
公開・匿名取得・再計算した証跡をproduction journalへ結合してから、別のfinal版Bを
作る。BはAのpackage/verification SHAと4Runの実publication gate完了を要求する。
Aを上書きせず、自分自身のpackage digestを自己証明へ使う循環を作らない。

packageにはINDEX、report、最小data、derived results、reader、README、NOTICE、
相対pathのmanifestを含める。追加コードもoperatorの明示allowlistだけを使う。
公開review前にstaging全体を自動収集したり、private入力設定をZIPへ入れない。
NOTICEは原repoや第三者素材への包括的licenseを作るものではない。

## 未検証試行を分けるschema2

main dataは固定relative path `data/assessment-attempts.json`とそのSHAを
`attempts_reference`へ持つ。sidecarは別typeのHTTP-only 4試行を保全する。
UUID、源Run/生成物/spec/DLL/版/計画commitの結合と、raw result・HTTP output・check rowsの
SHAを保持する。validation IDはnull、validatedはfalse、qualityはnullのままである。
HTTP診断の判定countsやunknown/fault boolを、採用済み品質へ変換しない。

`normalize_unvalidated_attempt`のbyte binding照合は公開投影の入力適格性確認であり、
独立validation receiptの作成や採用成功を意味しない。source unchanged/cleanupは
旧実行receiptからのcoarse確認として扱う。旧4件の原本を書き換えない。

`derive(data, attempts=sidecar)`と`seal_package(..., attempts=sidecar)`は明示的に両fileを扱う。
`attempt_followups`は旧HTTP-only UUIDから直接followup UUIDへの明示mapであり、policyと一致させる。
旧試行はmainの指定するちょうど1件の1.6評価へ同じ源Run UUID・artifact・spec・DLLで結合する。
followupという関係からvalidation成功や品質採用を推定しない。同じ源生成物の追加collector修復評価も
別UUIDのmain行として保全する。版と源Runだけで複数行のどれかを自動選択しない。
main/validation UUIDとの衝突、旧4行の改変、missing sidecar、品質昇格、異なる源生成物を拒否する。
新4件と実運用receiptが揃う前にはsealしない。

報告用assessment行N、未検証HTTP-only試行4、保存再評価の全試行N+4、源生成物のunique数を
別の指標として実行済みIDから再計算する。現在の計画は原7行とcontroller/collector修復の各4行を
保全する計15行・19試行・源7 uniqueであり、実証が揃う前に完了とは呼ばない。
Nは全件の数値品質採用を意味しない。complete/partialと品質はmain行からのみ
再計算する。非モデル運用の4dummy Run/1assessmentは15や源7へ加算しない。
recompute receiptにも報告行数・全試行数・未検証試行数を別fieldで保存する。

## 読者の再計算

専用Releaseの正確なZIPを別フォルダーへ展開し、Release本文で固定したMANIFESTの
SHA256を使う。Windows CPython 3.14.4、標準ライブラリのみ。

```powershell
python -B -X utf8 <展開先>/code/evaluator_publication.py reproduce `
  --package <展開先> --expected-manifest-sha256 <Release本文のSHA256> `
  --out <未作成の別フォルダー>
```

readerは全manifestファイルのsize/SHAと完全inventory、ID、seal phaseを検証してから、
実公開行を再計算する。`results/summary.json`とのbyte一致、終了0、新出力のreceiptが
揃った場合のみ成功。改竄、未列挙ファイル、unsafe path、出力再利用、未知quality method、
partial品質の昇格を拒否する。packageと異なるworking directoryでも実行できる。

これは派生報告値の公開再計算であり、private oracleを使ったfull scoring replayや
品質意味の独立再監査、将来の無故障、本格100再取得の開始可を保証しない。
実公開・匿名downloadの操作と証跡はrootが担当し、ローカルstagingだけで成功を称しない。
