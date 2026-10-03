param([Parameter(Mandatory=$true)][string]$ReviewDirectory)
$ErrorActionPreference = 'Stop'
$reviewRoot = [System.IO.Path]::GetFullPath($ReviewDirectory)
$owners = @(Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $reviewRoot 'owners.json') | ConvertFrom-Json)
$stopped = [System.Collections.Generic.List[object]]::new()
foreach($owner in $owners) {
    $current = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$owner.pid)
    if (!$current) { $stopped.Add([ordered]@{pid=$owner.pid;status='already_stopped'}); continue }
    if (!$current.CommandLine -or !$current.CommandLine.Contains([string]$owner.assembly)) {
        throw ('PID ownership mismatch; do not stop ' + $owner.pid)
    }
    $created = $current.CreationDate.ToUniversalTime()
    # PowerShell 7.5+ ConvertFrom-Json may already materialize ISO strings as a
    # UTC DateTime. Converting that object back through a culture string loses Z.
    $expected = if ($owner.started_utc -is [DateTime]) {
        $owner.started_utc.ToUniversalTime()
    } elseif ($owner.started_utc -is [DateTimeOffset]) {
        $owner.started_utc.UtcDateTime
    } else {
        [DateTimeOffset]::Parse([string]$owner.started_utc, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
    }
    if ([Math]::Abs(($created - $expected).TotalSeconds) -gt 2) { throw ('PID generation mismatch; do not stop ' + $owner.pid) }
    & taskkill /PID $owner.pid /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw ('Owned stop failed for ' + $owner.pid) }
    $stopped.Add([ordered]@{pid=$owner.pid;status='stopped_owned_application';assembly=$owner.assembly})
}
[ordered]@{status='stopped';stopped_utc=[DateTimeOffset]::UtcNow.ToString('o');owners=$stopped;human_review='not_run';saved_databases_retained=$true;stopped_by_helper_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reviewRoot 'stop-receipt.json') -Encoding utf8
Write-Output ('Stopped only owned review applications; evidence retained in ' + $reviewRoot)
