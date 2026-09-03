param(
    [Parameter(Mandatory = $true)][string]$PackageDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$appExe = Join-Path $package '影子简历助手.exe'
foreach ($relative in @('影子简历助手.exe', 'resources\app.asar', 'resources\backend\shadow-resume-backend.exe', 'resources\web\index.html')) {
    if (-not (Test-Path -LiteralPath (Join-Path $package $relative))) { throw "Missing packaged file: $relative" }
}
$actualVersion = (Get-Item -LiteralPath $appExe).VersionInfo.ProductVersion
if ($actualVersion -notin @($ExpectedVersion, "$ExpectedVersion.0")) { throw "Expected $ExpectedVersion, got $actualVersion" }
$smokeRoot = Join-Path $workspace ('tmp\release-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
$previousData = $env:SHADOW_SMOKE_DATA_DIR
$previousBackend = $env:SHADOW_SMOKE_TEST
$previousRender = $env:SHADOW_RENDER_SMOKE_TEST
try {
    foreach ($mode in @('backend', 'render')) {
        $env:SHADOW_SMOKE_DATA_DIR = Join-Path $smokeRoot $mode
        New-Item -ItemType Directory -Path $env:SHADOW_SMOKE_DATA_DIR | Out-Null
        $env:SHADOW_SMOKE_TEST = if ($mode -eq 'backend') { '1' } else { '0' }
        $env:SHADOW_RENDER_SMOKE_TEST = if ($mode -eq 'render') { '1' } else { '0' }
        $process = Start-Process -FilePath $appExe -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(45000)) {
            Stop-Process -Id $process.Id -Force
            throw "$mode smoke test timed out"
        }
        if ($process.ExitCode -ne 0) { throw "$mode smoke test failed: $($process.ExitCode)" }
        if (-not (Test-Path -LiteralPath (Join-Path $env:SHADOW_SMOKE_DATA_DIR 'data\app.db'))) {
            throw "$mode smoke test did not initialize an isolated database"
        }
        Write-Output "$mode smoke test passed"
    }
} finally {
    $env:SHADOW_SMOKE_DATA_DIR = $previousData
    $env:SHADOW_SMOKE_TEST = $previousBackend
    $env:SHADOW_RENDER_SMOKE_TEST = $previousRender
}
Write-Output "Verified release $actualVersion with isolated data at $smokeRoot"
