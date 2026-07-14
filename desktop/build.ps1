param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $ProjectRoot
try {
    & $Python -c "import webview, PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop dependencies are missing. Run: $Python -m pip install -r desktop/requirements.txt"
    }

    & $Python -m PyInstaller --noconfirm --clean desktop/PaperCatch.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }

    Write-Host "Built: $ProjectRoot\dist\PaperCatch\PaperCatch.exe"
}
finally {
    Pop-Location
}
