# Source Information v5：原100ペア・200実行の最終分析

全割付について「要求品質を維持してRun全体tokenを削減した」とは結論できない。全要求pass率差の識別範囲は−50〜＋50ポイント、Run全体token差は10件の欠測と正当化された有限上限の不在により点識別されない。完全使用量93ペアではpreload−exploreのvariant等重み合計token平均差が−280,283.33だが、両方全要求passは36ペアで、そのうちusageも完全な35ペアをpoolすると＋218,599.49になる。これは選択条件を変えた記述結果であり、改善・品質維持・因果機序の合格判定ではない。差がないことの証明でもない。

## 実取得と証拠の結合

最終取得終了監査時刻は `2026-10-05T23:52:06.819442+00:00`。原100ペア・200UUIDの実送信、停止・提出固定、原seq1、200アーカイブと依存ファイル、100公開readback／匿名全SHA復元／offline抽出／所有cleanupゲートを照合した。制御tool1792の実EXIT0、開始された全3observerのscope/shutdown ACK、明示的に成功したCIM不在照会count0、対象2labelの稼働Docker container0を確認した。停止済みcontainerや保持fileまで不存在とは主張しない。

| 区分 | 内訳 |
| --- | --- |
| 実行 | completed163、operator_stop33、provider_failure3、timeout1 |
| 取得未送信／未完了 | 0／0（採点完全性とは別） |
| 原初回採点 | scored131、evaluation_incomplete67、evaluator_fault2 |
| 原数値quality | 131件観測、69件null |
| Run全体usage | 190完全、10欠測（explore6／preload4） |
| 原raw verdict | pass98、fail6、fail_critical96。sentinelや評価不備を製品失敗へ自動変換しない |
| 応答モデルmetadata | 全200でdeepseek-v4.1-flash、予期しないID0。provider内部識別の証明ではない |

取得branchは `codex/wave-publication-adapter-20261004`、HEADは `bb720727790c9740c4595b0d71820e9c6a106bda`。原bundle SHA256は `f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334`、最終completion SHA256は `d887d371b4c377d864297f1fd1256429b6d85c381451fcd7a166d58b26e5d9f2`、公開dataset SHA256は `8a74ffc4bf90b38297a7668eabe91befa572215c9facdf20c814e617efa125f3`。全100公開catalog SHA256は `70913a0d01ff77ddacc236200955ff26961968cd4548c733b5a73ab4ab37f816`。コード／公開inventoryのSHAとReleaseの独立tagで後段公開を結び付ける。履歴の統合はmerge --no-ffで行い、原本・旧評価・凍結版を上書きしていない。

保存stream faultでは送信済み実行を再送せず、停止済み生成物を処理した。status fault後のoriginal90/91は未送信だった同じ4UUIDについて、旧制御の実終了・保持STOP・新独立observerの実healthy handoff後に開始した。古いSTOPのHTTP fence未確認／falseは保持され、その後の物理終了確認と分けている。Windows共有違反のfixtureは歴史的status faultの根本原因を証明しない。故障・早期停止・未採用・partial usageを成功へ書き換えていない。

## 目的・設計・主要指標

目的は初期source情報提示と、要求品質／Run全体provider input/output tokenの関係を調べること。金銭的費用は目的へ置き換えない。2つの固定source family、4つの固定意味variant、各25ペア、arm各100Runを維持する。100種類の独立アプリケーションでもHTTP呼び出し数分の独立実験でもない。OpenCode Go既存ユーザーキーをgatewayで用い、値を表示・記録・共有していない。モデルは指定のDeepSeek V4.1 Flash、Run1800秒／request600秒の固定条件。研究Skill／AGENTSは管理側のみでworkerへコピー・マウントしていない。

固定主要指標は2つ：全割付の全要求移行pass率差と、Run当たりprovider input＋output平均差。差はpreload−explore、variant各0.25、次いでfamily等重み。input＋outputは一度だけ加え、cache input／reasoning outputを再加算しない。critical failure、input/output単独、原数値qualityは追加ビュー。joint success flag、事後の非劣性margin、都合のよいsubsetによる主指標の置換は行わない。

