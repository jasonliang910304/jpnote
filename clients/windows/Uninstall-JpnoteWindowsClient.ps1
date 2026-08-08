#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$CurrentShellOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Version = '0.7.2'
$Documents = [Environment]::GetFolderPath('MyDocuments')
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

Remove-Module JpnoteFileImport -Force -ErrorAction SilentlyContinue

foreach ($ShellDirectory in $ShellDirectories) {
    $Target = Join-Path `
        (Join-Path `
            (Join-Path $Documents $ShellDirectory) `
            'Modules\JpnoteFileImport') `
        $Version

    if (Test-Path -LiteralPath $Target) {
        $Item = Get-Item -LiteralPath $Target -Force -ErrorAction Stop
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "拒絕移除 reparse point：$Target"
        }
        Remove-Item -LiteralPath $Target -Recurse -Force
        Write-Host "已移除 jpnote Windows client $Version：$Target"
    }
    else {
        Write-Host "找不到已安裝的 jpnote Windows client $Version：$Target"
    }
}
