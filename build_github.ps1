$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Set-Location $PSScriptRoot

$projectRoot = $PSScriptRoot


# ------------------------------------------------------------
# Funções auxiliares
# ------------------------------------------------------------

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Message Código de saída: $LASTEXITCODE."
    }
}


function Find-InnoSetupCompiler {
    $command = Get-Command `
        "ISCC.exe" `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($null -ne $command) {
        $commandPath = @(
            [string]$command.Source,
            [string]$command.Path,
            [string]$command.Definition
        ) |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_)
            } |
            Select-Object -First 1

        if (
            -not [string]::IsNullOrWhiteSpace($commandPath) -and
            (Test-Path -LiteralPath $commandPath -PathType Leaf)
        ) {
            return [string](
                Resolve-Path -LiteralPath $commandPath
            ).Path
        }
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if (
            -not [string]::IsNullOrWhiteSpace($candidate) -and
            (Test-Path -LiteralPath $candidate -PathType Leaf)
        ) {
            return [string](
                Resolve-Path -LiteralPath $candidate
            ).Path
        }
    }

    return $null
}


# ------------------------------------------------------------
# Versão
# ------------------------------------------------------------

$version = [string]$env:APP_VERSION

if ([string]::IsNullOrWhiteSpace($version)) {
    $version = "1.0.0"
}

$version = $version.Trim()
$version = $version -replace "^[vV]-?", ""

if ($version -notmatch "^\d+\.\d+\.\d+$") {
    throw "Versão inválida: '$version'. Use o formato 1.5.0."
}

Write-Host ""
Write-Host "=============================================="
Write-Host " Padroniza v$version"
Write-Host "=============================================="
Write-Host ""


# ------------------------------------------------------------
# Dependências
# ------------------------------------------------------------

Write-Host "Atualizando o pip..."

python -m pip install --upgrade pip

Assert-LastExitCode `
    -Message "Não foi possível atualizar o pip."


Write-Host "Instalando as dependências do aplicativo..."

python -m pip install -r requirements.txt

Assert-LastExitCode `
    -Message "Não foi possível instalar requirements.txt."


Write-Host "Instalando as dependências de compilação..."

python -m pip install -r requirements-build.txt

Assert-LastExitCode `
    -Message "Não foi possível instalar requirements-build.txt."


Write-Host "Garantindo a instalação do Pillow..."

python -m pip install --upgrade Pillow

Assert-LastExitCode `
    -Message "Não foi possível instalar o Pillow."


# ------------------------------------------------------------
# Limpeza
# ------------------------------------------------------------

Write-Host "Limpando compilações anteriores..."

$pathsToRemove = @(
    "build",
    "dist",
    "release"
)

