# Music 評価の帰属と有限受入検証（2026-10-06）

Music 評価1.6.0は、観測済みの製品違反、検査の前提未成立、観測側の障害を独立に保存する。原100ペア・200 Run、Music100件の旧採点、評価1.4/1.5の配布物、既存7回の別保存評価（5生成物）は変更しない。本記録は評価器の有限受入検証であり、生成物全体の品質保証やサンプル全体の品質改善の主張ではない。新規モデル呼び出しと取得は0である。新1.6による保存4生成物の別保存評価は親管理者が固定計画と最終配布物に基づいて実行する別工程である。

## 一次証拠と検討方法

固定された公開要求、各生成物の保存HTML/HTTP記録、独立カタログ価格、旧台帳・採点、評価器のシナリオ実装を照合した。旧レポートと独立レビューの指摘も検証対象にした。研究管理用の `research-analysis` と `scientific-critical-thinking` を分析部分に使用した。導入元はローカルmanifestに記録された K-Dense commit `154988403bb5a18e9d3c0ce4e6d5e2e4b184a298`。SIGSOFTの一般・benchmark基準は、ソフトウェア測定の観測可能性、測定定義、反例、再現手順の検討に適用し、人間参加者研究の規則を代用していない。

Music100件の最初のHTTP-only採点を列挙し、C014の旧failは5011/5061/5067の3件だった。列挙方法と全33判定、選択4例の保存入力・ログ・oracleのhashは私的証跡 `music16-attribution/saved-census-and-cases.json`（SHA256 `504273d14c5d5fb895c43ccd624930a82002d06abe3a4fb9b4632c7c51fba99c`）に保存した。この列挙は旧採点の再解釈・再採点ではない。以下の4例は異なる失敗境界と正常対照を確かめる診断選択であり、無作為抽出や代表性の証拠ではない。

| 保存例・観測 | 影響・重大度 | 分類と対処・不確実性 |
| --- | --- | --- |
| 5011: 削除に失敗した同一sessionの後に3回追加し、数量5、単価7.25、total36.25 | R013/C014。数量oracle汚染によるfalsefail、高 | 5×7.25は正しい。新シナリオは独立sessionの3追加を観測し、算術は独立単価×実観測数量で判定する。削除失敗の事実はC015/16に残す |
| 5061: `cart-total` の保存GET表示は `$21.75` | R013/C014。内部parserと公開表示要求の不一致、高 | marker欠落ではない。公開要求は小数点と2桁であり、通貨記号禁止ではない。有界の金額解釈を1.6で明示した。保存GETの `$0.00` はクリック後の表示保証ではない。実JSの `$0` が観測されれば2桁違反はfailを維持する |
| 5011/5061: 実際の非empty basketと有効入力に対するCheckout HTTP400。その後は成立order/GETがない | R018/C019、R025/C026は製品失敗。C020–23の一部はcascade、高 | HTTP400をunknownへ消さない。第二注文、清空、完了表示・他sessionのorder閲覧は各々の実前提がない場合unknown。別例の実order ID・stored row・GETは、購入checkのラベルと独立に採用する |
| 5067: AddToCart500、empty basket、旧POST record0と条件未成立の注文比較 | C012は製品失敗。C015/16、C019等の前提未成立、高 | hash-bound実HTTP500は残す。未観測Remove失敗やnonempty注文の保存不整合を発明しない。C017の要求basket形成失敗と、そのbasketの未観測算術も分ける |
| 5067: missing-field POST9件HTTP200・formありだが初期cart empty、外国Remove未送信 | R024/C033、R031/C032。bool default/非empty比較からのfalsefail、高 | 各fieldを新sessionで観測する。HTTP/form必須違反は独立にfailを残し、cart保持・外国操作は必要な実前提がない場合unknown |
| 5096: modern同名プロジェクトと `/tmp/mvc-music-store/musicstore.sqlite` データ保存先 | R029/C030。名前だけによるlegacy falsefail、高 | 実参照・起動と無害な名前を分離した既存1.4修復を継承。旧DLLと新DLLによる同一保存treeの有限比較を保存。新functional正例対照として選択 |

私的証跡には元の保存位置・hash・観測箇所・旧判定を保持する。公開文書に原プロンプト全体、生ログ、秘密値、非公開oracleの内容は転記しない。

## 全33チェックの確認範囲

次表は全checkを照合した結果であり、全てを新規に書き直したという意味ではない。有限反例を作った箇所はテストsourceと配布物receiptに結び付ける。

