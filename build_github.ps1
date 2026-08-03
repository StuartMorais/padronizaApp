$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Instalando dependências Python..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

Write-Host "Limpando compilações anteriores..."
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force release -ErrorAction SilentlyContinue
Remove-Item -Force Padroniza.spec -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force release | Out-Null

$commonArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "Padroniza",
    "--add-data", "app/styles;app/styles",
    "--add-data", "templates;templates",
    "--add-data", "examples;examples"
)

if (Test-Path "assets\padroniza.ico") {
    $commonArguments += @(
        "--icon",
        "assets\padroniza.ico"
    )
}

# ------------------------------------------------------------
# Versão em pasta usada pelo instalador
# ------------------------------------------------------------

Write-Host "Gerando a versão usada pelo instalador..."

$installerBuildArguments = @(
    "--onedir",
    "--contents-directory", ".",
    "--distpath", "dist",
    "--workpath", "build\installer"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @installerBuildArguments

if (-not (Test-Path "dist\Padroniza\Padroniza.exe")) {
    throw "A versão em pasta do Padroniza não foi gerada."
}

New-Item -ItemType Directory -Force "dist\Padroniza\data" | Out-Null
New-Item -ItemType Directory -Force "dist\Padroniza\output" | Out-Null
New-Item -ItemType Directory -Force "dist\Padroniza\backups" | Out-Null

# ------------------------------------------------------------
# Gerar o instalador com Inno Setup
# ------------------------------------------------------------

$isccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)

$iscc = $isccCandidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $iscc) {
    Write-Host "Inno Setup não encontrado. Instalando pelo Chocolatey..."
    choco install innosetup -y --no-progress

    $iscc = $isccCandidates |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
}

if (-not $iscc) {
    throw "Não foi possível localizar o compilador do Inno Setup."
}

Write-Host "Gerando o instalador..."
& $iscc "installer\Padroniza.iss"

$installer = Get-ChildItem "release\Padroniza-Setup-*.exe" |
    Select-Object -First 1

if (-not $installer) {
    throw "O instalador do Padroniza não foi gerado."
}

# ------------------------------------------------------------
# Versão portátil em um único arquivo EXE
# ------------------------------------------------------------

Write-Host "Gerando a versão portátil em um único arquivo..."

Remove-Item -Force Padroniza.spec -ErrorAction SilentlyContinue

$portableBuildArguments = @(
    "--onefile",
    "--distpath", "dist\portable",
    "--workpath", "build\portable"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @portableBuildArguments

$portableExecutable = "dist\portable\Padroniza.exe"

if (-not (Test-Path $portableExecutable)) {
    throw "O executável portátil do Padroniza não foi gerado."
}

Write-Host ""
Write-Host "Compilação concluída."
Write-Host "Instalador: $($installer.FullName)"
Write-Host "Portátil: $((Resolve-Path $portableExecutable).Path)"