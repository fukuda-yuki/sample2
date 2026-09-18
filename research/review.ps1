param(
    [Parameter(Mandatory)][ValidateSet('explore', 'preload')][string]$Condition,
    [ValidateSet('Start', 'Stop', 'Restart')][string]$Action = 'Start',
    [ValidateSet('human', 'automation')][string]$Session = 'human'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$materialRoot = Join-Path $repoRoot 'artifacts/exploration/20260919/human-review'
$application = Join-Path $materialRoot "$Condition/application"
$reviewState = Join-Path $materialRoot "$Condition/$Session-state"
$containerName = "ms1-review-20260919-$Condition-$Session"
$imageId = 'sha256:a0bd46f3cebfc2502fe930cb50827379180b7c3f4f297d5a9e2f7201f38d5c3d'
$entryAssembly = if ($Condition -eq 'explore') { 'MvcMusicStore.Web.dll' } else { 'MvcMusicStore.dll' }
$port = if ($Condition -eq 'explore') { 18101 } else { 18102 }
if ($Session -eq 'automation') { $port += 100 }

$inspection = & docker container inspect $containerName 2>$null
$exists = $LASTEXITCODE -eq 0
if ($exists) {
    $details = ($inspection | ConvertFrom-Json)[0]
    if ($details.Config.Labels.'sample2.review' -ne 'ms1-20260919') {
        throw 'Review container ownership mismatch'
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
    if (-not (Test-Path -LiteralPath (Join-Path $application $entryAssembly))) {
        throw 'Prepared review material is missing; see the human-review guide'
    }
    New-Item -ItemType Directory -Path $reviewState -Force | Out-Null
    & docker run -d --name $containerName --label sample2.review=ms1-20260919 `
        --network bridge --publish "127.0.0.1:${port}:8080" `
        --cap-drop ALL --security-opt no-new-privileges `
        --mount "type=bind,source=$application,target=/app,readonly" `
        --mount "type=bind,source=$reviewState,target=/data" `
        --workdir /app --env ASPNETCORE_ENVIRONMENT=Production `
        --env 'ConnectionStrings__MusicStoreEntities=Data Source=/data/store.sqlite' `
        $imageId dotnet $entryAssembly --urls http://0.0.0.0:8080
    if ($LASTEXITCODE -ne 0) { throw 'Review container creation failed' }
}
if ($Action -ne 'Stop') { Write-Output "http://127.0.0.1:$port/" }
