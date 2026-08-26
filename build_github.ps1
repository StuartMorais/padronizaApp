$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$projectRoot = $PSScriptRoot

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw "$Message Código de saída: $LASTEXITCODE."
    }
}

function Find-InnoSetupCompiler {
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        $candidate = @($command.Source, $command.Path, $command.Definition) |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            Select-Object -First 1
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [string](Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [string](Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

# -----------------------------------------------------------------------------
# Version
# -----------------------------------------------------------------------------
$version = [string]$env:APP_VERSION
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "APP_VERSION não foi informado pelo workflow de release."
}
$version = ($version.Trim() -replace "^[vV]-?", "")
if ($version -notmatch "^(\d+)\.(\d+)\.(\d+)$") {
    throw "Versão inválida: '$version'. Use MAJOR.MINOR.PATCH, por exemplo 1.6.2."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
$patch = [int]$Matches[3]

Write-Host ""
Write-Host "=============================================="
Write-Host " Padroniza v$version"
Write-Host " Build único: PyInstaller -> EXE + instalador"
Write-Host "=============================================="
Write-Host ""

# Dependencies are intentionally NOT installed here. GitHub Actions installs
# runtime/build requirements once before invoking this script. This keeps local
# builds deterministic and avoids the old duplicated 30+ minute install/build.
python -c "import PyInstaller, PIL, PySide6, docx, fitz, reportlab"
Assert-LastExitCode -Message "Dependências de build ausentes. Instale requirements.txt e requirements-build.txt."

# -----------------------------------------------------------------------------
# Clean output
# -----------------------------------------------------------------------------
foreach ($path in @("build", "dist", "release")) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path "build" -Force | Out-Null
New-Item -ItemType Directory -Path "release" -Force | Out-Null

Get-ChildItem -Path $projectRoot -Filter "*.spec" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force

# -----------------------------------------------------------------------------
# Application icon
# -----------------------------------------------------------------------------
$pngIconPath = Join-Path $projectRoot "assets\padroniza.png"
$icoIconPath = Join-Path $projectRoot "assets\padroniza.ico"

if (Test-Path -LiteralPath $pngIconPath -PathType Leaf) {
    Write-Host "Preparando ícone do aplicativo..."
    $iconScript = @'
from pathlib import Path
from PIL import Image

source = Path("assets/padroniza.png")
target = Path("assets/padroniza.ico")
with Image.open(source) as original:
    image = original.convert("RGBA")
    alpha = image.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise ValueError("O ícone PNG está completamente transparente.")
    logo = image.crop(box)
    canvas_size = 1024
    reference = max(logo.size)
    target_reference = max(1, round(canvas_size * min((reference / max(image.size)) * 1.60, 0.94)))
    scale = target_reference / reference
    resized = logo.resize(
        (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
        getattr(Image, "Resampling", Image).LANCZOS,
    )
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    position = ((canvas_size - resized.width) // 2, (canvas_size - resized.height) // 2)
    canvas.paste(resized, position, resized.getchannel("A"))
    canvas.save(
        target,
        format="ICO",
        sizes=[(16,16),(20,20),(24,24),(32,32),(40,40),(48,48),(64,64),(96,96),(128,128),(256,256)],
    )
'@
    $iconScript | python -
    Assert-LastExitCode -Message "Não foi possível criar assets\padroniza.ico."
}
$hasApplicationIcon = Test-Path -LiteralPath $icoIconPath -PathType Leaf

# -----------------------------------------------------------------------------
# Windows version resource: FileVersion/ProductVersion follow the GitHub release
# -----------------------------------------------------------------------------
$versionInfoPath = Join-Path $projectRoot "build\padroniza_version_info.txt"
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($major, $minor, $patch, 0),
    prodvers=($major, $minor, $patch, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Padroniza'),
        StringStruct('FileDescription', 'Padroniza'),
        StringStruct('FileVersion', '$version'),
        StringStruct('InternalName', 'Padroniza'),
        StringStruct('OriginalFilename', 'Padroniza.exe'),
        StringStruct('ProductName', 'Padroniza'),
        StringStruct('ProductVersion', '$version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -LiteralPath $versionInfoPath -Value $versionInfo -Encoding UTF8

# -----------------------------------------------------------------------------
# PyInstaller - exactly ONE build. The same one-file executable is the portable
# release asset and the payload installed by Inno Setup.
# -----------------------------------------------------------------------------
$arguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onefile",
    "--name", "Padroniza",
    "--distpath", "dist",
    "--workpath", "build\pyinstaller",
    "--version-file", $versionInfoPath,
    "--log-level", "WARN"
)

$dataDirectories = @(
    @{ Source = "app\ui\styles"; Target = "app\ui\styles" },
    @{ Source = "templates"; Target = "templates" },
    @{ Source = "examples"; Target = "examples" },
    @{ Source = "assets"; Target = "assets" },
    @{ Source = "docs"; Target = "docs" }
)
foreach ($entry in $dataDirectories) {
    if (Test-Path -LiteralPath $entry.Source) {
        $arguments += @("--add-data", "$($entry.Source);$($entry.Target)")
    }
}
if ($hasApplicationIcon) {
    $arguments += @("--icon", $icoIconPath)
}
$arguments += "main.py"

Write-Host "Executando PyInstaller uma única vez..."
python -m PyInstaller @arguments
Assert-LastExitCode -Message "O PyInstaller não conseguiu gerar Padroniza.exe."

$compiledExecutable = Join-Path $projectRoot "dist\Padroniza.exe"
if (-not (Test-Path -LiteralPath $compiledExecutable -PathType Leaf)) {
    throw "Executável não encontrado: $compiledExecutable"
}

$portablePath = Join-Path $projectRoot "release\Padroniza-v$version.exe"
Copy-Item -LiteralPath $compiledExecutable -Destination $portablePath -Force

# -----------------------------------------------------------------------------
# Inno Setup installer, packaging the exact same executable
# -----------------------------------------------------------------------------
$iscc = Find-InnoSetupCompiler
if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    Write-Host "Inno Setup não encontrado; instalando pelo Chocolatey..."
    $choco = Get-Command "choco.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $choco) {
        throw "Inno Setup e Chocolatey não estão disponíveis no runner."
    }
    & $choco.Source install innosetup --yes --no-progress
    Assert-LastExitCode -Message "Não foi possível instalar o Inno Setup."
    $iscc = Find-InnoSetupCompiler
}
if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    throw "Não foi possível localizar ISCC.exe."
}

$issPath = Join-Path $projectRoot "installer\Padroniza.iss"
$innoArguments = @("/DMyAppVersion=$version")
if ($hasApplicationIcon) {
    $innoArguments += "/DUseAppIcon=1"
}
$innoArguments += $issPath

Write-Host "Gerando instalador Inno Setup..."
& $iscc @innoArguments
Assert-LastExitCode -Message "O Inno Setup não conseguiu gerar o instalador."

$installerPath = Join-Path $projectRoot "release\Padroniza-Setup-v$version.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Instalador não encontrado: $installerPath"
}

# -----------------------------------------------------------------------------
# Checksums and GitHub Actions outputs
# -----------------------------------------------------------------------------
$checksumPath = Join-Path $projectRoot "release\SHA256SUMS.txt"
$checksumLines = @()
foreach ($asset in @($installerPath, $portablePath)) {
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $asset
    $checksumLines += "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($asset))"
}
Set-Content -LiteralPath $checksumPath -Value $checksumLines -Encoding ASCII

function To-GitHubPath([string]$PathValue) {
    return ((Resolve-Path -LiteralPath $PathValue).Path -replace "\\", "/")
}

$githubInstallerPath = To-GitHubPath $installerPath
$githubPortablePath = To-GitHubPath $portablePath
$githubChecksumPath = To-GitHubPath $checksumPath

if (-not [string]::IsNullOrWhiteSpace([string]$env:GITHUB_OUTPUT)) {
    @(
        "version=$version",
        "installer_path=$githubInstallerPath",
        "portable_path=$githubPortablePath",
        "checksum_path=$githubChecksumPath"
    ) | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}

Write-Host ""
Write-Host "=============================================="
Write-Host " Build concluído"
Write-Host "=============================================="
Write-Host "Versão:    $version"
Write-Host "Instalador: $installerPath"
Write-Host "Portátil:   $portablePath"
Write-Host "SHA-256:    $checksumPath"
Write-Host ""
