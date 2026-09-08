param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Find-ProjectRoot {
    # GitHub Actions always checks out a Git repository. Using Git first makes
    # this script independent of whether it lives in scripts/, scripts/build/,
    # or another nested build folder.
    try {
        $gitRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($gitRoot)) {
            return [string](Resolve-Path -LiteralPath $gitRoot).Path
        }
    }
    catch {
        # Fall back to walking upward below.
    }

    $candidate = [IO.DirectoryInfo](Resolve-Path -LiteralPath $PSScriptRoot).Path
    while ($null -ne $candidate) {
        $mainPy = Join-Path $candidate.FullName 'main.py'
        $requirements = Join-Path $candidate.FullName 'requirements.txt'
        if ((Test-Path -LiteralPath $mainPy -PathType Leaf) -and
            (Test-Path -LiteralPath $requirements -PathType Leaf)) {
            return $candidate.FullName
        }
        $candidate = $candidate.Parent
    }

    throw "Could not locate the Nexo repository root from $PSScriptRoot"
}

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw "$Message Exit code: $LASTEXITCODE"
    }
}

function Assert-File {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        throw "Required file not found: $PathValue"
    }
}

function Assert-Directory {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
        throw "Required directory not found: $PathValue"
    }
}

function Find-InnoSetupCompiler {
    $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        $candidate = @($command.Source, $command.Path, $command.Definition) |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            Select-Object -First 1
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [string](Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [string](Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

$ProjectRoot = Find-ProjectRoot
Set-Location -LiteralPath $ProjectRoot

if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "Invalid version '$Version'. Expected MAJOR.MINOR.PATCH."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
$patch = [int]$Matches[3]

$MainPy = Join-Path $ProjectRoot 'main.py'
$AssetsDir = Join-Path $ProjectRoot 'assets'
$TemplatesDir = Join-Path $ProjectRoot 'templates'
$PadronizaStylesDir = Join-Path $ProjectRoot 'app\ui\styles'
$IconPath = Join-Path $AssetsDir 'nexo.ico'
$InstallerScript = Join-Path $ProjectRoot 'installer\Nexo.iss'
$BuildDir = Join-Path $ProjectRoot 'build'
$DistDir = Join-Path $ProjectRoot 'dist'
$ReleaseDir = Join-Path $ProjectRoot 'release'

Assert-File $MainPy
Assert-File $IconPath
Assert-File $InstallerScript
Assert-Directory $AssetsDir
Assert-Directory $TemplatesDir
Assert-Directory $PadronizaStylesDir

Write-Host "Repository root: $ProjectRoot"
Write-Host "=============================================="
Write-Host " Nexo v$Version"
Write-Host " PyInstaller one-file EXE + Inno installer"
Write-Host "=============================================="

# Import pymupdf instead of fitz here to avoid the deprecation warning in the
# build preflight. The application may still use the fitz compatibility API.
python -c "import PyInstaller, PIL, PySide6, docx, pymupdf, reportlab; print('Build dependencies OK')"
Assert-LastExitCode -Message 'Build dependencies are missing.'

foreach ($path in @($BuildDir, $DistDir, $ReleaseDir)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

# Bake the release version into the app UI before PyInstaller analyzes imports.
$BuildVersionFile = Join-Path $ProjectRoot 'shell\_build_version.py'
Set-Content -LiteralPath $BuildVersionFile -Value "VERSION = `"$Version`"" -Encoding UTF8

$versionInfoPath = Join-Path $BuildDir 'nexo_version_info.txt'
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
        StringStruct('CompanyName', 'Nexo'),
        StringStruct('FileDescription', 'Nexo - Padroniza + Checklist'),
        StringStruct('FileVersion', '$Version'),
        StringStruct('InternalName', 'Nexo'),
        StringStruct('OriginalFilename', 'Nexo.exe'),
        StringStruct('ProductName', 'Nexo'),
        StringStruct('ProductVersion', '$Version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -LiteralPath $versionInfoPath -Value $versionInfo -Encoding UTF8

# IMPORTANT: all source paths passed to PyInstaller are absolute. When
# --specpath points to build/, relative --add-data paths otherwise get resolved
# relative to build/ and PyInstaller looks for build/assets, build/templates,
# etc. This is the cause of the reported CI failure.
$arguments = @(
    '--noconfirm',
    '--clean',
    '--windowed',
    '--onefile',
    '--name', 'Nexo',
    '--distpath', $DistDir,
    '--workpath', (Join-Path $BuildDir 'pyinstaller'),
    '--specpath', $BuildDir,
    '--paths', $ProjectRoot,
    '--version-file', $versionInfoPath,
    '--icon', $IconPath,
    '--add-data', "$AssetsDir;assets",
    '--add-data', "$TemplatesDir;templates",
    '--add-data', "$PadronizaStylesDir;app/ui/styles",
    '--hidden-import', 'win32com.client',
    '--hidden-import', 'pythoncom',
    '--hidden-import', 'pywintypes',
    '--log-level', 'WARN',
    $MainPy
)

Write-Host 'Running PyInstaller...'
python -m PyInstaller @arguments
Assert-LastExitCode -Message 'PyInstaller failed.'

$BuiltExe = Join-Path $DistDir 'Nexo.exe'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
    throw "Built executable not found: $BuiltExe"
}

$PortablePath = Join-Path $ReleaseDir "Nexo-v$Version.exe"
Copy-Item -LiteralPath $BuiltExe -Destination $PortablePath -Force

$iscc = Find-InnoSetupCompiler
if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    Write-Host 'Inno Setup not found; installing with Chocolatey...'
    $choco = Get-Command 'choco.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $choco) {
        throw 'Neither Inno Setup nor Chocolatey is available.'
    }
    & $choco.Source install innosetup --yes --no-progress
    Assert-LastExitCode -Message 'Could not install Inno Setup.'
    $iscc = Find-InnoSetupCompiler
}
if ([string]::IsNullOrWhiteSpace([string]$iscc)) {
    throw 'ISCC.exe could not be located.'
}

Write-Host 'Building installer...'
& $iscc "/DMyAppVersion=$Version" $InstallerScript
Assert-LastExitCode -Message 'Inno Setup failed.'

$InstallerPath = Join-Path $ReleaseDir "Nexo-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer not found: $InstallerPath"
}

$ChecksumPath = Join-Path $ReleaseDir 'SHA256SUMS.txt'
$checksumLines = foreach ($asset in @($InstallerPath, $PortablePath)) {
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $asset
    "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($asset))"
}
Set-Content -LiteralPath $ChecksumPath -Value $checksumLines -Encoding ASCII

function To-GitHubPath([string]$PathValue) {
    return ((Resolve-Path -LiteralPath $PathValue).Path -replace '\\', '/')
}

if (-not [string]::IsNullOrWhiteSpace([string]$env:GITHUB_OUTPUT)) {
    @(
        "portable_path=$(To-GitHubPath $PortablePath)",
        "installer_path=$(To-GitHubPath $InstallerPath)",
        "checksum_path=$(To-GitHubPath $ChecksumPath)"
    ) | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}

Write-Host 'Release files:'
Get-ChildItem -LiteralPath $ReleaseDir -File | Sort-Object Name | ForEach-Object {
    Write-Host " - $($_.FullName)"
}
