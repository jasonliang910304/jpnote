#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$CurrentShellOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Version = '0.7.2'
$Source = Join-Path $PSScriptRoot 'JpnoteFileImport'
$SourceManifest = Join-Path $Source 'JpnoteFileImport.psd1'

if (-not (Test-Path -LiteralPath $SourceManifest -PathType Leaf)) {
    throw "找不到 Windows client module：$Source"
}

$null = Test-ModuleManifest -Path $SourceManifest -ErrorAction Stop

$Documents = [Environment]::GetFolderPath('MyDocuments')
if ([string]::IsNullOrWhiteSpace($Documents)) {
    throw '無法取得目前使用者的 Documents 目錄。'
}

$CurrentShellDirectory = if ($PSVersionTable.PSEdition -eq 'Core') {
    'PowerShell'
}
else {
    'WindowsPowerShell'
}

$ShellDirectories = if ($CurrentShellOnly) {
    @($CurrentShellDirectory)
}
else {
    @('WindowsPowerShell', 'PowerShell')
}

function Assert-NotReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "為避免覆寫連結目標，安裝路徑不可是 reparse point：$Path"
        }
    }
}

function Install-JpnoteModuleTarget {
    param([Parameter(Mandatory = $true)][string]$ShellDirectory)

    $ModuleBase = Join-Path `
        (Join-Path $Documents $ShellDirectory) `
        'Modules\JpnoteFileImport'
    $Target = Join-Path $ModuleBase $Version
    $BackupBase = Join-Path $ModuleBase '_backups'
    $Timestamp = Get-Date -Format 'yyyyMMddTHHmmssfffffff'
    $Temporary = Join-Path $ModuleBase ".install-$Version-$PID-$Timestamp"
    $VersionBackup = $null
    $LegacyBackup = $null
    $LegacyMoved = @()

    New-Item -ItemType Directory -Path $ModuleBase -Force | Out-Null
    Assert-NotReparsePoint -Path $ModuleBase

    # Prepare and validate the complete new module before moving any old install.
    if (Test-Path -LiteralPath $Temporary) {
        Remove-Item -LiteralPath $Temporary -Recurse -Force
    }
    Copy-Item -LiteralPath $Source -Destination $Temporary -Recurse
    $TemporaryManifest = Join-Path $Temporary 'JpnoteFileImport.psd1'
    $null = Test-ModuleManifest -Path $TemporaryManifest -ErrorAction Stop

    $LegacyModule = Join-Path $ModuleBase 'JpnoteFileImport.psm1'
    $LegacyManifest = Join-Path $ModuleBase 'JpnoteFileImport.psd1'

    try {
        if ((Test-Path -LiteralPath $LegacyModule) -or (Test-Path -LiteralPath $LegacyManifest)) {
            $LegacyBackup = Join-Path $BackupBase "legacy-$Timestamp"
            New-Item -ItemType Directory -Path $LegacyBackup -Force | Out-Null
            foreach ($Legacy in @($LegacyModule, $LegacyManifest)) {
                if (Test-Path -LiteralPath $Legacy) {
                    Assert-NotReparsePoint -Path $Legacy
                    $LegacyName = Split-Path -Leaf $Legacy
                    Move-Item -LiteralPath $Legacy -Destination $LegacyBackup
                    $LegacyMoved += $LegacyName
                }
            }
        }

        if (Test-Path -LiteralPath $Target) {
            Assert-NotReparsePoint -Path $Target
            New-Item -ItemType Directory -Path $BackupBase -Force | Out-Null
            $VersionBackup = Join-Path $BackupBase "$Version-$Timestamp"
            Move-Item -LiteralPath $Target -Destination $VersionBackup
        }

        Move-Item -LiteralPath $Temporary -Destination $Target
        $InstalledManifest = Join-Path $Target 'JpnoteFileImport.psd1'
        $null = Test-ModuleManifest -Path $InstalledManifest -ErrorAction Stop
    }
    catch {
        Remove-Item -LiteralPath $Temporary -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue

        if (
            -not [string]::IsNullOrWhiteSpace([string]$VersionBackup) -and
            (Test-Path -LiteralPath $VersionBackup)
        ) {
            Move-Item -LiteralPath $VersionBackup -Destination $Target
        }

        if (
            -not [string]::IsNullOrWhiteSpace([string]$LegacyBackup) -and
            (Test-Path -LiteralPath $LegacyBackup)
        ) {
            foreach ($LegacyName in $LegacyMoved) {
                $SavedLegacy = Join-Path $LegacyBackup $LegacyName
                if (Test-Path -LiteralPath $SavedLegacy) {
                    Move-Item -LiteralPath $SavedLegacy -Destination (Join-Path $ModuleBase $LegacyName)
                }
            }
        }
        throw
    }

    if (-not [string]::IsNullOrWhiteSpace([string]$LegacyBackup)) {
        Write-Host "舊版未版本化模組已備份：$LegacyBackup"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$VersionBackup)) {
        Write-Host "既有 $Version 模組已備份：$VersionBackup"
    }
    Write-Host "已安裝 jpnote Windows client $Version：$Target"
    return $Target
}

$InstalledTargets = @()
foreach ($ShellDirectory in $ShellDirectories) {
    $InstalledTargets += Install-JpnoteModuleTarget -ShellDirectory $ShellDirectory
}

$CurrentTarget = Join-Path `
    (Join-Path `
        (Join-Path $Documents $CurrentShellDirectory) `
        'Modules\JpnoteFileImport') `
    $Version
$CurrentManifest = Join-Path $CurrentTarget 'JpnoteFileImport.psd1'
Import-Module $CurrentManifest -Force -ErrorAction Stop

Write-Host ''
Write-Host '安裝驗證完成。可用命令：Test-JpnoteFile、Import-JpnoteFile'
if (-not $CurrentShellOnly) {
    Write-Host '已同時安裝 Windows PowerShell 5.1 與 PowerShell 7 的使用者模組路徑。'
}
