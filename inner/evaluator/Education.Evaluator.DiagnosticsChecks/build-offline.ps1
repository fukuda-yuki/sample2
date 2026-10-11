param(
    [Parameter(Mandatory=$true)][string]$DependencyDirectory,
    [Parameter(Mandatory=$true)][string]$BuildRoot,
    [string]$ProductReceipt
)
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$repoRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$dependencyRoot=(Resolve-Path -LiteralPath $DependencyDirectory).Path
$buildDirectory=[System.IO.Path]::GetFullPath($BuildRoot)
if($buildDirectory.StartsWith($dependencyRoot,[System.StringComparison]::OrdinalIgnoreCase) -or $dependencyRoot.StartsWith($buildDirectory,[System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must be separate from dependency originals.'
}
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
$env:TEMP=Join-Path $buildDirectory 'temp'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:TMP=$env:TEMP
$env:DOTNET_CLI_HOME=$env:TEMP
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
$evaluatorProject=Join-Path $repoRoot 'inner/evaluator/Education.Evaluator/Education.Evaluator.csproj'
$checksProject=Join-Path $PSScriptRoot 'Education.Evaluator.DiagnosticsChecks.csproj'
$binaryDirectory=Join-Path $buildDirectory 'compile-bin'
$intermediateDirectory=(Join-Path $buildDirectory 'compile-obj')+'/'
$commands=@()
Push-Location $repoRoot
try {
    $sdk=(& dotnet --version).Trim()
    if($sdk -ne '8.0.425'){throw 'Acceptance requires the repository-pinned SDK 8.0.425.'}
    foreach($number in 1,2) {
        $arguments=@('build',$evaluatorProject,'-t:Rebuild','-c','Release','-p:UseSharedCompilation=false',"-p:OfflineReferenceDirectory=$dependencyRoot","-p:BaseIntermediateOutputPath=$intermediateDirectory","-p:OutputPath=$binaryDirectory/")
        $commands+=@{operation='standalone_rebuild';build=$number;arguments=$arguments}
        & dotnet @arguments 2>&1 | Tee-Object -FilePath (Join-Path $buildDirectory "build-$number.log")
        if($LASTEXITCODE -ne 0){throw "Standalone build $number failed."}
        $saved=Join-Path $buildDirectory "build-$number"
        New-Item -ItemType Directory -Path $saved -Force | Out-Null
        foreach($name in 'Education.Evaluator.dll','Education.Evaluator.pdb') {
            Copy-Item -LiteralPath (Join-Path $binaryDirectory $name) -Destination (Join-Path $saved $name)
        }
    }
    foreach($name in 'Education.Evaluator.dll','Education.Evaluator.pdb') {
        if((Get-FileHash -LiteralPath (Join-Path $buildDirectory "build-1/$name")).Hash -ne (Get-FileHash -LiteralPath (Join-Path $buildDirectory "build-2/$name")).Hash){throw "Repeat build differs: $name"}
    }
    $checksBinary=Join-Path $buildDirectory 'checks-bin'
    $arguments=@('build',$checksProject,'-c','Release','-p:UseSharedCompilation=false',"-p:OfflineReferenceDirectory=$dependencyRoot","-p:EvaluatorAssemblyPath=$binaryDirectory/Education.Evaluator.dll","-p:BaseIntermediateOutputPath=$buildDirectory/checks-obj/","-p:OutputPath=$checksBinary/")
    $commands+=@{operation='checks_build';arguments=$arguments}
    & dotnet @arguments 2>&1 | Tee-Object -FilePath (Join-Path $buildDirectory 'checks-build.log')
    if($LASTEXITCODE -ne 0){throw 'Diagnostics build failed.'}
    $checkArguments=@((Join-Path $checksBinary 'Education.Evaluator.DiagnosticsChecks.dll'))
    if($ProductReceipt){$checkArguments+=@('--product-receipt',(Resolve-Path -LiteralPath $ProductReceipt).Path)}
    $commands+=@{operation='checks';arguments=$checkArguments}
    & dotnet @checkArguments 2>&1 | Tee-Object -FilePath (Join-Path $buildDirectory 'checks.log')
    if($LASTEXITCODE -ne 0){throw 'Diagnostics assertions failed.'}
    $bundle=Join-Path $buildDirectory 'linux-bundle'
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    $dependencies=@()
    foreach($file in Get-ChildItem -LiteralPath $dependencyRoot -File -Recurse) {
        $relative=[System.IO.Path]::GetRelativePath($dependencyRoot,$file.FullName).Replace('\','/')
        if($relative -notin @('AngleSharp.dll','Microsoft.Data.Sqlite.dll','SQLitePCLRaw.core.dll','SQLitePCLRaw.batteries_v2.dll','SQLitePCLRaw.provider.e_sqlite3.dll','Education.Evaluator.deps.json','Education.Evaluator.runtimeconfig.json') -and -not $relative.StartsWith('runtimes/')){continue}
        $destination=Join-Path $bundle $relative
        New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
        $dependencies+=@{path=$relative;sha256=(Get-FileHash -LiteralPath $file.FullName).Hash.ToLowerInvariant();bytes=$file.Length}
    }
    foreach($name in 'Education.Evaluator.dll','Education.Evaluator.pdb') {Copy-Item -LiteralPath (Join-Path $binaryDirectory $name) -Destination (Join-Path $bundle $name)}
    if(-not(Test-Path -LiteralPath (Join-Path $bundle 'runtimes/linux-x64/native/libe_sqlite3.so'))){throw 'Linux x64 SQLite native dependency missing.'}
    $sources=@()
    foreach($relative in @('global.json','inner/evaluator/Education.Evaluator/Program.cs','inner/evaluator/Education.Evaluator/AppHost.cs','inner/evaluator/Education.Evaluator/Education.Evaluator.csproj','inner/evaluator/Education.Evaluator.DiagnosticsChecks/Program.cs','inner/evaluator/Education.Evaluator.DiagnosticsChecks/MarkerContractChecks.cs','inner/evaluator/Education.Evaluator.DiagnosticsChecks/Education.Evaluator.DiagnosticsChecks.csproj','inner/evaluator/Education.Evaluator.DiagnosticsChecks/build-offline.ps1')) {
        $sources+=@{path=$relative;sha256=(Get-FileHash -LiteralPath (Join-Path $repoRoot $relative)).Hash.ToLowerInvariant()}
    }
    $bundleFiles=@(Get-ChildItem -LiteralPath $bundle -Recurse -File | ForEach-Object {@{path=[System.IO.Path]::GetRelativePath($bundle,$_.FullName).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant();bytes=$_.Length}})
    $receipt=@{schema_version=1;status='accepted_finite_checks';evaluation_version='education-1.1.0';sdk=$sdk;source_identity='exact_inventory_not_a_claimed_commit';sources=$sources;dependencies=$dependencies;commands=$commands;repeat_build_identical=$true;standalone_dll_sha256=(Get-FileHash -LiteralPath (Join-Path $bundle 'Education.Evaluator.dll')).Hash.ToLowerInvariant();standalone_pdb_sha256=(Get-FileHash -LiteralPath (Join-Path $bundle 'Education.Evaluator.pdb')).Hash.ToLowerInvariant();checks_log_sha256=(Get-FileHash -LiteralPath (Join-Path $buildDirectory 'checks.log')).Hash.ToLowerInvariant();bundle_files=$bundleFiles;linux_invocation='dotnet Education.Evaluator.dll';linux_execution_verified=$false;original_run_modified=$false;model_calls=0}
    $receipt | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $buildDirectory 'build-receipt.json')
    Write-Output "Accepted offline bundle: $bundle"
} finally {Pop-Location}
