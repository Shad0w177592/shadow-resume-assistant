param(
    [Parameter(Mandatory = $true)]
    [string]$Installer
)

$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$target = Join-Path $workspace 'tmp\package-smoke\installed'
$targetParent = Split-Path -Parent $target

if (-not (Test-Path -LiteralPath $Installer)) {
    throw "installer not found: $Installer"
}
$smokeRoot = Join-Path $workspace 'tmp\package-smoke'
if (-not $target.StartsWith($smokeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "unsafe smoke install path: $target"
}
if (Test-Path -LiteralPath $targetParent) {
    $resolved = (Resolve-Path -LiteralPath $targetParent).Path
    if ($resolved -ne $targetParent) { throw "unexpected cleanup path: $resolved" }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $targetParent | Out-Null

$install = Start-Process -FilePath $Installer -ArgumentList @('/S', "/D=$target") -WindowStyle Hidden -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "installer exited with $($install.ExitCode)" }

$appExe = Join-Path $target '影子简历助手.exe'
$backendExe = Join-Path $target 'resources\backend\shadow-resume-backend.exe'
$webIndex = Join-Path $target 'resources\web\index.html'
foreach ($required in @($appExe, $backendExe, $webIndex)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "missing packaged file: $required" }
}

$env:SHADOW_SMOKE_TEST = '1'
$env:SHADOW_SMOKE_DATA_DIR = Join-Path $targetParent 'backend-smoke-data'
$smoke = Start-Process -FilePath $appExe -WindowStyle Hidden -Wait -PassThru
if ($smoke.ExitCode -ne 0) { throw "packaged app smoke test exited with $($smoke.ExitCode)" }
Remove-Item Env:SHADOW_SMOKE_TEST
$env:SHADOW_RENDER_SMOKE_TEST = '1'
$env:SHADOW_SMOKE_DATA_DIR = Join-Path $targetParent 'render-smoke-data'
$renderSmoke = Start-Process -FilePath $appExe -WindowStyle Hidden -Wait -PassThru
Remove-Item Env:SHADOW_RENDER_SMOKE_TEST
Remove-Item Env:SHADOW_SMOKE_DATA_DIR
if ($renderSmoke.ExitCode -ne 0) { throw "packaged frontend render test exited with $($renderSmoke.ExitCode)" }

$previousLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $targetParent 'normal-local-app-data'
$env:SHADOW_RENDER_SMOKE_TEST = '1'
$normalRenderSmoke = Start-Process -FilePath $appExe -WindowStyle Hidden -Wait -PassThru
Remove-Item Env:SHADOW_RENDER_SMOKE_TEST
$env:LOCALAPPDATA = $previousLocalAppData
if ($normalRenderSmoke.ExitCode -ne 0) { throw "normal-path frontend render test exited with $($normalRenderSmoke.ExitCode)" }

$uninstaller = Join-Path $target 'Uninstall 影子简历助手.exe'
if (Test-Path -LiteralPath $uninstaller) {
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @('/S') -WindowStyle Hidden -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw "uninstaller exited with $($uninstall.ExitCode)" }
}

[pscustomobject]@{
    Installer = $Installer
    Installed = $true
    BackendPresent = $true
    WebPresent = $true
    SmokeExitCode = $smoke.ExitCode
    RenderExitCode = $renderSmoke.ExitCode
    NormalRenderExitCode = $normalRenderSmoke.ExitCode
    Uninstalled = -not (Test-Path -LiteralPath $appExe)
}