### 品質：三値判断と原判定を分ける

| arm | 全要求pass | 確認違反でfullpass0 | unknown | pass率の識別範囲 |
| --- | --- | --- | --- | --- |
| explore | 50 | 2 | 48 | [50.00, 98.00]% |
| preload | 48 | 0 | 52 | [48.00, 100.00]% |

全割付pass率差の範囲は[−50,＋50]ポイント。これは未確定100件の三値割当による識別範囲であり、95%信頼区間ではない。確認critical violationはexplore1、preload0、critical未知は45／50で、差の範囲は[−46,＋49]ポイント。完全な全割付binary点推定がないためIID Hoeffding区間はnull。98passは原seq1と有限の保存coverageに基づく自動判断であり、全必須checkの独立意味監査や無制限の実務品質保証ではない。

4500必須checkを原UUID／seq1／spec／results／coverageへ結び付けた。内訳は自動保存coverageによるpass3234、独立意味未監査1259、限定手動監査による確認違反4、限定監査未解決3。後二者は目的抽出した7check・4Runのみ。違反check4は2Runに属し、4独立Runや全体欠陥率には変換しない。全4500の意味妥当性を独立に監査したとは主張しない。監査対象は盲検・対称な欠陥監査ではなく、確認不合格2対0からarmの優劣を言えない。

| 原数値quality（追加・観測条件付き） | 観測／欠測 | 平均 | 中央値 |
| --- | --- | --- | --- |
| explore | 66/34 | 94.91 | 100.00 |
| preload | 65/35 | 93.87 | 100 |

数値qualityの平均は採点できた65／66件に条件付く。69nullを0にせず、異なる評価完全性・check意味・variant構成を持つ平均から品質維持を認定しない。この表はpublic-datasetのoriginal_numeric_qualityをarm別にnull除外してstatistics.mean／medianした追加記述であり、14結果のbyte再計算対象とは別である。

### token：全割付と完全使用量を分ける

| 指標 | 全割付平均差 | 完全93ペアvariant等重み平均差 | ICC0仮定のnormal95%区間 |
| --- | --- | --- | --- |
| input_tokens | 未識別 | -277,960.29 | [-669,998.27, 114,077.69] |
| output_tokens | 未識別 | -2,323.04 | [-5,598.47, 952.39] |
| total_tokens | 未識別 | -280,283.33 | [-674,406.52, 113,839.86] |

完全93ペアはA23／B22／C23／D25。合計差のICC0.1／0.3仮定区間もそれぞれ[−729,652.91,169,086.25]／[−823,544.66,262,978.00]で0を跨ぐ。ICCは測定値ではなく1＋3ρの仮定感度。計画4pair sessionで25clusterのCR1 normal区間は[−709,542.47,148,975.81]、実waveで50clusterは[−638,316.59,77,749.92]。独立cluster・normal近似の仮定、選択とcluster間provider／日時依存が残る。これらは全割付効果の区間ではない。

不完全usage10件の全Run tokenはnullとし、観測partialを別欄に残した。一意・累積・全call包含を独立に証明しないpartialは正式下限と呼ばない。wallclockや単発context上限を全Run token上限へ転換しない。以下は各arm／variantの完全Run平均へ0.5／1／2倍を欠測代入する全9交差条件×3指標。全条件が利用可能、clampなし、データから識別された値ではない。合計の仮定差は−737,391.49〜−60,729.15と全9条件で負だが、仮定集合の外の欠測真値を制約しない。output単独には正の条件もある。

