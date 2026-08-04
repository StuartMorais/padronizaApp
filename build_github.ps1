$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ------------------------------------------------------------
# Versão
# ------------------------------------------------------------

$version = $env:APP_VERSION

if ([string]::IsNullOrWhiteSpace($version)) {
    $version = "1.0.0"
}

$version = $version.Trim()
$version = $version -replace "^[vV]-?", ""

if ($version -notmatch "^\d+\.\d+\.\d+$") {
    throw "Versão inválida: '$version'. Use o formato 1.5.0."
}

Write-Host "Versão da compilação: $version"

# ------------------------------------------------------------
# Dependências
# ------------------------------------------------------------

Write-Host "Instalando dependências Python..."

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

# ------------------------------------------------------------
# Limpeza
# ------------------------------------------------------------

Write-Host "Limpando compilações anteriores..."

Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force release -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Filter "*.spec" |
    Remove-Item -Force -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force release | Out-Null

# ------------------------------------------------------------
# Argumentos comuns do PyInstaller
# ------------------------------------------------------------

$commonArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--add-data", "app/styles;app/styles",
    "--add-data", "templates;templates",
    "--add-data", "examples;examples"
)

# ------------------------------------------------------------
# Ícone do aplicativo
# ------------------------------------------------------------

$pngIconPath = "assets\padroniza.png"
$icoIconPath = "assets\padroniza.ico"
$innoDefines = @()

if (Test-Path $pngIconPath) {
    Write-Host "Convertendo o ícone PNG para ICO..."

    @'
from pathlib import Path
from PIL import Image

source = Path("assets/padroniza.png")
target = Path("assets/padroniza.ico")

with Image.open(source) as image:
    image = image.convert("RGBA")
    image.save(
        target,
        format="ICO",
        sizes=[
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )

print(f"Ícone criado: {target}")
'@ | python -

    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível converter o ícone PNG para ICO."
    }
}

$innoArguments = @(
    "/DMyAppVersion=$version"
) + $innoDefines + @(
    "installer\Padroniza.iss"
)

& $iscc @innoArguments

if ($LASTEXITCODE -ne 0) {
    throw "O Inno Setup encerrou com o código $LASTEXITCODE."
}

if (Test-Path "assets") {
    $commonArguments += @(
        "--add-data",
        "assets;assets"
    )
}

if (Test-Path $icoIconPath) {
    Write-Host "Usando o ícone: $icoIconPath"

    $commonArguments += @(
        "--icon",
        $icoIconPath
    )

    $innoDefines += "/DUseAppIcon=1"
}
else {
    Write-Warning "Nenhum ícone foi encontrado."
    Write-Warning "Adicione assets\padroniza.png."
}

else {
    Write-Warning "Ícone não encontrado em $iconPath. O aplicativo será compilado com o ícone padrão."
}

# ------------------------------------------------------------
# Versão em pasta usada pelo instalador
# ------------------------------------------------------------

Write-Host "Gerando a versão usada pelo instalador..."

$installerBuildArguments = @(
    "--onedir",
    "--contents-directory", ".",
    "--name", "Padroniza",
    "--distpath", "dist\installer",
    "--workpath", "build\installer"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @installerBuildArguments

$installerApplication = "dist\installer\Padroniza\Padroniza.exe"

if (-not (Test-Path $installerApplication)) {
    throw "A versão usada pelo instalador não foi gerada."
}

$innoArguments = @(
    "/DMyAppVersion=$version"
) + $innoDefines + @(
    "installer\Padroniza.iss"
)

& $iscc @innoArguments

if ($LASTEXITCODE -ne 0) {
    throw "O Inno Setup encerrou com o código $LASTEXITCODE."
}

# ------------------------------------------------------------
# Localizar ou instalar o Inno Setup
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

# ------------------------------------------------------------
# Gerar instalador
# ------------------------------------------------------------

Write-Host "Gerando o instalador..."

& $iscc `
    "/DMyAppVersion=$version" `
    "installer\Padroniza.iss"

if ($LASTEXITCODE -ne 0) {
    throw "O Inno Setup encerrou com o código $LASTEXITCODE."
}

$installerPath = "release\Padroniza-Setup-v$version.exe"

if (-not (Test-Path $installerPath)) {
    throw "O instalador não foi encontrado: $installerPath"
}

# ------------------------------------------------------------
# Versão portátil em um único EXE
# ------------------------------------------------------------

Write-Host "Gerando a versão portátil em um único arquivo..."

$portableName = "Padroniza-v$version"

$portableBuildArguments = @(
    "--onefile",
    "--name", $portableName,
    "--distpath", "dist\portable",
    "--workpath", "build\portable"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @portableBuildArguments

$portablePath = "dist\portable\$portableName.exe"

if (-not (Test-Path $portablePath)) {
    throw "O executável portátil não foi encontrado: $portablePath"
}

# ------------------------------------------------------------
# Informar caminhos ao GitHub Actions
# ------------------------------------------------------------

$githubInstallerPath = $installerPath -replace "\\", "/"
$githubPortablePath = $portablePath -replace "\\", "/"

if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_OUTPUT)) {
    "version=$version" |
        Out-File `
            -FilePath $env:GITHUB_OUTPUT `
            -Encoding utf8 `
            -Append

    "installer_path=$githubInstallerPath" |
        Out-File `
            -FilePath $env:GITHUB_OUTPUT `
            -Encoding utf8 `
            -Append

    "portable_path=$githubPortablePath" |
        Out-File `
            -FilePath $env:GITHUB_OUTPUT `
            -Encoding utf8 `
            -Append
}

Write-Host ""
Write-Host "Compilação concluída."
Write-Host "Instalador: $installerPath"
Write-Host "Portátil: $portablePath"