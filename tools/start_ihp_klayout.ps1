param(
    [string]$Layout = "",
    [string]$Workspace = "",
    [string]$KLayout = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pdkRoot = Join-Path $repoRoot "external\ihp_pdk"
$pdkPath = Join-Path $pdkRoot "ihp-sg13g2"
$klayoutTech = Join-Path $pdkPath "libs.tech\klayout"
$pycellApi = Join-Path $klayoutTech "python\pycell4klayout-api\source\python\cni\dlo.py"
$preprocessor = Join-Path $klayoutTech "python\pypreprocessor\pypreprocessor\__init__.py"

if (-not (Test-Path -LiteralPath $pycellApi) -or -not (Test-Path -LiteralPath $preprocessor)) {
    throw @"
IHP SG13_dev PCell dependencies are missing.
From the repository root, initialize the pinned nested submodules:
  git -C external/ihp_pdk submodule update --init `
    ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api `
    ihp-sg13g2/libs.tech/klayout/python/pypreprocessor
"@
}

if (-not $Workspace) {
    $Workspace = Join-Path $repoRoot "workspace"
}
$Workspace = [System.IO.Path]::GetFullPath($Workspace)
$klayoutHome = Join-Path $Workspace ".klayout"
$pycache = Join-Path $Workspace ".cache\klayout_pycache"
New-Item -ItemType Directory -Force -Path $klayoutHome, $pycache | Out-Null

if (-not $KLayout) {
    $candidates = @(
        (Get-Command klayout_app -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Get-Command klayout -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "C:\Program Files\KLayout\klayout_app.exe",
        "C:\Program Files\KLayout\klayout.exe",
        (Join-Path $repoRoot "tools\KLayoutPortable\klayout_app.exe")
    )
    $KLayout = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $KLayout -or -not (Test-Path -LiteralPath $KLayout)) {
    throw "KLayout was not found. Pass -KLayout C:\path\to\klayout_app.exe"
}

$env:PDK_ROOT = $pdkRoot
$env:PDK = "ihp-sg13g2"
$env:PDKPATH = $pdkPath
$env:STD_CELL_LIBRARY = "sg13g2_stdcell"
$env:KLAYOUT_HOME = $klayoutHome
$env:PYTHONPYCACHEPREFIX = $pycache
$env:KLAYOUT_PATH = (@($klayoutHome, $klayoutTech, (Join-Path $klayoutTech "tech")) |
    Where-Object { $_ }) -join [System.IO.Path]::PathSeparator
$env:PYTHONPATH = (@((Join-Path $klayoutTech "python"),
    (Join-Path $klayoutTech "python\pycell4klayout-api\source\python")) |
    Where-Object { $_ }) -join [System.IO.Path]::PathSeparator
$env:Path = "$(Split-Path -Parent $KLayout)$([System.IO.Path]::PathSeparator)$env:Path"

$arguments = @("-e", "-n", "sg13g2")
if ($Layout) {
    $layoutPath = [System.IO.Path]::GetFullPath($Layout)
    if (-not (Test-Path -LiteralPath $layoutPath)) {
        throw "Layout file not found: $layoutPath"
    }
    $arguments += $layoutPath
}

Write-Host "Starting IHP SG13G2 KLayout (edit mode)"
Write-Host "  PDK:       $pdkPath"
Write-Host "  Workspace: $Workspace"
Write-Host "  PCells:    SG13_dev"
Start-Process -FilePath $KLayout -ArgumentList $arguments -WorkingDirectory $Workspace
