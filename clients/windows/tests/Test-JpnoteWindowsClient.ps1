#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "ASSERT FAILED: $Message" }
}

$WindowsRoot = Split-Path -Parent $PSScriptRoot
$Manifest = Join-Path $WindowsRoot 'JpnoteFileImport\JpnoteFileImport.psd1'
$Module = Import-Module $Manifest -Force -PassThru
try {
    Assert-True ($Module.Version.ToString() -eq '0.7.2') 'module version'
    Assert-True ($null -ne (Get-Command Test-JpnoteFile -ErrorAction Stop)) 'Test-JpnoteFile export'
    Assert-True ($null -ne (Get-Command Import-JpnoteFile -ErrorAction Stop)) 'Import-JpnoteFile export'

    $Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("jpnote-win-client-" + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $Temp | Out-Null
    try {
        $JsonPath = Join-Path $Temp '日本語.json'
        $Utf8 = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText(
            $JsonPath,
            '{"items":[{"key":"vocab:猫","type":"vocabulary","display":"猫","reading":"ねこ","meanings":["貓"]}]}',
            $Utf8
        )

        $Snapshot = & $Module { param($P) Get-JpnoteFileSnapshot -Path $P } $JsonPath
        Assert-True ($Snapshot.Text -match '猫') 'strict UTF-8 snapshot'
        Assert-True ($Snapshot.Bytes.Length -gt 0) 'snapshot bytes'
        Assert-True ($Snapshot.Sha256 -match '^[0-9a-f]{64}$') 'snapshot SHA-256'

        $Token = ('a' * 64)
        $CheckArgs = @(& $Module { Get-JpnoteSshArguments -Mode Check -SshHost 'jpnote' })
        Assert-True (($CheckArgs -join ' ') -eq 'jpnote jpnote import --stdin --protocol 1 --all --yes --check') 'check args'
        $ImportArgs = @(& $Module {
            param($T)
            Get-JpnoteSshArguments -Mode Import -SshHost 'user@arch-host' -PreflightToken $T
        } $Token)
        Assert-True (
            ($ImportArgs -join ' ') -eq (
                'user@arch-host jpnote import --stdin --protocol 1 --all --yes ' +
                '--preflight-token ' + $Token
            )
        ) 'import args'

        $MissingTokenRejected = $false
        try {
            $null = & $Module {
                Get-JpnoteSshArguments -Mode Import -SshHost 'jpnote'
            }
        }
        catch {
            $MissingTokenRejected = $true
        }
        Assert-True $MissingTokenRejected 'missing preflight token rejection'

        $Unchanged = & $Module { param($S) Test-JpnoteSourceUnchanged -Snapshot $S } $Snapshot
        Assert-True ([bool]$Unchanged) 'unchanged source'
        [System.IO.File]::AppendAllText($JsonPath, ' ', $Utf8)
        $Changed = & $Module { param($S) Test-JpnoteSourceUnchanged -Snapshot $S } $Snapshot
        Assert-True (-not [bool]$Changed) 'changed source rejection'

        $InvalidPath = Join-Path $Temp 'invalid.json'
        [System.IO.File]::WriteAllBytes($InvalidPath, [byte[]](0xFF, 0xFE, 0x00))
        $Rejected = $false
        try {
            $null = & $Module { param($P) Get-JpnoteFileSnapshot -Path $P } $InvalidPath
        }
        catch {
            $Rejected = $true
        }
        Assert-True $Rejected 'invalid UTF-8 rejection'
    }
    finally {
        Remove-Item -LiteralPath $Temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Remove-Module JpnoteFileImport -Force -ErrorAction SilentlyContinue
}

Write-Host 'jpnote Windows client tests: PASS'
