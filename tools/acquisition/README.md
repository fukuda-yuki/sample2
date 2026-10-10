# 過去の取得運転・回収ツール

現在の取得入口は [`research.acquisition_pipeline`](../../research/acquisition_pipeline.py)
です。[利用手順](../../docs/code-usage.md)を参照してください。

このディレクトリは、新100ペア運転時に使用した補助コードを履歴とともに保持します。

- `driver.py` / `owner.py` / `proofsvc.py`: pipeline導入前のwave運転用。
  当時のWindows絶対パス、successor設定、proofサービスに依存します。
  `owner.py` は読み込み時点で設定を読むため、一般的なCLIとして起動しません。
- `procalive.py`: 当時のWindowsプロセス生存確認用。
- `recover_saved.py`: 保存済み73・75・82・98番の回収専用。75番のみLinux volumeを
  使用する分岐を含みます。汎用の自動復旧ツールではありません。
  元の評価・生成物を保持し、別の採点連番に復旧結果を記録する実装です。

過去の運転に必要な版は固定コミットから復元します。別の取得や別の対象に適用する
場合は、対象・設定・保存先を改めて設計し、これらの固定値を流用しません。
