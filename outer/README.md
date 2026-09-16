# 外側：実験実行基盤（最小経路）

対応 Issue: [#5](https://github.com/fukuda-yuki/sample2/issues/5)。仕様は [docs/outer-harness.md](../docs/outer-harness.md)。

## 何をするか

開始状態の用意、条件の固定、実行、停止確認、成果物の回収と固定、内側の評価器の呼び出し、保存、再集計を行う。
**品質の正解基準は持たない。** 評価器の `verdict` `quality` をそのまま保存し、外側で合否や配点を作らない。
評価器の実行には上限時間を設け、超えた場合は評価器とその子プロセスを道連れに停止して
`evaluator_fault` として記録する（成果物のアプリが残らないようにする）。

## 何をしないか

- **モデルを呼ばない。** 実行器は `dummy` と `manual` だけを実装する。モデルを呼ぶ経路は無い。
- 評価器の出力を書き換えない。既存の評価ディレクトリを上書きしない。
- `blocked` `error` を 0 や合格に読み替えない。
- 並列実行、複数課題、クラウド配備、専用ダッシュボード。これらは #5 の初期範囲に含まれない。

## 構成

| パス | 内容 |
| --- | --- |
| `harness/` | 実行基盤の実装（Python 3、標準ライブラリのみ） |
| `conditions/<task_id>/condition.json` | 条件。課題・開始状態・環境・移行要求・入力条件・実行上限・エージェント版・評価版 |
| `tests/` | 非モデル検証の単体テスト（`unittest`）。87 件 |
| `verify/` | 接続検証のドライバ（`verify.py`）、記録（`README.md`）、生データ（`verification-summary.json`） |

実行時のデータは `runs/` に置き、**追跡しない**。

## 使い方

```powershell
cd <repo root>

# 単体テスト（ダミー実行器と合成使用量のみ。モデルを呼ばない）
python -m unittest discover -s outer\tests -p 'test_*.py'

# 接続検証（実評価器をビルドして動かす。モデルを呼ばない）
python outer\verify\verify.py --repo .
```

接続検証は `runs/_verify` を毎回消してから作り直す。個別の操作は次のとおり。

```powershell
$py = 'python'
$env:PYTHONPATH = "$PWD\outer"

# Run を作る（許可リストに載った入力だけを渡す）
& $py -m harness.cli create --task MS1-001 --condition C01 --attempt 1 `
    --input legacy-source=path\to\legacy-checkout

# ダミー実行器で走らせる（モデルを呼ばない。agent 欄は null のままでよい）
& $py -m harness.cli start --run MS1-001-C01-001 --runner dummy --scenario ok --synthetic

# 停止を確認して成果物を固定し、使用量を正規化する
& $py -m harness.cli collect --run MS1-001-C01-001

# 内側の評価器へ渡す
& $py -m harness.cli score --run MS1-001-C01-001

# 再採点（成果物を変えず、新しい連番で評価ディレクトリを増やす）
& $py -m harness.cli score --run MS1-001-C01-001

# 保存済み資材だけから再集計する
& $py -m harness.cli aggregate

# 原本の保全と復元
& $py -m harness.cli preserve --run MS1-001-C01-001
& $py -m harness.cli restore --package run-MS1-001-C01-001 --destination tmp\restored
```

`start` は条件の `agent` が埋まっていないと失敗する。ダミー実行器を使うときだけ `--synthetic` を付ける。
その場合 `manifest.json` に `synthetic: true` と `model_called: false` が記録され、**実モデル実行の記録としては使えない。**

## 関連

- 仕様: [docs/outer-harness.md](../docs/outer-harness.md)
- 評価器の契約: [docs/evaluator.md](../docs/evaluator.md)
- 非モデル検証の記録と限界: [verify/README.md](verify/README.md)
- 移植元: `sample1` @ `aa76384654bd64bf38cc5a9ada486fb8d3a559ca`（対応表は仕様 §9）
