# 前回100組から今回100組へ：研究責任者の追補判断 v2

今回の100ペア・200 Runは、前回の「抽出済みcatalogと重複する元コード抜粋」の研究を、元コード・既存データが正解を左右する移行課題へ進めたものです。課題の情報依存性を示す有限controlと保存・測定の設計は前進しました。しかし、今回も「品質を維持してRun全体tokenを減らす初期提示方針」を採用する判断には届いていません。品質未知100件、全Run usage欠測10件、有限評価の意味妥当性、実際の運転条件の変更が残ります。次は同じ100組を増やすより、保存資料から測定の曖昧さを解き、測れる問いへ設計を固定することを優先します。

データを無意味とは判断しません。前回の冗長情報の結果を、必要情報にも一般化できないこと、平均token差の負符号を成功効率へ置き換えられないこと、実装終了と品質判定可能性が別であることを明確にしました。これは提示方針の勝者を示す研究成果とは異なります。以下の判断は取得後の探索的検討であり、新しいモデル実験、再採点、原本・旧評価の変更は行っていません。

## 1. 研究の目的と前回からの関係

目的は、既存システムの移行でモデルが受け取るInput contextと、要求品質・Run全体input/output tokenの関係を調べることです。料金、短い実行、同じ教材での反復数を、その目的の代わりにはしません。古いmiscの日本固有条件を今回へ再導入していません。

| 軸 | 前回：既存`result` Releaseの100組 | 今回：source-info-v5の100ペア | 比較の扱い |
| --- | --- | --- | --- |
| 問い | 構造化catalogがあるとき、重複する元データ定義の初期抜粋は必要か | 正解が元コード・既存データに依存するとき、初期提示と必要時探索で何が違うか | 同じ研究目的の発展。介入は同一でない |
| 両条件の情報アクセス | 同じ元ソース、完全catalog246件、同じ取得能力 | 同じ元ソース・既存データと読取り権限 | 「情報を隠す対照」ではない |
| 初期提示の差 | expandedだけSampleData.cs 1–360/431行、51,393 bytes追加。両条件はcatalog JSONと982-byte確認情報を持つ | preloadだけ選定source/data textを追加。Music7ファイル、Education10ファイル | 重複データとtask-relevant sourceの内容差を保つ。bytesをmodeltokenへ換算しない |
| 正式な差の方向 | compact−expanded＝少−多 | preload−explore＝多−少 | 両方の負符号を再現と解釈できない |
| 対象 | Music Storeの一つのcatalog/storefront課題、均一価格8.99 | Music continuity A/B、Contoso enrollment C/D。2family内4variant | 100種類の独立アプリではない。合成データ・研究者overlayを含む |
| 品質 | 29要件・30check、HTTP/browser/DB等の有限契約 | Music31要件・33check、Education12要件・12check | 同じ百分率を同じ潜在品質尺度とは認定しない |
| モデル・予算 | DeepSeek V4.1 Flash、OpenCode1.17.11、Run1800秒/request600秒 | 同じ指定 | provider内部状態・日時まで同一とは限らない |
| 運転 | 直列隣接pair、実順序compact先45/expanded先55、中断・最初のdate-policy改訂あり | 当初同account2 Run/先行50対50。実取得は承認されたwave改訂を含むcap2/4/8 | 元protocolと実際の混合運転を区別する |

前回の完全使用量91組ではcompact−expandedが−515,402.59 token、平均総量比0.8687246（13.1%減）でした。全要件passはcompact61、expanded62＋未知1、全usage完全191/200でした。公開派生CSVから100組・91完全組・平均差を再計算しましたが、大容量の旧raw archiveを独立に再監査した結果ではありません。

提示量を多−少へ統一すると、旧expanded−compactは＋515,402.59、今回preload−exploreの完全93ペア・変種等重み差は−280,283.33です。対象、提示内容、評価、選択集合、運転が違うので、これは記述上の相違です。「効果反転の原因がtask情報の必要性だった」「前回削減を再現した」とは判定できません。

## 2. 何を引き継ぎ、何を作り直したか