| 指標 | explore欠測倍率 | preload欠測倍率 | variant等重み仮定差 |
| --- | --- | --- | --- |
| input_tokens | 0.5 | 0.5 | -298,321.76 |
| input_tokens | 0.5 | 1.0 | -219,372.55 |
| input_tokens | 0.5 | 2.0 | -61,474.14 |
| input_tokens | 1.0 | 0.5 | -442,323.99 |
| input_tokens | 1.0 | 1.0 | -363,374.78 |
| input_tokens | 1.0 | 2.0 | -205,476.37 |
| input_tokens | 2.0 | 0.5 | -730,328.45 |
| input_tokens | 2.0 | 1.0 | -651,379.25 |
| input_tokens | 2.0 | 2.0 | -493,480.83 |
| output_tokens | 0.5 | 0.5 | -2,172.23 |
| output_tokens | 0.5 | 1.0 | -1,199.83 |
| output_tokens | 0.5 | 2.0 | 744.98 |
| output_tokens | 1.0 | 0.5 | -3,802.50 |
| output_tokens | 1.0 | 1.0 | -2,830.10 |
| output_tokens | 1.0 | 2.0 | -885.29 |
| output_tokens | 2.0 | 0.5 | -7,063.04 |
| output_tokens | 2.0 | 1.0 | -6,090.64 |
| output_tokens | 2.0 | 2.0 | -4,145.82 |
| total_tokens | 0.5 | 0.5 | -300,493.99 |
| total_tokens | 0.5 | 1.0 | -220,572.38 |
| total_tokens | 0.5 | 2.0 | -60,729.15 |
| total_tokens | 1.0 | 0.5 | -446,126.49 |
| total_tokens | 1.0 | 1.0 | -366,204.88 |
| total_tokens | 1.0 | 2.0 | -206,361.65 |
| total_tokens | 2.0 | 0.5 | -737,391.49 |
| total_tokens | 2.0 | 1.0 | -657,469.88 |
| total_tokens | 2.0 | 2.0 | -497,626.66 |

## 題材・尺度・選択条件を変えた全ビュー

| variant | 品質差bounds（pp） | 完全ペアn | 合計平均差 | 合計中央値差 | 両pass完全n／平均差 |
| --- | --- | --- | --- | --- | --- |
| MS1-CONT-A | [-16.00, 16.00] | 23 | -107,768.78 | 45406 | 17 / 387,094.47 |
| MS1-CONT-B | [-28.00, 28.00] | 22 | -92,536.32 | 20,049.50 | 16 / -3346 |
| CU1-ENR-C | [-72.00, 72.00] | 23 | -333,312.35 | -911094 | 2 / 561956 |
| CU1-ENR-D | [-84.00, 84.00] | 25 | -587,515.88 | -437600 | 0 / null |

| 固定family | 割付ペア | 品質差bounds（pp） | 完全pair等variant合計差 | 両pass等variant合計差 |
| --- | --- | --- | --- | --- |
| contoso-enrollment | 50 | [-78.00, 78.00] | -460,414.11 | null |
| music-store-continuity | 50 | [-22.00, 22.00] | -100,152.55 | 191,874.24 |

Musicでは平均が負でもA/Bの中央値差は正、幾何比は1.019／1.046。Contosoの完全pair平均はより負だが品質未知が多く、Dの両passペアは0。全variant等重み両pass差はnullのまま。35完全成功pairのpool平均＋218,599.49はMusic33／C2／D0という別の対象構成であり、全割付主要結果とは比較条件が異なる。

| 全7選択集合（事後条件） | 含有ペア | 完全tokenペア | pool合計平均差 |
| --- | --- | --- | --- |
| both_implementations_completed | 79 | 79 | -302,471.39 |
| both_original_scored | 55 | 54 | -199,660.17 |
| both_original_research_coverage_complete | 55 | 54 | -199,660.17 |
| both_usage_complete | 93 | 93 | -288,909.27 |
| both_derived_full_pass | 36 | 35 | 218,599.49 |
| any_execution_failure | 21 | 14 | -212,380.14 |
| any_derived_quality_unknown | 63 | 57 | -553,851.25 |

両実装正常集合79pairでも負の平均差は残るため、全平均差を早期停止だけが説明すると断定できない。一方、品質未知を含む集合の負の差と、成功集合の正の差は、品質・測定・選択による別の説明を残す。post-assignment選択を介入効果へ読み替えず、空集合もnullとして公表する。

| 探索的頑健化（完全pair内） | trim平均差 | winsor平均差 |
| --- | --- | --- |
| 0%/tail | -280,283.33 | -280,283.33 |
| 5.0%/tail | -271,825.29 | -260,870.12 |
| 10.0%/tail | -285,194.94 | -272,314.41 |

