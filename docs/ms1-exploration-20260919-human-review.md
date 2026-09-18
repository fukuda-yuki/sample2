# 探索後の人による抜き取り確認材料

**人の確認は未実施。** Docker障害からの明示的な再開後、全初回18枠の処理を終え、
各条件の合格生成物から以下を選んだ。これは確認対象と手順の納品であり、人の合格記録ではない。

## 対象と起動

選定母集団は今回の初回18枠のうち、実行完了・完全計測・品質合格のRunである。
既存6 Runや補充を混ぜない。合格集合のトークン中央値に最も近いものを選び、
同値なら実行開始が早いものを選ぶ。

| 条件 | 今回の対象 | 選定理由 | 人の判定 |
|---|---|---|---|
| explore | 新規 MS1-001-explore-003（3,730,097 tokens） | 合格6件の中央値3,915,396.5へ最も近い2件のうち実行が早い | Not run |
| preload | 新規 MS1-001-preload-003（3,344,941 tokens） | 合格4件の中央値3,747,229.5へ最も近い2件のうち実行が早い | Not run |
| explained | 新規 MS1-001-explained-004（3,783,708 tokens） | 合格5件の中央値3,783,708と一致 | Not run |

対象のRunは `runs/exploration-20260919-ms1` 直下。既存6件に含まれる同名Runとは別である。
評価時のpublish成果物を、ハッシュ一致を確認して
`artifacts/exploration/20260919/human-review-resumed-v1/<condition>/application` に複製した。
全ファイルの対応、Run instance ID、SHA-256は同ディレクトリの `review-targets.json` にある。
原本・固定成果物を編集せず、確認用DBは別の `human-state` に作る。

リポジトリのルートからPowerShellで実行する。既存Dockerのbridgeを使うローカル確認で、
新たな専用ネットワークやモデルRunを作る操作ではない。

```powershell
.\research\review-resumed.ps1 -Condition explore -Action Start
# http://127.0.0.1:18201/ をブラウザーで開く
.\research\review-resumed.ps1 -Condition explore -Action Restart
.\research\review-resumed.ps1 -Condition explore -Action Stop

.\research\review-resumed.ps1 -Condition preload -Action Start
# http://127.0.0.1:18202/
.\research\review-resumed.ps1 -Condition preload -Action Stop

.\research\review-resumed.ps1 -Condition explained -Action Start
# http://127.0.0.1:18203/
.\research\review-resumed.ps1 -Condition explained -Action Stop
```

最初は空の確認用状態から起動する。Stop/RestartでDBは消さない。同じ条件の再確認は
記録を残したうえで行い、原本をリセット対象にしない。
通常ウィンドウをセッションA、InPrivate/シークレットをセッションBとして使う。
通常のタブを2枚開くだけではセッションが分離しない。条件を替えるときは、前条件の
Cookieを引き継がない専用のブラウザープロファイルまたは新しいセッションを用意する。

## 確認する流れと現行評価の対応

入力には架空の値を使う。例：FirstName=Review、LastName=User、Address=1 Main St、
City=Seattle、State=WA、PostalCode=98101、Country=US、Phone=0000000000、
Email=review@example.test。有効なPromoCodeは `FREE`。

| 手順 | 確認する結果 | 要件／評価項目 | 人の判定 |
|---|---|---|---|
| AでHome→ジャンル→アルバム詳細→Add to cart | 通常のリンクで移動でき、商品・価格・Cart件数が見える | R-006/008/010/011、C-007/009/011/012 | Not run |
| 同じ商品をもう1個追加し、1個ずつ削除 | 数量2→1→0、合計金額と表示が対応する | R-012〜015、C-013〜016 | Not run |
| 別の商品も続けて追加 | 2商品の別行と金額の合計が表示され、サーバーエラーにならない | R-016、C-017 | Not run |
| 商品を入れ、無効PromoCodeでcheckout | 入力画面に戻り、かごの商品・数量・合計、Orders.OrderId集合が変わらない | R-023、C-024 | Not run |
| 独立した状態でFirstName空欄＋FREEでcheckout | 同様に状態を保持し、注文を作らない | R-024、C-025 | Not run |
| 正しい架空住所＋FREEでcheckout | 完了画面に整数の注文番号、かごが空になる | R-018/020/021/025、C-019/021/022/026 | Not run |
| BでかごとAのComplete URLを開く | Aのかごが混ざらず、Aの注文詳細にアクセスできない | R-017/022、C-018/023 | Not run |
| 作成した注文番号を記録しRestart | 注文番号がDBに残り、カタログが増殖しない。その後の購入で別番号になる | R-005/019、C-006/020 | Not run |

注文集合は確認用コンテナーのDBを読み取り専用で調べられる。

```powershell
docker exec ms1-review-20260919-r1-explore-human python3 -c "import sqlite3; c=sqlite3.connect('file:/data/store.sqlite?mode=ro',uri=True); print(c.execute('SELECT OrderId FROM Orders ORDER BY OrderId').fetchall())"
```

操作日時・条件・Run instance ID・使ったURL・操作前後の表示・注文集合・判定・不一致を
記録する。人の判定欄は、その人が実際に確認してから更新する。
R-005は現行契約の注文ID保持であり、注文詳細の全列保持を保証する項目ではない。
画面の完全な忠実再現、画像/CSSの不足などの対象外事項は、現行29要件の合否と分ける。

## 現時点で分かったこと

自動確認は `-Session automation` を指定し、別の `automation-state` と18301〜18303番を使う。
人の状態領域とCookieを再利用しない。自動確認の実施範囲・結果は別の確認記録へ残す。
これは人の受入確認や、上表の全シナリオを人が再実施したことを意味しない。

今回選んだ3生成物は、エージェントが起動とホームの実描画を確認した。Cart、ジャンル、商品詳細への
リンクは表示される。商品画像の欠落とスタイルの差も見えるため、画面の忠実再現まで合格したとは扱わない。
記録は `human-review-resumed-v1/automated-preview.json`。人の領域は未作成のまま保持した。
記入用の `human-observation-template.csv` に各条件7シナリオのNot run行を用意した。

初回中断時の旧確認材料は `human-review` に残した。旧対象preload-001はHTMLタグを文字として表示し、
カートとジャンルメニューが正常なリンクにならない。保存された `Content(html)` とR-010不合格に対応し、
エージェントが実画面で確認した。今回の中央値代表preload-003とは異なる生成物である。

preloadのR-029は `.sln` の名前だけを根拠とする判定で、参照先は新しいnet8.0プロジェクトである。
評価器の偽不合格を疑う具体例として別途確認する。現行スコア93.1は改変していない。
別の品質不合格preload-002はCartの主キーがCartIdになり、別商品追加で制約違反を起こした。
人の確認でも異なる商品を続けて追加する操作を含め、R-016/C-017との対応を確認する。
explained-001の起動前障害記録も残すが、上表のexplained-004には確認可能な生成物がある。

本実験の開始には、これらの評価上の不一致の解決と、人による主要シナリオ確認が必要である。
