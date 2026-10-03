param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory=$true)][string]$PublishedRoot,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [int]$PortA = 5051,
    [int]$PortB = 5052
)
$ErrorActionPreference = 'Stop'
$taskRepo = [System.IO.Path]::GetFullPath($RepoRoot)
$reviewRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$publishedRootPath = [System.IO.Path]::GetFullPath($PublishedRoot)
$permittedRoot = [System.IO.Path]::Combine($taskRepo, 'artifacts') + [System.IO.Path]::DirectorySeparatorChar
if (!$reviewRoot.StartsWith($permittedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Review output must be a new directory under this repository artifacts/.'
}
if (Test-Path -LiteralPath $reviewRoot) { throw 'Retain old review output; select a new output directory.' }
if ($PortA -eq $PortB -or $PortA -lt 1024 -or $PortB -lt 1024) { throw 'Use distinct localhost ports above 1023.' }
New-Item -ItemType Directory -Path $reviewRoot | Out-Null
$owners = [System.Collections.Generic.List[object]]::new()
# Child applications receive ordinary OS variables and only their test DB config.
# Environment values are never printed or written; gateway credentials are excluded.
$allowedNames = @('PATH','PATHEXT','PSMODULEPATH','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMW6432','DOTNET_ROOT','DOTNET_ROOT_X64')
foreach ($environmentName in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
    if ($allowedNames -notcontains $environmentName.ToUpperInvariant()) {
        [Environment]::SetEnvironmentVariable($environmentName, $null, 'Process')
    }
}
try {
    foreach ($variant in @('A','B')) {
        $caseRoot = Join-Path $reviewRoot $variant
        $applicationRoot = Join-Path $caseRoot 'application'
        New-Item -ItemType Directory -Path $caseRoot | Out-Null
        Copy-Item -LiteralPath (Join-Path $publishedRootPath ('published-' + $variant)) -Destination $applicationRoot -Recurse
        $database = Join-Path $caseRoot 'store.sqlite'
        $initial = Join-Path $taskRepo ('artifacts\migration-assets-v2\MS1-CONT-' + $variant + '\evaluation\initial-store.sqlite')
        Copy-Item -LiteralPath $initial -Destination $database
        $port = if ($variant -eq 'A') { $PortA } else { $PortB }
        $url = 'http://127.0.0.1:' + $port
        $assembly = Join-Path $applicationRoot 'MusicStore.Continuity.dll'
        $stdout = Join-Path $caseRoot 'application.stdout.log'
        $stderr = Join-Path $caseRoot 'application.stderr.log'
        $process = Start-Process -FilePath 'dotnet' -ArgumentList @(('"' + $assembly + '"'),'--urls',$url) -WorkingDirectory $applicationRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Environment @{
            'ConnectionStrings__MusicStoreEntities' = ('Data Source=' + $database)
            'DOTNET_CLI_TELEMETRY_OPTOUT' = '1'
            'DOTNET_NOLOGO' = '1'
            'ASPNETCORE_ENVIRONMENT' = 'Production'
        } -PassThru
        $owner = [ordered]@{variant=$variant;pid=$process.Id;assembly=$assembly;database=$database;url=$url;started_utc=$process.StartTime.ToUniversalTime().ToString('o');initial_database_sha256=(Get-FileHash -LiteralPath $initial -Algorithm SHA256).Hash.ToLowerInvariant();assembly_sha256=(Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant();credentials_passed=$false}
        $owners.Add($owner)
        $owners | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reviewRoot 'owners.json') -Encoding utf8
        $ready = $false
        $deadline = [DateTime]::UtcNow.AddSeconds(20)
        while ([DateTime]::UtcNow -lt $deadline) {
            try { $response = Invoke-WebRequest -Uri $url -TimeoutSec 2; if ($response.StatusCode -eq 200) { $ready = $true; break } } catch { }
            if ($process.HasExited) { break }
            Start-Sleep -Milliseconds 200
        }
        if (!$ready) { throw ('Reference startup failed; retain logs under ' + $caseRoot) }
    }
    [ordered]@{status='running_for_human_review';human_review='not_run';model_dispatches=0;owners=$owners;started_by_helper_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reviewRoot 'launch-receipt.json') -Encoding utf8
    foreach($owner in $owners) { Write-Output ($owner.variant + ' ' + $owner.url + ' pid=' + $owner.pid) }
    Write-Output ('Stop: & "' + (Join-Path $taskRepo 'research\Stop-MigrationReview.ps1') + '" -ReviewDirectory "' + $reviewRoot + '"')
} catch {
    [ordered]@{status='startup_failed';human_review='not_run';error=$_.Exception.Message;owners=$owners} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reviewRoot 'launch-failure.json') -Encoding utf8
    foreach($owner in $owners) {
        try { & taskkill /PID $owner.pid /T /F | Out-Null } catch { }
    }
    throw
}