93個の全leave-one-complete-pair条件による中心範囲は -330,912.11〜-224,999.97。1ペアの除外だけで符号は変わらないが、全割付欠測や品質を解決しない。正のtokenを持つ93ペアの等variant平均log比からの幾何比は0.93（精密値はexploratory JSON）。ゼロ分母／preload0は今回は0件、欠測7pairは別扱い。尺度を変えた比は算術平均差と別の推定対象。全input/outputにも同じ影響・比・trim条件を公開した。

| 全variant／family除外条件 | 残る割付ペア | 品質差bounds（pp） | 全割付合計差 |
| --- | --- | --- | --- |
| omit_variant_MS1-CONT-A | 75 | [-61.33, 61.33] | null |
| omit_variant_MS1-CONT-B | 75 | [-57.33, 57.33] | null |
| omit_variant_CU1-ENR-C | 75 | [-42.67, 42.67] | null |
| omit_variant_CU1-ENR-D | 75 | [-38.67, 38.67] | null |
| omit_family_contoso-enrollment | 50 | [-22.00, 22.00] | null |
| omit_family_music-store-continuity | 50 | [-78.00, 78.00] | null |

除外6条件の全割付token点推定はすべてnull。対象を変更しても未観測を復元したことにはならない。

### 順序・日時・実装条件・重なり

| 最初に割付されたarm | 割付ペア | 完全ペア | pool合計差 |
| --- | --- | --- | --- |
| explore_first | 50 | 45 | -443,834.13 |
| preload_first | 50 | 48 | -143,667.21 |

両順序各50pairで差の大きさは異なる。割付順序は実HTTP開始順序やcache因果効果の証明ではない。source/task/scoring/research/execution/実evaluator SHA別の分布と全check raw判定×導出状態はsupplementary JSON、25計画sessionを含む全層はdescriptive-strata JSONに残した。以下のpool集計はvariant混合が異なり、主要等重み比較とは区別する。

#### acquisition_phase

| 層 | 割付Run | 利用可能ペア | 完全tokenペア | pool合計差 |
| --- | --- | --- | --- | --- |
| central-wave-pair12-100-v2 | 4 | 2 | 2 | 22839 |
| central-wave-pair14-100-v3 | 8 | 4 | 2 | -1239980 |
| central-wave-pair18-100-v4 | 8 | 4 | 3 | -1,476,225.33 |
| central-wave-pair22-100-v5 | 56 | 28 | 28 | 80,671.82 |
| central-wave-pair50-100-v6 | 8 | 4 | 3 | -884,237.67 |
| central-wave-pair54-100-v7 | 8 | 4 | 4 | 52,223.25 |
| central-wave-pair58-100-v9 | 20 | 10 | 9 | -354,970.67 |
| central-wave-pair6-100-v1 | 12 | 6 | 6 | -555,585.67 |
| central-wave-pair68-100-v10 | 66 | 33 | 31 | -408,235.16 |
| historic-first-five-two-Run-pairs | 10 | 5 | 5 | -127411 |

#### run_concurrency_cap

| 層 | 割付Run | 利用可能ペア | 完全tokenペア | pool合計差 |
| --- | --- | --- | --- | --- |
| 2 | 12 | 6 | 6 | -352,626.50 |
| 4 | 180 | 90 | 83 | -252,902.71 |
| 8 | 8 | 4 | 4 | -940,469.50 |

#### assigned_order_quartile

| 層 | 割付Run | 利用可能ペア | 完全tokenペア | pool合計差 |
| --- | --- | --- | --- | --- |
| 1 | 50 | 25 | 22 | -367,610.86 |
| 2 | 50 | 25 | 25 | -27,258.20 |
| 3 | 50 | 25 | 23 | -378,819.57 |
| 4 | 50 | 25 | 23 | -408,122.52 |

#### start_date_utc

| 層 | 割付Run | 利用可能ペア | 完全tokenペア | pool合計差 |
| --- | --- | --- | --- | --- |
| 2026-10-04 | 102 | 51 | 48 | -234,199.04 |
| 2026-10-05 | 98 | 49 | 45 | -347,266.84 |

