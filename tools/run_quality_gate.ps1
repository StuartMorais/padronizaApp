$ErrorActionPreference = "Stop"

Write-Host "[1/7] Compilando Python..."
python -m compileall -q app tests tools

Write-Host "[2/7] Verificando módulos órfãos..."
python tools/check_dead_code.py

Write-Host "[3/7] Ruff..."
ruff check .

Write-Host "[4/7] Pyright..."
pyright

Write-Host "[5/7] Testes + cobertura do núcleo..."
pytest -q `
  --cov=app.core `
  --cov=app.domain `
  --cov=app.document `
  --cov=app.repositories `
  --cov=app.services `
  --cov-config=.coveragerc `
  --cov-report=term-missing `
  --cov-report=xml:coverage.xml `
  --cov-fail-under=75

Write-Host "[6/7] Smoke tests das telas e diálogos..."
$env:QT_QPA_PLATFORM = "offscreen"
pytest -q tests/test_gui_startup_smoke.py tests/test_ui_smoke_matrix.py

Write-Host "[7/7] Inicialização completa pelo main.py..."
$previousDataDir = $env:PADRONIZA_DATA_DIR
$smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("padroniza-quality-" + [guid]::NewGuid().ToString("N"))
try {
    $env:PADRONIZA_DATA_DIR = $smokeRoot
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
    # Force QSettings into the isolated smoke-test tree instead of touching
    # the developer/CI user's native Windows registry settings.
    Set-Content -Path (Join-Path $smokeRoot "portable.flag") -Value "quality smoke test" -Encoding UTF8
    python main.py --smoke-test
}
finally {
    if ($null -eq $previousDataDir) {
        Remove-Item Env:PADRONIZA_DATA_DIR -ErrorAction SilentlyContinue
    } else {
        $env:PADRONIZA_DATA_DIR = $previousDataDir
    }
    Remove-Item -Recurse -Force $smokeRoot -ErrorAction SilentlyContinue
}

Write-Host "Quality gate concluído com sucesso."
