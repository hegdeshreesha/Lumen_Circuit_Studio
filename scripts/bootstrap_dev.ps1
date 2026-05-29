param(
    [string]$PythonExe = "python",
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

Write-Host "[Lumen] Bootstrapping development environment..."

if (-not (Test-Path $VenvPath)) {
    & $PythonExe -m venv $VenvPath
}

$venvPython = Join-Path $VenvPath "Scripts\\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtualenv Python not found: $venvPython"
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython scripts\verify_environment.py

Write-Host "[Lumen] Environment is ready."
Write-Host "[Lumen] Activate: $VenvPath\\Scripts\\Activate.ps1"
Write-Host "[Lumen] Run app: python -m lumen"
Write-Host "[Lumen] Run tests: python -m unittest discover -s tests -v"