#### analysis_session

| 層 | 割付Run | 利用可能ペア | 完全tokenペア | pool合計差 |
| --- | --- | --- | --- | --- |
| 1 | 8 | 4 | 4 | -364,530.50 |
| 10 | 8 | 4 | 4 | 1010568 |
| 11 | 8 | 4 | 4 | -560,147.25 |
| 12 | 8 | 4 | 4 | -260592 |
| 13 | 8 | 4 | 3 | -1,349,979.33 |
| 14 | 8 | 4 | 4 | -10,756.75 |
| 15 | 8 | 4 | 4 | -300973 |
| 16 | 8 | 4 | 4 | -661,650.75 |
| 17 | 8 | 4 | 3 | 103,793.67 |
| 18 | 8 | 4 | 4 | 643036 |
| 19 | 8 | 4 | 4 | -1533674 |
| 2 | 8 | 4 | 4 | 388,339.50 |
| 20 | 8 | 4 | 4 | -1,206,789.25 |
| 21 | 8 | 4 | 4 | 2,108,953.75 |
| 22 | 8 | 4 | 2 | 552,658.50 |
| 23 | 8 | 4 | 4 | -2,201,182.50 |
| 24 | 8 | 4 | 4 | -892,417.25 |
| 25 | 8 | 4 | 4 | -205,472.75 |
| 3 | 8 | 4 | 4 | -1,016,383.25 |
| 4 | 8 | 4 | 3 | -811518 |
| 5 | 8 | 4 | 2 | -2286862 |
| 6 | 8 | 4 | 4 | 700368 |
| 7 | 8 | 4 | 4 | 1258837 |
| 8 | 8 | 4 | 4 | 239129 |
| 9 | 8 | 4 | 4 | -1441423 |

cap2／4／8のRun数は12／180／8で、単一運用regimeではない。実装manifest interval重なりの最大は8、348segments。これは瞬間的な同時provider request・CPU稼働の観測ではない。phase、cap、順序、日時、停止、評価buildが交絡し、phase/cap効果は識別されない。開始はUTC2026-10-04に102Run、10-05に98Run。実evaluator build SHAは3種類（Music100、Education旧6／診断94）、凍結worker設定は4種類。versionラベルだけで同等性を判断していない。

Run durationは各arm98観測／2欠測で、explore中央値814.12秒、preload752.27秒。短い生成・shared stopは効率改善の根拠にならない。normalized observed_request_countの平均は60.52／52.45で、独立Run数を増やさない。この定義をgateway raw要求開始／終了11307と同一数とみなさない。cache-read平均は完全usageのexplore4,025,473.36／preload3,699,984、reasoningは30,664.76／29,164.19でinput/output内数。cache-writeの未記録80／75を0へ変換していない。partial・component分布と参照件数をsupplementaryに保持した。

## 原データ・測定妥当性の問題と対処