| 前回の知見・限界 | 設計前の原資料 | 今回の選択 | 今回で解けた部分／残った部分 |
| --- | --- | --- | --- |
| HTTPだけでは通常削除の不具合を見落とす。HTTP全合格186、複合全合格123、確認失敗76、未評価1という旧監査 | [Issue #21](https://github.com/fukuda-yuki/sample2/issues/21) | 通常browser操作、独立期待値、普通の採点・合成経路を校正 | 有限chain controlsは支持。全未知生成物の意味妥当性は保証しない |
| 均一価格、顧客・注文履歴なし、両arm完全catalogでは元資産の保持や必要性が弱い | [Issue #22](https://github.com/fukuda-yuki/sample2/issues/22) | Musicの非一様価格・丸めpolicy・既存履歴。Contosoのenum/grade、singular/TPH DB変換・関係保存 | 同じ公開要求でもsource/data違いで正解が変わる有限controlは成立。モデルが実際に必要情報を読んだ・理解した証明ではない |
| 1094は75応答があるのにmodel_called=false、1085はraw SSEとnormalized usage不一致、9usage欠測 | [Issue #23](https://github.com/fukuda-yuki/sample2/issues/23) | immutable UUID、intent/send/ack/response/usageを分離、途中SSE・停止・partial保存 | 全200実送信/終了/保全を確認できた。欠測10件は残り、旧欠測も回復したことにはならない |
| 課題数と反復数、欠測と主指標、並行条件が混在 | [Issue #24](https://github.com/fukuda-yuki/sample2/issues/24) | 2family/4variant、等重み、全割付分母、品質とtokenを別指標、未知null、非劣性marginなし | 主張範囲は明確化。未知が大きく、全割付主指標は点識別されない |

時系列は、10月3日の旧監査・Issue #21〜#24、source/data依存taskと測定・記録の修復、1family候補から2family・4variant・64直列pairのv2/v3、AI研究責任者受入のv4、ユーザー指定100ペア・各25・並行候補のv5、10月4〜5日の取得です。100はユーザー固定の探索上限で、powerや品質維持の保証から算出したNではありません。

旧最終reportと再分析ZIPのRelease公開は10月5日で、今回の10月3日設計より後です。一方、保存された旧design-draft-reviewは「2026-10-03の初稿」を記しています。公開日から本文・提言の成立/共有時刻まで後発と決めず、設計判断との前後は未確定とします。その提言を設計前の合意へ逆算せず、日時を確認できるIssue・監査・固定条件を先行判断の根拠とします。直接の「以前の助手提案→ユーザー合意」のnative会話全文はこの調査で取得できず、私がその提案を書いたという個人的帰属は断定しません。親から共有された会話時刻と、今回読んだsampling-instructions原本・固定protocolを区別して証拠表に残しました。

10月5日公開の旧reportも、評価契約の整合、通常クリック自己確認、明細識別、初期提示と後続保持の分離、異なる情報需要の課題、停止時usage追跡という候補を整理しています。当時のIssue #24・固定protocolに基づく今回の介入は初期source提示のみです。自己検証や保持・圧縮方針を同時介入しておらず、旧提言のすべてを実施した研究とは扱いません。

## 3. 今回の到達点と測定の限界

原100ペア・200 UUIDの実送信、原seq1、停止・提出固定、保全、100公開/匿名復元/抽出/所有cleanupゲートが完了しています。モデル応答metadataは全200でdeepseek-v4.1-flashです。provider内部実装の独立証明ではありません。

| 区分 | 今回の原記録・導出 |
| --- | --- |
| 実行 | completed163、operator_stop33、provider_failure3、timeout1 |
| 原初回採点 | scored131、evaluation_incomplete67、evaluator_fault2 |
| 原verdict | pass98、fail6、fail_critical96。sentinelを製品欠陥へ変換しない |
| 証拠付き有限品質 | pass98、確認違反2、未知100。explore50/2/48、preload48/0/52 |
| 使用量 | 190完全、10欠測（explore6/preload4）、93完全pair |
| 独立意味監査 | 目的抽出7check/4Run、違反4check/2Run、未解決3check。全4500check監査ではない |

品質未知100のうち74はcompletedです。内訳はA3、B2、C31、D38。原scored131でも31は意味判断が未知です。実行中断だけを改善してもこの問題は解けません。逆に、operator_stopでも10件、provider_failureでも1件は保存された有限契約passです。execution stateから製品品質を決めません。

現在の98passは、自動保存coverageと原評価による有限判断です。fail側は個別の意味監査を要求する慎重な導出ですが、pass側全件の独立意味監査はありません。したがって従来の品質差[−50,+50]ポイントは、受理したpass/確認違反の意味が正しいという条件付きで残り100を補完する範囲です。実用上の無制限品質や評価器false-passまで含む保証範囲ではありません。

この前提を問い直すため、自動passのうちexplore rE件、preload rP件を仮にunknownへ戻す感度表示を追加しました。範囲は[−0.50−rP/100, +0.50+rE/100]となり、98pass全部を信頼しない極端条件では[−0.98,+1.00]です。この表示は比例差の単位（−98〜＋100ポイント）で、確認違反2件の判定は保持しています。これは誤合格率の推定、98件が間違いという証拠、新しい主判定ではありません。原ラベルは変更せず、固定判定の欠測と測定意味の不確実性を分けたものです。

Educationは同じ版名でも旧DLL6 Run（Dのみ）と診断DLL94 Runに分かれます。診断sourceはCreatedIdの同定と後続観測経路、browser観測とwhole coverageを区別する部分に変更があります。14項目のsynthetic受入や5080の新build結合は有限の支持ですが、全生成物や旧buildとの意味同等性を証明しません。旧DLLのsource対応が未確認な箇所を、現在sourceのdiffだけで当時の実装と断定していません。

限定監査は、5045のcart UI更新不成立、5080のinvalid-date処理で要求されたHTTP200に対する302を支持しました。5073の日付値・DB/WAL基線、5096の旧名称と実依存の区別は未解決です。外部script注入や保存wire不足も残ります。評価器の誤不合格疑い、生成物の確認違反、基盤中断、未測定の品質観点を別々に保ちます。

## 4. 結果を受けて何を問い直したか

最初の全件分析は既に公開したv1です。本追補では、結果・ユーザー補足・別レビューを受けて問いを変更した6段階を実行しました。各段階にplan、実行開始/終了UTC、入力SHA、実行source snapshot/SHA、output SHAを保存しました。履歴表は後から組み立てたことを明示し、時刻を遡って作っていません。

| 段階 | 問い・選択理由 | 実施した変更 | 得た答え・次の判断 |
| --- | --- | --- | --- |
| 1 欠測境界 | 旧0.5/1/2倍率の負符号を、全割付結論にできるか | 品質未知率と任意欠測token平均のanalytic反転境界 | 仮定集合外の符号を制約しない。提示の勝者を選べず、研究史を確認する必要がある |
| 2 研究継続性 | ユーザーが前回→今回の提案・判断の連続性を明示 | 原Issue/固定条件/旧公開表を照合、旧91pairを再集計。旧新混合しない | 冗長提示から必要情報・資産保持への再設計と確定。次は測定修復が判断可能性を回復したか |
| 3 測定意味 | 98自動passと100unknownが何を保証するか | 全200/4500checkの版別coverage census、仮のpass撤回感度 | completed74でも未知。尺度・coverage・誤合格の前提を監査対象へ。原判定は保持 |
| 4 選択と重み | 完全pair負差と双方pass正差は構成比だけか | 同じvariant内の選択mixture、ABC共通supportで平均差変化を分解 | 重みだけでは反転しない。選択後のvariant内平均が変わり、D成功supportは0 |
| 5 phase/build support | 多変量調整で運転・時間・buildを分けられるか | 100pair内一致、task×phase×cap×day×build support、exact rank | 全pairで条件は共通。family/build aliasと疎なsupportがあり、因果調整係数はfitしない |
| 6 停止の起点 | generic STOPを製品失敗/peer原因へ読み替えられるか | 保存predecision証拠を別監査し全200へ結合、no-owned-target等の条件付き比較 | 5監視alarm/3Run-bound guard。中断除外でも負差は残るが選択・品質未知は残る。次は測定優先の判断へ |

これは6つの問い・判断段階です。初段から後続への移行は5回で、そのうち段階2はユーザーの研究史補足により優先順を変更しました。計算CLIは6本分を実行していますが、感度gridセル、独立チェック件数、仮想撤回2499組、再現再計算を考察反復へ数えていません。新しい介入条件のモデル実験は0です。

### 欠測の反転境界

全100pair品質差は、未知のpass補完率をqE/qPとすると `−0.02 + 0.52qP − 0.48qE` です。両未知群が同じ補完率qと仮定しても、q=0.5を境に符号が変わります。これは有限未知ラベルの仮定で、観測から推定したprobabilityではありません。

全Run total-token差は `−234,783.10 + 0.04μP − 0.06μE`。μは各arm欠測Runの真の平均総量という仮定です。0境界は `μP=5,869,577.5+1.5μE`。explore欠測平均を観測済みarm平均4,181,673.70と仮定すると、preload欠測平均12,142,088.05、preload観測済み平均の約3.154倍で差が0です。この倍率のもっともらしさは評価できていません。partialは正式下限に使わず、有限上限なしでは差は両方向に非識別です。

保存段階1のconclusion文には「旧gridの負符号」という広い表現がありました。input/totalに限定する補足を追記しています。output単独の(.5 explore,2 preload)条件は＋744.984で、負ではありません。原result/sourceを保持し、補足を別ファイルにしました。

### 選択後の平均は別の対象

完全usageの変種平均total差はA−107,768.78、B−92,536.32、C−333,312.35、D−587,515.88です。この4つの同じ平均を非負重みで組み替えるだけでは正へ転じません。

双方passかつusage完全35ペアではA17/B16/C2/D0、pooled差＋218,599.49です。Dを0埋めした元の4変種等重み量は計算しません。共通ABCのpool変化＋397,726.91は、対称な記述分解でvariant内の選択による平均変化＋415,670.16、構成比変化−17,943.25となります。Dを完全集合から落とすsupport変更は別に＋109,781.84です。分解は恒等式であり、選択バイアスの因果補正ではありません。

### 共有pair条件と識別できない運転効果

phase/cap/UTC日/実DLL/waveは全100pairでarm間一致でした。共通のpair基線が加法的なら差で打ち消せますが、arm応答の変化、同account干渉、日時依存、選択、測定の意味まで消えるわけではありません。

cap2/4/8は12/180/8 Run。運転改訂のユーザー許可と原v5 protocolを保全し、純粋な固定2-Run regimeを実証した結果へ変換しません。全100pair差をtask/phase/cap/day/buildで説明する加法designは18列・exact rank17。family/build所属には `1 = I(A) + I(B) + I(旧Education) + I(診断Education)` という線形従属があります。旧Education DLLはDの初期phaseだけなので、同phase内の旧新対照もありません。18係数を一意にfitできず、rankが満たされても因果識別には別仮定が必要です。

全4variantのcomplete supportがあるphaseだけの等重み記述ではv5＋56,771.39、v9−189,073.79、v10−340,812.47でした。これは元100pair主対象ではなく、phase内のtask等重み条件付き量です。小phaseには欠けたvariantがありnullです。少数cellの符号からphaseの因果効果やsource提示の効き方を決めません。

### 停止理由の読解で変わった解釈

public v1 STOP ledgerのtrigger IDはexporterが固定nullを出すため、原証拠もないとは断定できませんでした。別レビューが当時のpredecision journal hashまたはappend-only prefix、manifest UUID、owned fenceを照合しました。196原証拠のbyte不変を確認し、公開用whitelistを別保存しています。

8 runtime alarmは、監視プローブ異常5、Runに結合できるguard失敗3でした。3件はpreload-A5052応答不完全、explore-A5066のSSLEOF transport error、preload-C5087応答不完全という保存記録へ結合できます。provider内部根本原因や製品欠陥の証明ではありません。

全200の分類は、監査したSTOP/latchへ未結合159、他のowned runtime target30、guard失敗付きtarget3、v7 recovery/controller targetで起点未解決4、dispatch前の登録scopeのみ4。operator_stop33は全て実targetへ結合し、unique owned target37はoperator_stop33/provider_failure3/completed1です。登録scopeだけの4件は後にcompletedでした。target、停止要求、原因、実際の中断を区別します。

両方completed79ペアの等変種total差は−276,256.54、どちらもexplicit owned STOP targetでない80ペアでは−273,680.12です。したがって観測負差全体を停止したRunだけの累積量で説明する読み方は不十分です。ただしこれらは事後選択で、無障害・無干渉の対照群でも完了反実仮想でもありません。

## 5. 次に何をするか：責任者判断

優先順位は「P0測定監査→必要箇所だけ別保存の測定修復→その後に一つの科学的介入」です。今回の範囲では前二者の具体計画までを確定し、新取得を開始していません。全再取得も、今回条件を即採用することも、既定にしません。

| 優先・対象 | 何を変える／変えない | 根拠・必要証拠 | 完了基準・分岐 |
| --- | --- | --- | --- |
| P0：build/construct対応 | 原seq1不変。版別requirement→construct→check→oracle→coverage→actual DLL/source/dependency表を作る | 旧29/currentMusic31/Education12、実DLL3種、postprocessor等価未確認 | 200Runの版対応を埋め、各意味に対応した証拠と不足を全行に記録。版名だけの同一性判断をしない |
| P0：日付・DB/WAL・CreatedId | original DBとWALをreadonly、別copyで保持。calendar意味と文字列厳密一致を分ける | Education E003/E007/E009/E012 rawfail44/29/27/72check観測（独立欠陥数ではない）と5073未解決 | 各indexへUUID/build/spec、expected/observed cell、基線、依存path、資料有無、unknown理由を付ける。値が復元不能なら明示unknownで閉じる |
| P0：旧名称と実依存 | コメント/名称/data pathとproject/assembly/launch依存を分ける | C030 rawfail3、5096の名称だけの指摘 | complete frozen treeの有限依存監査。実依存の根拠または未確認を残す。名称だけでpassへ反転しない |
| P1：pass側の対称監査 | 4variant×2armで割付順が最初の原導出passを各1、計8Run。原判定は保持 | fail側だけの7check目的監査はfalse-passを除外しない | 8Runの全必須checkに証拠disposition、critical・date・legacy・cartを同規則で点検。非ランダム有限監査で誤分類率を推定しない。旧D DLLの監査・旧新等価性ゲートの代替にはしない。系統不備があれば影響predicateへ拡張 |
| P1：cart環境と停止記録 | 保存network/DOM/resource/guardを読む。外部注入やabsenceを証拠なしに宣言しない | 5045外部scriptの限定観測、5observer alarm/3guard | Music100のevidence availability censusと具体疑義を区別。環境原因を識別不能なら未来のisolated対照を別計画へ |
| P1：診断buildの等価性 | 旧新source/binaryを正しく結合。原6/94を上書きしない | ID同定→後続Edit/Restart、coverage/adoption境界に変更可能性 | actual oldDLL sourcepin、有限boundary入力/期待/結果を対応。不足ならmodel不要校正または保存生成物別評価を別版で計画 |
| P2：行動証拠 | 初期packet→後続source返却→保持/再取得→検証の同じ分類規則を両arm/variantへ | 必要情報のtask controlsはモデルの読解機序を証明しない | 送信bytesとtool返却を区別、分類coverage/unknown/sourceSHAを保存。トレースで意図や理解を断定せず、取得/保持の操作的指標まで |

P0は既存資料のcensusと意味判定であり、rawfail172check等をすべて偽失敗/製品失敗へ確定する約束ではありません。基準を変えるなら新しい品質構成概念、同基準の実装修正なら別保存の再評価です。当時のwire/host/基線がないものは、後日の再評価で当時観測済みへ変換できません。

次の科学的研究候補は以下の順に比較します。現時点でどれも新取得許可ではありません。

| 候補 | 区別できる説明・価値 | 選択条件 |
| --- | --- | --- |
| 修復済み同scopeで初期提示の単独比較 | task-relevant情報の提示が取得/保持の負担を減らすか。今回の問いを保持 | P0完了と実際のstable regime・usage/quality evidence受入が前提。全数を取り直すより欠けた境界に必要な最小比較を設計 |
| 初期提示固定で通常操作の自己確認を単独介入 | 前回・今回のcart/date失敗が検証工程で減るか | UI/DBの機能失敗が実在すると確定した場合。追加検証tokenと全要求達成を同時に測る。提示量と同時変更しない |
| 初期提示と後続保持の分離 | 初期負担か反復保持/再取得か | 既存行動censusでpacket保持が測れること。情報アクセスは揃え、正解oracleをworkerへ渡さない |
| 直列/並行の技術対照 | shared account load/cacheと欠測・実行時間の運転依存 | 今回の変更regimeが研究問いを遮る場合。小さな事前固定technical comparison、結果と研究Runを混ぜない |
| 実務に近い独立source追加・問い変更 | 固定教材の実行可能性と代表性の限界 | 一般移行を主張したい場合。実顧客資産/権利/業務範囲・oracle・資源を確定。4variant反復追加で代表性を代用しない |

追加サンプリング開始条件は、(1)何を学ぶかと単一介入、母対象/claim、主要quality/tokenを固定、(2)task/contract/actual evaluator/source/workerを新hashへ結合、(3)重要疑義が確認結果または影響付きunknownとして閉じる、(4)許容別実装・既知欠陥・observer faultの有限校正と必要な通常操作証拠、(5)実送信/停止/usage/owner回収とstable運転の有限技術受入、(6)未知・欠測・依存・分母・停止規則とN理由を事前固定、(7)必要な承認とexact-plan開始権限、です。未知が主要判断を妨げる場合は、必要証拠を追加するか、問い・claim範囲を変更して再固定するまで開始しません。human_reviewをAIでpassedへ変えません。品質維持を判断する研究に変えるなら、許容差の根拠を取得前に定め、後からmarginを作りません。

## 6. 証拠・レビュー・再現範囲

別workerによる研究史、方法論/STOP、構成概念/測定、実装/再現のレビューを保存しました。数値チェックと主張レビューは別です。同じモデルの意見一致、人間未実施、有限監査を独立施設追試や全品質保証に変換していません。一般化・新規性・モデル内部機序の新主張は出していません。

実読使用Skillはresearch-analysis、scientific-critical-thinking、hypothesis-generation、scientific-brainstormingです。各`.agents/skills/*/SKILL.md`と該当UPSTREAM、statistical_pitfalls/experimental_design、SIGSOFT GeneralStandard/Benchmarking、`docs/research-skills/manifest.json`を参照。K-Dense pin154988403bb5a18e9d3c0ce4e6d5e2e4b184a298、SIGSOFT pin554118c6b60580aeba4cbe1222fbe12df5e62171。自動ソフトウェア比較の目的/指標/固定対象/再現/未知仮定に適用し、人間参加者・医療基準は適用していません。配置、実使用、効果実証は別で、Skill効果の実験はしていません。

公開packageは今回200の既存公開dataset/check audit、旧公開の最小派生表、STOP whitelist、6段階のsource/result/plan/receipt、レビュー、再計算手順を含みます。秘密、auth/ownership原材、private oracle/DB/runtime/binary、権利未確認画像は含みません。旧v1 report/analysis.zip/collectionをそのまま版として保持します。

段階2はoperator取得metadataを含む履歴resultを保全し、公開コピーでは再分析に必要な既に公開済みpriorファイルだけへ入力inventoryを限定した結果を別保存します。数値・分析contentが同一で、変わるのはinput hash inventoryのみと照合します。公開版再計算のbyte一致と、履歴段階2とのcontent一致を別々に確認します。このpackaging再計算は新しい考察反復ではありません。

公開からの再計算は派生数値を再現します。STOP raw prefix監査、旧大容量rawの独立監査、保存品質の独立意味再監査、全private評価環境replayは同じ達成条件ではありません。非公開評価資材を公開してその限界を消しません。

前回資料は[旧result Release](https://github.com/fukuda-yuki/sample2/releases/tag/result)、今回v1/追補の入口は[今回専用Release](https://github.com/fukuda-yuki/sample2/releases/tag/source-info-v5-100p2-f39b38adc6bb-final)です。原取得branchはcodex/wave-publication-adapter-20261004、HEAD bb720727790c9740c4595b0d71820e9c6a106bda、dataset SHA256 8a74ffc4bf90b38297a7668eabe91befa572215c9facdf20c814e617efa125f3。公開追補のmanifestと終了receiptが追加commit、asset、匿名readbackの実結果を記録します。履歴統合はmerge --no-ffを使います。
