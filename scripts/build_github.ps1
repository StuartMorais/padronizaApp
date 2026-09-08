param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $ProjectRoot

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw "$Message Exit code: $LASTEXITCODE"
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

if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "Invalid version '$Version'. Expected MAJOR.MINOR.PATCH."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
$patch = [int]$Matches[3]

Write-Host "=============================================="
Write-Host " Office Tools v$Version"
Write-Host " PyInstaller one-file EXE + Inno installer"
Write-Host "=============================================="

python -c "import PyInstaller, PIL, PySide6, docx, fitz, reportlab; print('Build dependencies OK')"
Assert-LastExitCode -Message 'Build dependencies are missing.'

foreach ($path in @('build', 'dist', 'release')) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path 'build' -Force | Out-Null
New-Item -ItemType Directory -Path 'release' -Force | Out-Null

# Bake the release version into the app UI before PyInstaller analyzes imports.
Set-Content -LiteralPath 'shell\_build_version.py' -Value "VERSION = `"$Version`"" -Encoding UTF8

$versionInfoPath = Join-Path $ProjectRoot 'build\office_tools_version_info.txt'
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
        StringStruct('CompanyName', 'Office Tools'),
        StringStruct('FileDescription', 'Office Tools - Padroniza + Checklist'),
        StringStruct('FileVersion', '$Version'),
        StringStruct('InternalName', 'OfficeTools'),
        StringStruct('OriginalFilename', 'OfficeTools.exe'),
        StringStruct('ProductName', 'Office Tools'),
        StringStruct('ProductVersion', '$Version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -LiteralPath $versionInfoPath -Value $versionInfo -Encoding UTF8

$arguments = @(
    '--noconfirm',
    '--clean',
    '--windowed',
    '--onefile',
    '--name', 'OfficeTools',
    '--distpath', 'dist',
    '--workpath', 'build\pyinstaller',
    '--specpath', 'build',
    '--version-file', $versionInfoPath,
    '--icon', 'assets\office-tools.ico',
    '--add-data', 'assets;assets',
    '--add-data', 'templates;templates',
    '--add-data', 'app\ui\styles;app\ui\styles',
    '--hidden-import', 'win32com.client',
    '--hidden-import', 'pythoncom',
    '--hidden-import', 'pywintypes',
    '--log-level', 'WARN',
    'main.py'
)

Write-Host 'Running PyInstaller...'
python -m PyInstaller @arguments
Assert-LastExitCode -Message 'PyInstaller failed.'

$BuiltExe = Join-Path $ProjectRoot 'dist\OfficeTools.exe'
if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
    throw "Built executable not found: $BuiltExe"
}

$PortablePath = Join-Path $ProjectRoot "release\OfficeTools-v$Version.exe"
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
& $iscc "/DMyAppVersion=$Version" 'installer\OfficeTools.iss'
Assert-LastExitCode -Message 'Inno Setup failed.'

$InstallerPath = Join-Path $ProjectRoot "release\OfficeTools-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer not found: $InstallerPath"
}

$ChecksumPath = Join-Path $ProjectRoot 'release\SHA256SUMS.txt'
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
Get-ChildItem 'release' -File | Sort-Object Name | ForEach-Object { Write-Host " - $($_.FullName)" }