foreach ($pathToRemove in $pathsToRemove) {
    if (Test-Path -LiteralPath $pathToRemove) {
        Remove-Item `
            -LiteralPath $pathToRemove `
            -Recurse `
            -Force
    }
}

Get-ChildItem `
    -Path $projectRoot `
    -Filter "*.spec" `
    -File `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force

New-Item `
    -ItemType Directory `
    -Path "release" `
    -Force |
    Out-Null


# ------------------------------------------------------------
# Converter PNG para ICO
# ------------------------------------------------------------

$assetsDirectory = Join-Path `
    $projectRoot `
    "assets"

$pngIconPath = Join-Path `
    $assetsDirectory `
    "padroniza.png"

$icoIconPath = Join-Path `
    $assetsDirectory `
    "padroniza.ico"


if (Test-Path -LiteralPath $pngIconPath -PathType Leaf) {
    Write-Host "Convertendo assets\padroniza.png para ICO..."

    if (Test-Path -LiteralPath $icoIconPath -PathType Leaf) {
        Remove-Item `
            -LiteralPath $icoIconPath `
            -Force
    }

    $iconConversionScript = @'
from pathlib import Path

from PIL import Image


SOURCE = Path("assets/padroniza.png")
TARGET = Path("assets/padroniza.ico")

CANVAS_SIZE = 1024

# Ampliação visual aproximada de 60%.
SCALE_FACTOR = 1.60

# Margem mínima para evitar cortes no Windows.
MAX_CONTENT_RATIO = 0.94


if not SOURCE.is_file():
    raise FileNotFoundError(
        f"Ícone PNG não encontrado: {SOURCE}"
    )


with Image.open(SOURCE) as original:
    image = original.convert("RGBA")

    if image.width <= 0 or image.height <= 0:
        raise ValueError(
            "O PNG possui dimensões inválidas."
        )

    # Localiza apenas a área visível do PNG.
    alpha_channel = image.getchannel("A")
    visible_box = alpha_channel.getbbox()

    if visible_box is None:
        raise ValueError(
            "O PNG está completamente transparente."
        )

    visible_logo = image.crop(visible_box)

    logo_width, logo_height = visible_logo.size

    if logo_width <= 0 or logo_height <= 0:
        raise ValueError(
            "O PNG não contém uma área visível válida."
        )

    # Mede quanto o logotipo ocupava dentro do PNG original.
    source_reference_size = max(
        image.width,
        image.height,
    )

    visible_reference_size = max(
        logo_width,
        logo_height,
    )

    original_content_ratio = (
        visible_reference_size /
        source_reference_size
    )

    # Aumenta a ocupação visual em aproximadamente 60%.
    target_content_ratio = min(
        original_content_ratio * SCALE_FACTOR,
        MAX_CONTENT_RATIO,
    )

    target_reference_size = max(
        1,
        round(
            CANVAS_SIZE *
            target_content_ratio
        ),
    )

    resize_scale = (
        target_reference_size /
        visible_reference_size
    )

    resized_width = max(
        1,
        round(logo_width * resize_scale),
    )

    resized_height = max(
        1,
        round(logo_height * resize_scale),
    )

    resampling_container = getattr(
        Image,
        "Resampling",
        Image,
    )

    resized_logo = visible_logo.resize(
        (resized_width, resized_height),
        resampling_container.LANCZOS,
    )

    canvas = Image.new(
        "RGBA",
        (CANVAS_SIZE, CANVAS_SIZE),
        (0, 0, 0, 0),
    )

    position = (
        (CANVAS_SIZE - resized_width) // 2,
        (CANVAS_SIZE - resized_height) // 2,
    )

    # Compatível com as versões atuais e anteriores do Pillow.
    canvas.paste(
        resized_logo,
        position,
        resized_logo.getchannel("A"),
    )

    canvas.save(
        TARGET,
        format="ICO",
        sizes=[
            (16, 16),
            (20, 20),
            (24, 24),
            (32, 32),
            (40, 40),
            (48, 48),
            (64, 64),
            (96, 96),
            (128, 128),
            (256, 256),
        ],
    )


if not TARGET.is_file():
    raise RuntimeError(
        f"O arquivo ICO não foi criado: {TARGET}"
    )


if TARGET.stat().st_size <= 0:
    raise RuntimeError(
        f"O arquivo ICO foi criado vazio: {TARGET}"
    )


print(
    f"Ícone ampliado e criado com sucesso: {TARGET}"
)
'@

    $iconConversionScript | python -

    Assert-LastExitCode `
        -Message "Não foi possível converter o ícone PNG para ICO."
}
else {
    Write-Warning "O arquivo assets\padroniza.png não foi encontrado."
}


$hasApplicationIcon = Test-Path `
    -LiteralPath $icoIconPath `
    -PathType Leaf

if ($hasApplicationIcon) {
    Write-Host "Ícone disponível: assets\padroniza.ico"
}
else {
    Write-Warning "O aplicativo será compilado com o ícone padrão."
}


# ------------------------------------------------------------
# Argumentos comuns do PyInstaller
# ------------------------------------------------------------

$commonArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed"
)

$dataDirectories = @(
    @{
        Source = "app\styles"
        Target = "app\styles"
    },
    @{
        Source = "templates"
        Target = "templates"
    },
    @{
        Source = "examples"
        Target = "examples"
    },
    @{
        Source = "assets"
        Target = "assets"
    }
)

foreach ($dataDirectory in $dataDirectories) {
    $sourcePath = [string]$dataDirectory.Source
    $targetPath = [string]$dataDirectory.Target

    if (Test-Path -LiteralPath $sourcePath) {
        $commonArguments += @(
            "--add-data",
            "$sourcePath;$targetPath"
        )
    }
}

if ($hasApplicationIcon) {
    $commonArguments += @(
        "--icon",
        $icoIconPath
    )
}


# ------------------------------------------------------------
# Compilação em pasta para o instalador
# ------------------------------------------------------------

Write-Host ""
Write-Host "Gerando a versão usada pelo instalador..."

$installerBuildArguments = @(
    "--onedir",
    "--contents-directory",
    ".",
    "--name",
    "Padroniza",
    "--distpath",
    "dist",
    "--workpath",
    "build\installer"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @installerBuildArguments

Assert-LastExitCode `
    -Message "O PyInstaller não conseguiu gerar a versão do instalador."


$installedExecutable = Join-Path `
    $projectRoot `
    "dist\Padroniza\Padroniza.exe"

if (
    -not (
        Test-Path `
            -LiteralPath $installedExecutable `
            -PathType Leaf
    )
) {
    throw "Executável do instalador não encontrado: $installedExecutable"
}


# ------------------------------------------------------------
# Localizar ou instalar o Inno Setup
# ------------------------------------------------------------

Write-Host ""
Write-Host "Localizando o Inno Setup..."

$iscc = Find-InnoSetupCompiler

if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    Write-Host "Inno Setup não encontrado. Tentando instalar..."

    $chocolateyCommand = Get-Command `
        "choco.exe" `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($null -eq $chocolateyCommand) {
        throw "Chocolatey não foi encontrado para instalar o Inno Setup."
    }

    $chocolateyPath = @(
        [string]$chocolateyCommand.Source,
        [string]$chocolateyCommand.Path,
        [string]$chocolateyCommand.Definition
    ) |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        } |
        Select-Object -First 1

    if ([string]::IsNullOrWhiteSpace($chocolateyPath)) {
        throw "O caminho do Chocolatey não pôde ser determinado."
    }

    if (
        -not (
            Test-Path `
                -LiteralPath $chocolateyPath `
                -PathType Leaf
        )
    ) {
        throw "Chocolatey não encontrado no caminho: $chocolateyPath"
    }

    & $chocolateyPath `
        install `
        innosetup `
        --yes `
        --no-progress

    Assert-LastExitCode `
        -Message "Não foi possível instalar o Inno Setup."

    $iscc = Find-InnoSetupCompiler
}

if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    throw "Não foi possível localizar o ISCC.exe do Inno Setup."
}

$iscc = [string]$iscc

if (
    -not (
        Test-Path `
            -LiteralPath $iscc `
            -PathType Leaf
    )
) {
    throw "O compilador do Inno Setup não existe no caminho: $iscc"
}

Write-Host "Inno Setup encontrado em:"
Write-Host $iscc


# ------------------------------------------------------------
# Gerar o instalador
# ------------------------------------------------------------

Write-Host ""
Write-Host "Gerando o instalador..."

$issPath = Join-Path `
    $projectRoot `
    "installer\Padroniza.iss"

if (
    -not (
        Test-Path `
            -LiteralPath $issPath `
            -PathType Leaf
    )
) {
    throw "Arquivo do Inno Setup não encontrado: $issPath"
}

$innoArguments = @(
    "/DMyAppVersion=$version"
)

if ($hasApplicationIcon) {
    $innoArguments += "/DUseAppIcon=1"
}

$innoArguments += $issPath

& $iscc @innoArguments

Assert-LastExitCode `
    -Message "O Inno Setup não conseguiu gerar o instalador."


$installerPath = Join-Path `
    $projectRoot `
    "release\Padroniza-Setup-v$version.exe"

if (
    -not (
        Test-Path `
            -LiteralPath $installerPath `
            -PathType Leaf
    )
) {
    throw "Instalador não encontrado: $installerPath"
}


# ------------------------------------------------------------
# Compilação portátil
# ------------------------------------------------------------

Write-Host ""
Write-Host "Gerando a versão portátil..."

$portableName = "Padroniza-v$version"

$portableBuildArguments = @(
    "--onefile",
    "--name",
    $portableName,
    "--distpath",
    "dist\portable",
    "--workpath",
    "build\portable"
) + $commonArguments + @(
    "main.py"
)

python -m PyInstaller @portableBuildArguments

Assert-LastExitCode `
    -Message "O PyInstaller não conseguiu gerar a versão portátil."


$portablePath = Join-Path `
    $projectRoot `
    "dist\portable\$portableName.exe"

if (
    -not (
        Test-Path `
            -LiteralPath $portablePath `
            -PathType Leaf
    )
) {
    throw "Executável portátil não encontrado: $portablePath"
}


# ------------------------------------------------------------
# Resultados para o GitHub Actions
# ------------------------------------------------------------

$githubInstallerPath = (
    Resolve-Path -LiteralPath $installerPath
).Path -replace "\\", "/"

$githubPortablePath = (
    Resolve-Path -LiteralPath $portablePath
).Path -replace "\\", "/"

if (
    -not [string]::IsNullOrWhiteSpace(
        [string]$env:GITHUB_OUTPUT
    )
) {
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
Write-Host "=============================================="
Write-Host " Compilação concluída"
Write-Host "=============================================="
Write-Host "Versão: $version"
Write-Host "Instalador: $installerPath"
Write-Host "Portátil: $portablePath"
Write-Host ""