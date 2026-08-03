$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Instalando dependências Python..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

Write-Host "Limpando compilações anteriores..."
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist\Padroniza" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force release -ErrorAction SilentlyContinue
Remove-Item -Force Padroniza.spec -ErrorAction SilentlyContinue

$pyInstallerArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onefile",
    "--name", "Padroniza",
    "--add-data", "app/styles;app/styles",
    "--add-data", "templates;templates",
    "--add-data", "examples;examples"
)

if (Test-Path "assets\padroniza.ico") {
    $pyInstallerArguments += @(
        "--icon",
        "assets\padroniza.ico"
    )
}

$pyInstallerArguments += "main.py"

Write-Host "Gerando o aplicativo..."
python -m PyInstaller @pyInstallerArguments

New-Item -ItemType Directory -Force "dist\Padroniza\data" | Out-Null
New-Item -ItemType Directory -Force "dist\Padroniza\output" | Out-Null
New-Item -ItemType Directory -Force "dist\Padroniza\backups" | Out-Null
New-Item -ItemType Directory -Force release | Out-Null

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

Write-Host "Instalador gerado em: $($installer.FullName)"