| 証拠箇所／問題 | 影響する主張 | 重大度 | 不確実性・対処 |
| --- | --- | --- | --- |
| data/public-check-audit：unknown100Run、意味未監査1259check | 品質維持・全割付pass率 | 重大 | boundsで限定。自動coverageと独立意味監査を分ける。原failやnullを0化しない |
| dataset usage：10欠測／7不完全pair | 全割付Run全体token差 | 重大 | 有限上限未提供。全27仮定を保持し、完全caseを主要効果へ置換しない |
| public-stop-ledger／phase／原STOP | 停止原因・効率・単一regime | 重大 | 共通targetや登録scopeを原因Runへ変換しない。旧HTTP fence false／未記録を保持 |
| 5045 C015/C016保存trace・画面・凍結JS | 観測環境でのcart更新と単独機序 | 重大 | 同一クリックPOST200camelCase、JS PascalCase、画面未更新を照合。local.adguard.org実HTTP200注入、事前404原因未同定を保持。環境非依存欠陥や排他的原因は未確認 |
| 5080 E008/E010原HTTP／観測log／diagnostic build | invalid date欠落create/edit要求 | 重大 | 各3番目invalidの302と前GET200／hidden dateなし。保存Program/AppHost/専用csproj3pin、両output5pin、原DLL/PDBを最終再照合。wire payload直接保存、今回独立rebuild／SQL差分はなし |
| 5073 E003/E012：日付cell／UI・DB・WAL | 原critical failの意味 | 重大 | DB2026-02-03 00:00:00とUI日付の相違、比較4cell値とWAL baseline未解決。ambiguous維持。新しいbuild照合で当時の未確認記録を書き換えない |
| 5096 R029/C030：2つのdirectory名 | 旧project/assembly依存 | 中 | 2つの名称検出は実旧app依存を証明しない。全artifact依存不存在も監査しておらずambiguous |
| 3実buildとhistorical coverage source | 評価器同等性・原checkの意味 | 重大 | 診断Educationの保存build結合は5080で確認。Music／旧Educationを含む全版の独立同等性や再buildは未確認 |
| 各pair MANIFEST/NOTICE／原本はprivate | 公開資料での品質再監査・全環境replay | 重大 | 認証、ownership、oracle/DB/runtime/binary、条件未確認画像を除外。SHAと理由、能力への影響を保持 |
| 固定2family／反復Run／session/wave | 独立性・代表性・一般化 | 重大 | 固定対象内の記述。100appsやrequest独立実験へ変換しない。実施可否と代表性／一般化を別判断 |

5080のビルド根拠：保存receipt SHA256 `381313ba71dc478db0e848c1082b630f3c83f4db795d0fa089048b10dfc5b511`、Program `5552b4d68e32fd91c451be2e4ec5beae4383f2f7890b16c0a7679d511568b162`、専用compile project `6d538ae58a61b7a19462a3491f420eb0bf6c746edbee64c726c590cb22b693dd`、AppHost `6ddf9bbceec44ee293d02d1d8595edabc556d71fa9ef936aae8de6ef6fb40151`、原DLL `63efeac8c027ba8de53b3a04e86ed7277686b6b52408bedd613b74aa118b620c`、PDB `da37da8aaffd250326be6f96430d86411828174ef3ec14da9d5b641ad3392554`。現repo csprojとは異なる専用compile projectを使った保存buildで、全当時sourceと2出力のSHA／サイズを照合した。非同梱のprivate build資材に依存するため、公開hashだけで同じ入力意味監査を独立再実施できるとは主張しない。7checkのoriginal evidence refsと追加理由はpublic-check-auditに残した。

## 競合説明と判断

以下は観測後の探索的説明で、事前仮説ではない。初期情報が探索負担を変えたなら、品質を保った同じvariant内で探索行動・token構成差が期待される。一方、成功集合の正の差、Musicの尺度による符号差、Contosoの大量品質未知は単純な一方向説明を支持しない。失敗・停止が説明するなら短いRun／shared STOP／partialに集中すると予測されるが、正常79pairでも負の平均が残る。測定が説明するならbuild／coverage／raw proseとの矛盾へ集中し、日付・名称・cartの限定監査はその検討箇所を示す。選択、順序、cache、時期、provider変動、固定family特性、偶然も残る。観察的strataの差やAIの意見一致から排他的機序や一般化を決めない。

| 対応候補 | 既存資産／不足への効果 | 今回の判断 |
| --- | --- | --- |
| 原本維持・主張限定 | 負結果・未知・故障と全100分母を保持 | 採用。取得完了と効果識別を分離 |
| 保存結果の再分析 | モデル追加なしに全条件比較可能 | 今回実施。欠測真値・意味監査・環境交絡は解消しない |
| 保存生成物の別保存での再評価 | 評価意味や日付／名称／注入を狙って検査 | 次の対処候補。元seq1を上書きせず別計画・実行権限が必要 |
| 限定再取得 | 証拠が復旧不能な影響条件のみ改善可能 | 必要性を箇所別に判断。今回の分析推奨だけで起動しない |
| 追加対照／独立追試 | host注入分離・固定評価・usage完全性等を識別 | 将来別設計候補。今回100を独立多数appsへ一般化しない |
| 問い／対象の変更、全面再取得 | 代表性や設計不足には資産補完が必要 | 先に選ばない。saved再監査・限定対処の効果と必要条件を比較 |

