<#
.SYNOPSIS
  評価器の校正（calibration）を実行する。

.DESCRIPTION
  成果物を固定し、評価器だけを検証する。モデルは一切呼び出さない。

  校正の 4 分類（docs/quality-spec.md §7.1）をすべて含む。
    1. 正例            : inner/fixtures/reference
    2. 重要な負例      : inner/fixtures/negatives の 7 種
    3. 妥当な別実装    : inner/fixtures/alternative
    4. 評価側の障害    : 成果物なし / 台帳に実装のない検査 ID

  期待は実行前に宣言する。各ケースについて「期待する判定」「不合格になる要件の
  集合」「未評価になる要件の集合」「終了コード」「品質点の有無」を固定し、実結果と
  完全一致で突き合わせる。この完全一致は「落ちてはいけない要件」の指定より強く、
  予期しない不合格（誤検出）と予期しない合格（見逃し）の両方を検出する。

.EXAMPLE
  ./run-calibration.ps1
#>
[CmdletBinding()]
param(
    [string]$EvaluationVersion = '1.0.0'
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $here)
$evaluator = Join-Path $repo 'inner\evaluator\MusicStore.Evaluator'
$negatives = Join-Path $repo 'inner\fixtures\negatives\apply.ps1'
$reference = Join-Path $repo 'inner\fixtures\reference'
$alternative = Join-Path $repo 'inner\fixtures\alternative'
$specSource = Join-Path $repo 'inner\spec\requirements.json'
$catalogSource = Join-Path $repo 'inner\spec\catalog.json'
$runs = Join-Path $repo 'runs'
$dll = Join-Path $evaluator 'bin\Release\net8.0\MusicStore.Evaluator.dll'

Write-Host '評価器をビルドします。'
& dotnet build (Join-Path $evaluator 'MusicStore.Evaluator.csproj') -c Release --nologo -v q
if ($LASTEXITCODE -ne 0) {
    throw '評価器のビルドに失敗しました。'
}

if (-not (Test-Path $dll)) {
    throw "評価器のアセンブリがありません: $dll"
}

# 成果物ハッシュは bin/obj を無視するが、成果物の中身を追跡済みの状態に揃えておく。
foreach ($fixture in @($reference, $alternative)) {
    foreach ($dir in @('bin', 'obj')) {
        $path = Join-Path $fixture $dir
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
        }
    }
}

if (Test-Path $runs) {
    Remove-Item -Recurse -Force $runs
}

New-Item -ItemType Directory -Force -Path $runs | Out-Null