| Check | 1.6の判定と前提・観測の扱い |
| --- | --- |
| C001 | web project発見、publish結果とentry assembly。既存有限predicateを維持 |
| C002 | 初期起動時のreadinessを固定。後続restart失敗で起動済みという観測を消さない |
| C003/004/005/007/008/010/011 | 各Browse responseを独立評価。後続timeout・restart失敗でも先に観測した500等を残す。欠けたresponseはunknown/fault |
| C006 | catalog・既存order行保持・restart後の新規注文を分離。新order ID欠測を既存データ破壊と呼ばない。実catalog損失/行欠落/valid checkout失敗はfail |
| C009 | visibleな完全金額tokenで価格を比較。2.48を12.48/2.480のsubstringでpassにしない。script/style/templateは証拠に使わない。複数・unsupported表示はunknown |
| C012 | GET追加のowned Cart destinationと実redirect statusを確認。301/302/303/307/308を認識し、304やforeign/extra pathを受理しない。未観測のqualified flowはunknown |
| C013 | 実2追加後のAlbum/数量。generic row markerを読めない場合をemptyと見なさない |
| C014 | 独立追加session。独立価格×観測済みpositive数量の算術と必須金額表示を分離。empty setupは算術unknown、真のwrong amount/fraction/marker欠落はfail |
| C015/016 | positive owned RecordId、実quantity2/1、POST/JSON、実後状態と金額。未実施POSTを失敗と呼ばない。browser finite failはHTTP unknownと共存、browser passで欠測HTTPを補完しない |
| C017 | 指定mixed basketの形成、金額表示、そのbasketの算術を分離。形成が失敗しても真の形成違反は残し、成立していないbasketの期待総額を数値違反と呼ばない |
| C018 | actual A/B cart response/statusとpositive A cartを確認。B500のempty風bodyでは隔離passにしない。実foreign row漏洩は他前提不足と独立にfail |
| C019/026 | readableでnonemptyのowned basket、有効入力、address form、owned exact completion URI。valid basket HTTP400はfail。missing basketは購入outcome unknown |
| C020 | stored first purchase、実cleared cart、別のreadable second basketを確認。前checkのpassラベルへ依存させない。malformed残存markerで次購入を実行しない |
| C021 | 実nonempty purchase後の全rowとzero total。unsupported残存rowを無視してempty/passにしない |
| C022/023 | 実positive owned order ID、stored rowと実own/other GETを独立確認。先行購入のunknownだけで実GETを捨てず、GET500と後続DB unreadableはfail+fault+gapとして保存 |
| C024/025/033 | HTTP200と全9住所field+PromoCodeを持つ同一form、cart保持、stored order差分を分離。PromoCodeだけのformはpass不可。各missing-fieldは別session。欠けたcart前提でも実500/form欠落はfail |
| C027/028 | Microsoft.NET.Sdk.Webとnet8以上、System.Web/.NET Framework4非依存の既存静的predicateを確認、継承 |
| C029 | 指定DB fileの存在を後続restart readinessで隠さない |
| C030 | 名前と実legacy依存を分離する既存metadata検査を継承。read failure/不確かな参照はunknown、確定legacy依存はfailと独立に保存 |
| C031 | 原migration行保持と、新規stored order算術/detailsを分離。実input basketが指定条件を満たす時だけworkflow比較。真のstored total/details不整合・contracted table欠落はfail。BUSY/LOCKED/CANTOPEN等はobserver fault/unknown |
| C032 | positive actual A rowと実foreign POST、その後のraw A/B snapshot比較。未送信/defaultfalse/後GET読取faultを製品failへ変換しない。実cart変化はfaultと共存するfinite fail |

## 明示した解釈境界

Moneyはexactly-one `cart-total` marker、ASCII数値、小数点と2桁、単一Unicode通貨記号の前置/後置、単一符号と空白に限って読める。符号を保存し、decimal coefficient上限を超える値を丸めない。二重符号/通貨、複数金額、ラベル、grouping、括弧など未対応表現はunknownであり、数値を推測してpass/failにしない。欠落/重複markerや明白なfraction違反はfinite failure。HTTPとbrowser consumerは共通の有限金額oracleで照合し、1.4/1.5のstrict解釈を変更しない。

row decoderはTR以外のmarker要素も観測し、unsigned int32/leading zeroを読む。同一Albumの複数linkは許可し、異なるAlbum、曖昧/overflow ID・count、重複row IDをunknownとして残す。必要quantity markerの欠落と孤立quantityはfinite contract violationとcoverage gapを残す。record0は読取結果に残すが、positive owned rowを必要とする操作は実行しない。

POST checkoutの301/302/303はowned exact completion pathとpositive IDに結ぶ。foreign/extrapath/誤IDはfail。307/308のmethod維持、同origin exact pathのquery/fragment付きflowは今回実際のそのflowを観測しないためunknownとする。公開要求にないquery/fragment禁止を製品仕様として追加しない。GET追加の307/308はGETを維持するため別扱いである。

有限failureを付けても元のError/fault・Blocked predicateを失わない。いずれかの必須predicateがunknown、またはobserver faultがある出力は `researchStatus=incomplete`、評価器の `quality=null`。既知の製品failureの判定は残る。これを品質改善や完全観測と呼ばない。

## 検証と残る限界

合成counterfixtureには正常・負例・境界・旧版対照、保存5011/5061の入力観測に由来する有限回帰を含めた。旧受理済み1.5 DLLの5反例はRED、新1.6 DLLで同じ入力はGREENになることを別保存witnessで確認する。valid checkout400、Add500、wrong money/precision、確定stored data不整合、missing table、foreign URIはunknownに消さない負例である。合成receiptは実app/UI実行の証拠ではない。

実コマンドはSDK8.0.425の `dotnet build ... --no-restore` とテストDLL実行。最終配布DLLをテストrunnerに置き、通常assertions、共通money fixture、既存hash-bound receiptの相互運用、保存5096のstatic scanを確認する。同じcompile pathで2回のDLL/PDB一致、旧依存bundleの保持、source/SDK/command/runtime inventoryは別保存build receiptに記録する。receipt自身はruntime inventoryから除外する。最終source commitとDLLのbind、最終件数・hashはそのreceiptを正とする。

有界parserは任意のHTML/CSS visibility・opaque money・indirect/dynamic launchを一般に解決しない。cross-platform/path deterministic build、未検査表現への一般化、100生成物の新品質分布は主張しない。静的反例の修復と、保存4生成物の固定技術評価の成功は別の受入gateである。旧データを研究結論に使う範囲の判断は、この修復だけでは完了しない。