研究結論に採用しないことと原本削除は別である。今回は新しい取得、再採点、別モデル、Linux対応、原データ削除を実行していない。対処表は追加実行の許可ではない。

## 方法基準・Skill・既読情報

ACM SIGSOFT General Standard／Benchmarkingを、自動ソフトウェア比較・固定要求・反復Runの証拠、測定、再現性、一般化範囲に適用した。人間参加者／医療基準を機械的に移植せず、基準項目の数やAI一致を品質点数にしない。再現の証拠はUUID／実送信／原seq1／SHA／終了ACK／公開復元、測定の不足は上の問題表、一般化範囲は固定2familyに対応する。[SIGSOFT pinned source](https://github.com/acmsigsoft/EmpiricalStandards/tree/554118c6b60580aeba4cbe1222fbe12df5e62171)を確認した。p値や任意閾値だけで科学的・実用的判断を行わない。

実読・使用したSkillはresearch-analysis、scientific-critical-thinking、hypothesis-generationと必要なupstream/statistical pitfalls/bias/causal/concepts／SIGSOFT資料。Skillは研究管理側のみで使用。残る3Skillの配置と実使用は区別する。K-Dense pin `154988403bb5a18e9d3c0ce4e6d5e2e4b184a298`。初期の自己分析案より前に一部途中結果・fault・復旧条件を見ており、盲検／元事前登録ではない。ユーザーが許可したGPT6-Astraへ設計・実装・解釈を相談したが、意見一致は独立専門家検証ではない。

[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065)はv2（2026-09-02）preprintの一次metadata／abstractを確認した。全文、査読、本taskでの有効性や新規性は確認していない。系統的新規性調査も実施していない。Skillの配置・セッション認識・今回実使用・効用を区別する。

## 公開物・再分析可能性の境界

今回専用tag `source-info-v5-100p2-f39b38adc6bb-final` に結び付ける公開dataは全200assignment／run／4500check／100pair／27scenario、全14計算結果、15コード、Windows CPython3.14.4環境metadata、モデル識別、停止ledger、凍結契約のhome-prefixのみを置換した公開派生、READMEと本report。各pairで保存済みの公開raw派生を100catalogと統合collectionにまとめる。collectionはpair ZIP/parts＋manifest＋review＋scan＋analysis.zip＋catalogのexact assetsで、全Release添付物そのものではない。analysis公開reviewは独立assetとしても保持する。

全100公開pair（47,472ファイル、元pair ZIP合計868,738,964bytes）の匿名再取得・全SHA復元が実EXIT0で完了した。統合ZIPのnested SHA照合、最終Release匿名取得、公開packageだけからの14結果byte/SHA完全一致は、後段の実verification receiptを成功根拠として確認する。本report生成時点のこれら未実施項目を既成事実として扱わず、Release notesに実施結果と独立manifest SHAを記録する。統計再計算・保存品質意味の独立監査・全private評価環境再実行は別の達成範囲。

秘密・native auth・ownership・private oracle/DB/runtime/binary・条件未確認の画像は公開copyから除外し、原本は保持。各MANIFEST／NOTICEに理由・SHA・公開能力への影響を残す。AIによる有限の内容・privacy・権利確認とmemory-only既存キーscanであり、human_reviewはnot_run、普遍的無漏洩／全権利／全品質保証ではない。sample2に既存の包括licenseがない部分へ新しい包括reuse licenseを勝手に付けていない。

既存`result`はMusic単独・別期間・別割付で今回に流用・合算していない。foreign UUID registryと厳密取得commitがないためcohort間UUID重複ゼロは確認不能。今回dataset・catalog・ZIPは原bundleと200UUIDへ独立結合している。再分析はWindows限定、標準libraryのoffline4CLIでprovider／evaluator／downloaderを呼ばず、外部の新規出力先で行う。実行手順と独立MANIFEST SHAの取得はREADME／Release notesを参照する。