$spec = [System.IO.File]::ReadAllText($specSource, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$requirementIds = @($spec.requirements | ForEach-Object { $_.id })
if ($requirementIds.Count -ne 29) {
    throw "要件台帳の件数が想定と違います: $($requirementIds.Count)"
}

function Select-Except {
    param([string[]]$Excluded)
    return @($requirementIds | Where-Object { $Excluded -notcontains $_ })
}

function Test-SetEqual {
    param($A, $B)
    $a = @($A | Sort-Object -Unique)
    $b = @($B | Sort-Object -Unique)
    if ($a.Count -ne $b.Count) {
        return $false
    }

    for ($i = 0; $i -lt $a.Count; $i++) {
        if ($a[$i] -ne $b[$i]) {
            return $false
        }
    }

    return $true
}

# ---------------------------------------------------------------------------
# 期待の宣言。ここで固定した内容を実行後の実結果と突き合わせる。
# ---------------------------------------------------------------------------
$plan = New-Object System.Collections.Generic.List[object]

function Add-Case {
    param(
        [string]$CaseId,
        [string]$Kind,
        [string]$Artifact,
        [int]$Sequence,
        [string]$ExpectedVerdict,
        [string[]]$ExpectedFailed,
        [string[]]$ExpectedBlocked,
        [string]$Negative = $null,
        [string]$Spec = $null,
        [string]$Catalog = $null,
        [int]$ExpectedExitCode = 0,
        [bool]$ExpectedQualityNull = $false,
        [string]$Note = ''
    )

    $plan.Add([ordered]@{
            caseId              = $CaseId
            kind                = $Kind
            artifact            = $Artifact
            sequence            = $Sequence
            negative            = $Negative
            spec                = $Spec
            catalog             = $Catalog
            expectedVerdict     = $ExpectedVerdict
            expectedExitCode    = $ExpectedExitCode
            expectedQualityNull = $ExpectedQualityNull
            expectedFailed      = @($ExpectedFailed)
            expectedBlocked     = @($ExpectedBlocked)
            note                = $Note
        })
}

Add-Case -CaseId 'cal-ref-001' -Kind '正例' -Artifact $reference -Sequence 1 `
    -ExpectedVerdict 'pass' -ExpectedFailed @() -ExpectedBlocked @() `
    -Note '自己作成の正例。29 要件すべてが通ることを期待する。'

Add-Case -CaseId 'cal-ref-002' -Kind '正例' -Artifact $reference -Sequence 2 `
    -ExpectedVerdict 'pass' -ExpectedFailed @() -ExpectedBlocked @() `
    -Note '同じ成果物を 2 回評価し、判定と品質点が一致することを確認する。'

Add-Case -CaseId 'cal-alt-001' -Kind '妥当な別実装' -Artifact $alternative -Sequence 3 `
    -ExpectedVerdict 'pass' -ExpectedFailed @() -ExpectedBlocked @() `
    -Note '最小 API と素の SQLite で書き直した別実装。正例と同じ要件を満たすことを期待する。'

Add-Case -CaseId 'cal-alt-002' -Kind '妥当な別実装' -Artifact $alternative -Sequence 4 `
    -ExpectedVerdict 'pass' -ExpectedFailed @() -ExpectedBlocked @() `
    -Note '別実装の 2 回目。判定と品質点の一致を確認する。'

Add-Case -CaseId 'neg-remove-count-pre-decrement' -Kind '重要な負例' -Artifact $null -Negative 'remove-count-pre-decrement' -Sequence 10 `
    -ExpectedVerdict 'fail' -ExpectedFailed @('R-014') -ExpectedBlocked @() `
    -Note '削除応答の数量を減算前に読む。R-014 だけが落ちることを期待する。'

Add-Case -CaseId 'neg-no-quantity-multiply' -Kind '重要な負例' -Artifact $null -Negative 'no-quantity-multiply' -Sequence 11 `
    -ExpectedVerdict 'fail_critical' -ExpectedFailed @('R-013', 'R-016') -ExpectedBlocked @() `
    -Note 'かご合計で数量を掛けない。金額を見る R-013 と R-016 が落ちることを期待する。'

Add-Case -CaseId 'neg-duplicate-cart-lines' -Kind '重要な負例' -Artifact $null -Negative 'duplicate-cart-lines' -Sequence 12 `
    -ExpectedVerdict 'fail_critical' -ExpectedFailed @('R-012', 'R-013', 'R-014', 'R-015', 'R-016') -ExpectedBlocked @() `
    -Note '同じアルバムでも明細を増やす。明細構成を見る R-012 R-014 R-015 R-016 と金額の R-013 が落ちることを期待する。'

Add-Case -CaseId 'neg-no-seed' -Kind '重要な負例' -Artifact $null -Negative 'no-seed' -Sequence 13 `
    -ExpectedVerdict 'fail_critical' `
    -ExpectedFailed @('R-002', 'R-003', 'R-004', 'R-005', 'R-006', 'R-008', 'R-010', 'R-011', 'R-012', 'R-013', 'R-014', 'R-016', 'R-017') `
    -ExpectedBlocked @('R-023', 'R-024') `
    -Note '初期カタログを投入しない。カタログを前提とする要件が連鎖して落ち、404 系と注文系は落ちないことを期待する。かごに明細を入れられないため入力検証の 2 要件は未評価を期待する。'

Add-Case -CaseId 'neg-destructive-seed' -Kind '重要な負例' -Artifact $null -Negative 'destructive-seed' -Sequence 14 `
    -ExpectedVerdict 'fail_critical' -ExpectedFailed @('R-005') -ExpectedBlocked @() `
    -Note '起動のたびに DB を作り直す。注文が保持されない R-005 だけが落ちることを期待する。'

Add-Case -CaseId 'neg-unknown-album-500' -Kind '重要な負例' -Artifact $null -Negative 'unknown-album-500' -Sequence 15 `
    -ExpectedVerdict 'fail' -ExpectedFailed @('R-009') -ExpectedBlocked @() `
    -Note '存在しないアルバムで 500 を返す。R-009 だけが落ちることを期待する。'

Add-Case -CaseId 'neg-legacy-wrapper' -Kind '重要な負例' -Artifact $null -Negative 'legacy-wrapper' -Sequence 16 `
    -ExpectedVerdict 'fail' -ExpectedFailed @('R-029') -ExpectedBlocked @() `
    -Note '旧実装を起動する記述を残す。静的検査の R-029 だけが落ちることを期待する。'

$missingArtifact = Join-Path $runs 'no-such-artifact'
Add-Case -CaseId 'fault-missing-artifact' -Kind '評価側の障害' -Artifact $missingArtifact -Sequence 90 `
    -ExpectedVerdict 'error' -ExpectedFailed @() -ExpectedBlocked @() -ExpectedExitCode 2 -ExpectedQualityNull $true `
    -Note '成果物ディレクトリが無い。成果物の欠陥ではなく評価側の障害として error になることを期待する。'

# 台帳の写しに実装のない検査 ID を足し、評価器自身の自己検証が働くことを確認する。
# 台帳とカタログは別ディレクトリに置かれる想定なので、カタログは明示的に渡す。
$specCopyDir = Join-Path $runs 'fault-unimplemented-check'
New-Item -ItemType Directory -Force -Path $specCopyDir | Out-Null
$specCopy = Join-Path $specCopyDir 'requirements.json'
$specText = [System.IO.File]::ReadAllText($specSource, [System.Text.Encoding]::UTF8)
$specText = $specText.Replace('{ "id": "C-001",', '{ "id": "C-999", "observation": "実装のない検査。" },{ "id": "C-001",')
[System.IO.File]::WriteAllText($specCopy, $specText)

Add-Case -CaseId 'fault-unimplemented-check' -Kind '評価側の障害' -Artifact $reference -Sequence 91 -Spec $specCopy -Catalog $catalogSource `
    -ExpectedVerdict 'error' -ExpectedFailed @() -ExpectedBlocked @() -ExpectedExitCode 2 -ExpectedQualityNull $true `
    -Note '台帳に実装のない検査 ID がある。成果物を採点せず error になることを期待する。'

# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------
function Invoke-Evaluation {
    param(
        [string]$CaseId,
        [string]$Artifact,
        [int]$Sequence,
        [string]$Spec,
        [string]$Catalog
    )

    $out = Join-Path $runs $CaseId
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $stdoutPath = Join-Path $out 'evaluator-stdout.txt'
    $stderrPath = Join-Path $out 'evaluator-stderr.txt'

    $arguments = @($dll, '--artifact', $Artifact, '--out', $out, '--evaluation-version', $EvaluationVersion, '--sequence', "$Sequence")
    if ($Spec) {
        $arguments += @('--spec', $Spec)
    }

    if ($Catalog) {
        $arguments += @('--catalog', $Catalog)
    }

    # 評価器は評価側の障害を stderr に書いて終了コード 2 で終わる。$ErrorActionPreference = 'Stop' の
    # ままネイティブ コマンドの stderr を扱うと終了エラーとして扱われ、ここでスクリプトが止まる。
    # 出力はファイルへ回し、成否は終了コードだけで判定する。
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & dotnet @arguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    $result = [ordered]@{
        caseId       = $CaseId
        exitCode     = $exitCode
        verdict      = $null
        quality      = $null
        evaluationId = $null
        failed       = @()
        blocked      = @()
        errored      = @()
        stdout       = ([System.IO.File]::ReadAllText($stdoutPath)).Trim()
        stderr       = ([System.IO.File]::ReadAllText($stderrPath)).Trim()
    }

    $evaluationPath = Join-Path $out 'evaluation.json'
    if (Test-Path $evaluationPath) {
        # PowerShell 5.1 の Get-Content は既定で ANSI として読むため、UTF-8 を明示する。
        $evaluation = [System.IO.File]::ReadAllText($evaluationPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        $result.verdict = $evaluation.verdict
        $result.quality = $evaluation.quality
        $result.evaluationId = $evaluation.evaluationId
        if ($null -ne $evaluation.requirements) {
            $result.failed = @($evaluation.requirements | Where-Object { $_.judgement -eq 'fail' } | ForEach-Object { $_.id })
            $result.blocked = @($evaluation.requirements | Where-Object { $_.judgement -eq 'blocked' } | ForEach-Object { $_.id })
            $result.errored = @($evaluation.requirements | Where-Object { $_.judgement -eq 'error' } | ForEach-Object { $_.id })
        }
    }

    return $result
}

$records = New-Object System.Collections.Generic.List[object]

foreach ($case in $plan) {
    $artifact = $case.artifact
    if ($case.negative) {
        $artifact = Join-Path $runs "neg-$($case.negative)\artifact"
        Write-Host "負例 $($case.negative) を作成します。"
        & $negatives -Name $case.negative -Out $artifact
        if (-not (Test-Path $artifact)) {
            throw "負例 $($case.negative) の作成に失敗しました: $artifact"
        }
    }

    Write-Host "評価します: $($case.caseId)"
    $result = Invoke-Evaluation -CaseId $case.caseId -Artifact $artifact -Sequence $case.sequence -Spec $case.spec -Catalog $case.catalog

    # 期待と実結果の突き合わせ。宣言は実行前に固定済み。
    $failedMatch = Test-SetEqual $result.failed $case.expectedFailed
    $blockedMatch = Test-SetEqual $result.blocked $case.expectedBlocked
    $errorMatch = ($result.errored.Count -eq 0)
    $verdictMatch = ($result.verdict -eq $case.expectedVerdict)
    $exitMatch = ($result.exitCode -eq $case.expectedExitCode)
    $qualityMatch = $true
    if ($case.expectedQualityNull -and $null -ne $result.quality) {
        $qualityMatch = $false
    }

    $result.expectedVerdict = $case.expectedVerdict
    $result.expectedExitCode = $case.expectedExitCode
    $result.expectedQualityNull = $case.expectedQualityNull
    $result.expectedFailed = @($case.expectedFailed)
    $result.expectedBlocked = @($case.expectedBlocked)
    $result.verdictMatch = $verdictMatch
    $result.exitMatch = $exitMatch
    $result.qualityMatch = $qualityMatch
    $result.failedMatch = $failedMatch
    $result.blockedMatch = $blockedMatch
    $result.expectationMet = ($verdictMatch -and $exitMatch -and $qualityMatch -and $failedMatch -and $blockedMatch -and $errorMatch)
    $result.kind = $case.kind
    $result.note = $case.note

    $records.Add($result)
}

# ---------------------------------------------------------------------------
# 記録
# ---------------------------------------------------------------------------
function Format-Ids {
    param($Ids)
    $list = @($Ids)
    if ($list.Count -eq 0) {
        return '（なし）'
    }

    return ($list -join ' ')
}

Write-Host ''
Write-Host '| ケース | 種別 | 終了コード | 期待判定 | 実判定 | 品質 | 期待の不合格 | 実測の不合格 | 実測の未評価 | 期待どおりか |'
Write-Host '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |'
foreach ($r in $records) {
    $quality = if ($null -eq $r.quality) { 'null' } else { '{0:0.00}' -f $r.quality }
    $met = if ($r.expectationMet) { 'はい' } else { 'いいえ' }
    Write-Host ("| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} | {8} | {9} |" -f `
            $r.caseId, $r.kind, $r.exitCode, $r.expectedVerdict, $r.verdict, $quality, `
        (Format-Ids $r.expectedFailed), (Format-Ids $r.failed), (Format-Ids $r.blocked), $met)
}

$mismatches = @($records | Where-Object { -not $_.expectationMet })
Write-Host ''
if ($mismatches.Count -eq 0) {
    Write-Host 'すべてのケースで期待と実結果が完全に一致しました。'
}
else {
    Write-Host "期待と実結果が食い違ったケース: $($mismatches.Count) 件"
    foreach ($r in $mismatches) {
        $reasons = New-Object System.Collections.Generic.List[string]
        if (-not $r.verdictMatch) { $reasons.Add("判定 期待 $($r.expectedVerdict) / 実測 $($r.verdict)") | Out-Null }
        if (-not $r.exitMatch) { $reasons.Add("終了コード 期待 $($r.expectedExitCode) / 実測 $($r.exitCode)") | Out-Null }
        if (-not $r.qualityMatch) { $reasons.Add('品質点が null ではありません') | Out-Null }
        if (-not $r.failedMatch) { $reasons.Add("不合格 期待 $(Format-Ids $r.expectedFailed) / 実測 $(Format-Ids $r.failed)") | Out-Null }
        if (-not $r.blockedMatch) { $reasons.Add("未評価 期待 $(Format-Ids $r.expectedBlocked) / 実測 $(Format-Ids $r.blocked)") | Out-Null }
        if ($r.errored.Count -gt 0) { $reasons.Add("評価側の障害 $(Format-Ids $r.errored)") | Out-Null }
        Write-Host "  $($r.caseId): $($reasons -join '、')"
    }
}

$summaryPath = Join-Path $runs 'calibration-summary.json'
$records | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $summaryPath
Write-Host ''
Write-Host "要約を書き出しました: $summaryPath"

if ($mismatches.Count -gt 0) {
    exit 1
}