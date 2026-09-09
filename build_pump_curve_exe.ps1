$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path $projectRoot 'pump_curve_web\frontend'
$specPath = Join-Path $projectRoot 'pump_curve_web\pump_curve_app.spec'

Push-Location $frontendRoot
try {
    npm.cmd install
    $env:VITE_API_BASE = ''
    npm.cmd run build
}
finally {
    Pop-Location
}

Push-Location $projectRoot
try {
    python -m PyInstaller $specPath --clean --noconfirm
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host 'Build complete: dist\pump_curve_app\pump_curve_app.exe'
Write-Host 'Copy pump_curve_web\pump_app_config.template.json to the EXE directory as pump_app_config.json and fill in database settings.'
