#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$SshHost = 'jpnote'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Installer = Join-Path $PSScriptRoot '..\Install-JpnoteWindowsClient.ps1'
$Sample = Join-Path $PSScriptRoot 'jpnote-windows-import-smoke-noop.json'

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "找不到 installer：$Installer"
}
if (-not (Test-Path -LiteralPath $Sample -PathType Leaf)) {
    throw "找不到 smoke JSON：$Sample"
}

Write-Host '=== 安裝／更新 jpnote Windows client ==='
& $Installer

$InstalledModule = Get-Module JpnoteFileImport -ListAvailable |
    Where-Object { $_.Version -eq [version]'0.7.2' } |
    Sort-Object Version -Descending |
    Select-Object -First 1
if ($null -eq $InstalledModule) {
    throw '安裝後找不到 JpnoteFileImport 0.7.2。'
}
Import-Module $InstalledModule.Path -Force -ErrorAction Stop

$SmokeDirectory = Join-Path ([System.IO.Path]::GetTempPath()) 'jpnote-windows-real-smoke'
New-Item -ItemType Directory -Path $SmokeDirectory -Force | Out-Null
$SmokePath = Join-Path $SmokeDirectory ("jpnote-smoke-$PID-" + [Guid]::NewGuid().ToString('N') + '.json')
Copy-Item -LiteralPath $Sample -Destination $SmokePath

Write-Host ''
Write-Host '=== Windows PowerShell 5.1＋SSH 實機 smoke ==='
Write-Host '接下來請依序：'
Write-Host '1. 每次 SSH 提示時輸入金鑰 passphrase。'
Write-Host '2. 確認預檢後輸入大寫 IMPORT。'
Write-Host '3. 刪除來源提示輸入 y。'
Write-Host ''

try {
    Import-JpnoteFile -Path $SmokePath -SshHost $SshHost

    if (Test-Path -LiteralPath $SmokePath) {
        throw (
            '遠端匯入已返回，但 smoke 來源檔仍存在。' +
            '請確認最後的刪除提示輸入了 y。'
        )
    }
}
finally {
    if (Test-Path -LiteralPath $SmokePath) {
        Write-Warning "保留失敗時的 smoke 檔供檢查：$SmokePath"
    }
}

Write-Host ''
Write-Host 'PASS：Windows client install／SSH protocol／no-op import／來源刪除 gate 通過。'
