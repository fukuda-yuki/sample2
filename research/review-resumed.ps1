param(
    [Parameter(Mandatory)][ValidateSet('explore', 'preload', 'explained')][string]$Condition,
    [ValidateSet('Start', 'Stop', 'Restart')][string]$Action = 'Start',
    [ValidateSet('human', 'automation')][string]$Session = 'human'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$materialRoot = Join-Path $repoRoot 'artifacts/exploration/20260919/human-review-resumed-v1'
$receiptPath = Join-Path $materialRoot 'review-targets.json'
if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'Post-exploration review materials are not prepared yet' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$target = $receipt.targets | Where-Object { $_.condition -eq $Condition }
if ($target.material_state -ne 'prepared') { throw 'No application is available for this condition; inspect failure records' }
$application = Join-Path $materialRoot "$Condition/application"
$reviewState = Join-Path $materialRoot "$Condition/$Session-state"
$containerName = "ms1-review-20260919-r1-$Condition-$Session"
$imageId = 'sha256:a0bd46f3cebfc2502fe930cb50827379180b7c3f4f297d5a9e2f7201f38d5c3d'
$port = @{ explore=18201; preload=18202; explained=18203 }[$Condition]
if ($Session -eq 'automation') { $port += 100 }
$inspection = & docker container inspect $containerName 2>$null
$exists = $LASTEXITCODE -eq 0
if ($exists) {
    $details = ($inspection | ConvertFrom-Json)[0]
    if ($details.Config.Labels.'sample2.review' -ne 'ms1-20260919-r1' -or
        $details.Config.Labels.'sample2.review.instance' -ne $target.run_instance_id) {
        throw 'Review container ownership or target identity mismatch'
    }
}
if ($Action -in @('Stop', 'Restart')) {
    if (-not $exists) { throw 'This review container does not exist' }
    & docker $Action.ToLowerInvariant() $containerName
    if ($LASTEXITCODE -ne 0) { throw "Docker $Action failed" }
} elseif ($exists) {
    & docker start $containerName
    if ($LASTEXITCODE -ne 0) { throw 'Review start failed' }
} else {
    foreach ($file in ($receipt.files | Where-Object { $_.condition -eq $Condition })) {
        $relativeFile = [System.IO.Path]::GetRelativePath($target.application, $file.destination)
        $currentFile = [System.IO.Path]::GetFullPath((Join-Path $application $relativeFile))
        if (-not $currentFile.StartsWith([System.IO.Path]::GetFullPath($application) + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Review receipt file escapes the relocated application'
        }
        if ((Get-FileHash -LiteralPath $currentFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) {
            throw 'Prepared review copy changed'
        }
    }
    New-Item -ItemType Directory -Path $reviewState -Force | Out-Null
    & docker run -d --name $containerName --label sample2.review=ms1-20260919-r1 `
        --label "sample2.review.instance=$($target.run_instance_id)" `
        --network bridge --publish "127.0.0.1:${port}:8080" `
        --cap-drop ALL --security-opt no-new-privileges `
        --mount "type=bind,source=$application,target=/app,readonly" `
        --mount "type=bind,source=$reviewState,target=/data" `
        --workdir /app --env ASPNETCORE_ENVIRONMENT=Production `
        --env 'ConnectionStrings__MusicStoreEntities=Data Source=/data/store.sqlite' `
        $imageId dotnet $target.entry_assembly --urls http://0.0.0.0:8080
    if ($LASTEXITCODE -ne 0) { throw 'Review container creation failed' }
}
if ($Action -ne 'Stop') { Write-Output "http://127.0.0.1:$port/" }
