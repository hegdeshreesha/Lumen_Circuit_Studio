param(
    [string]$PythonExe = "python",
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $VenvPath "Scripts\\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[Lumen] Creating virtual environment at $VenvPath ..."
    & $PythonExe -m venv $VenvPath
}

if (-not (Test-Path $venvPython)) {
    throw "Virtualenv Python not found: $venvPython"
}

Write-Host "[Lumen] Installing/updating required dependencies ..."
& $venvPython -m pip install -r requirements.txt

Write-Host "[Lumen] Launching Lumen Circuit Studio ..."
& $venvPython -m lumen
