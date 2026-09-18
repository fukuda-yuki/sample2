# 探索後の人による抜き取り確認材料

**人の確認は未実施。** 新規バッチは3枠目の環境障害で中断したため、現時点で
全条件の合格生成物は揃っていない。これは確認対象と手順の納品であり、人の合格記録ではない。

## 対象と起動

選定母集団は今回の初回18枠のうち、実行完了・完全計測・品質合格のRunである。
既存6 Runや補充を混ぜない。合格集合のトークン中央値に最も近いものを選び、
同値なら実行開始が早いものを選ぶ。

| 条件 | 今回の対象 | 選定理由 | 人の判定 |
|---|---|---|---|
| explore | 新規 MS1-001-explore-001 | 合格1件、中央値4,337,365 tokensと一致 | Not run |
| preload | 新規 MS1-001-preload-001 | 合格なし。93.1点の失敗原因を確認する対象 | Not run |
| explained | 新規 MS1-001-explained-001 の障害記録 | モデル未実行、アプリ生成物なし | アプリ確認不可 |

対象のRunは `runs/exploration-20260919-ms1` 直下。既存6件に含まれる同名Runとは別である。
評価時のpublish成果物を、ハッシュ一致を確認して
`artifacts/exploration/20260919/human-review/<condition>/application` に複製した。
90ファイルの対応とSHA-256は同ディレクトリの `copy-receipt.json` にある。
原本・固定成果物を編集せず、確認用DBは別の `human-state` に作る。

リポジトリのルートからPowerShellで実行する。既存Dockerのbridgeを使うローカル確認で、
新たな専用ネットワークやモデルRunを作る操作ではない。

```powershell
.\research\review.ps1 -Condition explore -Action Start
# http://127.0.0.1:18101/ をブラウザーで開く
.\research\review.ps1 -Condition explore -Action Restart
.\research\review.ps1 -Condition explore -Action Stop

.\research\review.ps1 -Condition preload -Action Start
# http://127.0.0.1:18102/ は失敗原因確認用
.\research\review.ps1 -Condition preload -Action Stop
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
| 商品を入れ、無効PromoCodeでcheckout | 入力画面に戻り、かごの商品・数量・合計、Orders.OrderId集合が変わらない | R-023、C-024 | Not run |
| 独立した状態でFirstName空欄＋FREEでcheckout | 同様に状態を保持し、注文を作らない | R-024、C-025 | Not run |
| 正しい架空住所＋FREEでcheckout | 完了画面に整数の注文番号、かごが空になる | R-018/020/021/025、C-019/021/022/026 | Not run |
| BでかごとAのComplete URLを開く | Aのかごが混ざらず、Aの注文詳細にアクセスできない | R-017/022、C-018/023 | Not run |
| 作成した注文番号を記録しRestart | 注文番号がDBに残り、カタログが増殖しない。その後の購入で別番号になる | R-005/019、C-006/020 | Not run |

注文集合は確認用コンテナーのDBを読み取り専用で調べられる。

```powershell
docker exec ms1-review-20260919-explore-human python3 -c "import sqlite3; c=sqlite3.connect('file:/data/store.sqlite?mode=ro',uri=True); print(c.execute('SELECT OrderId FROM Orders ORDER BY OrderId').fetchall())"
```

操作日時・条件・Run instance ID・使ったURL・操作前後の表示・注文集合・判定・不一致を
記録する。人の判定欄は、その人が実際に確認してから更新する。
R-005は現行契約の注文ID保持であり、注文詳細の全列保持を保証する項目ではない。
画面の完全な忠実再現、画像/CSSの不足などの対象外事項は、現行29要件の合否と分ける。

## 現時点で分かったこと

エージェントは別の `automation-state` で2生成物の起動とホーム画面を確認した。
exploreにはCartとジャンルのリンクが表示される。preloadはHTMLタグを文字として表示し、
カートとジャンルメニューが正常なリンクにならない。ビルド修正後の `Content(html)` が
保存された最終実装にあり、R-010の不合格と対応する。
この起動・画面確認は人の受入確認や、上表の全シナリオ再実施を意味しない。

preloadのR-029は `.sln` の名前だけを根拠とする判定で、参照先は新しいnet8.0プロジェクトである。
評価器の偽不合格を疑う具体例として別途確認する。現行スコア93.1は改変していない。
explainedはネットワーク作成前後の障害記録を確認する対象であり、画面確認はできない。

本実験の開始には、これらの評価上の不一致の解決と、人による主要シナリオ確認が必要である。
