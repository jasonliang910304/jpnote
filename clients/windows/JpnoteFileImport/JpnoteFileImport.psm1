Set-StrictMode -Version 2.0

$script:JpnoteProtocol = 'jpnote.import.v1'
$script:JpnoteProtocolVersion = 1
$script:MaxImportBytes = 16MB

function Get-JpnoteSha256Hex {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$Bytes
    )

    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $HashBytes = $Sha256.ComputeHash($Bytes)
    }
    finally {
        $Sha256.Dispose()
    }

    return ([BitConverter]::ToString($HashBytes)).Replace('-', '').ToLowerInvariant()
}

function Get-JpnoteFileSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $Resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    $FullPath = [System.IO.Path]::GetFullPath($Resolved.Path)
    $Before = Get-Item -LiteralPath $FullPath -Force -ErrorAction Stop

    if ($Before.PSIsContainer) {
        throw "匯入來源不能是資料夾：$FullPath"
    }
    if (($Before.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "為避免誤刪，不接受符號連結／reparse point：$FullPath"
    }
    if ([int64]$Before.Length -gt [int64]$script:MaxImportBytes) {
        throw "匯入來源超過大小上限 $($script:MaxImportBytes) bytes：$FullPath"
    }

    $Stream = [System.IO.File]::Open(
        $FullPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $Memory = New-Object System.IO.MemoryStream
        try {
            $Stream.CopyTo($Memory)
            $Bytes = $Memory.ToArray()
        }
        finally {
            $Memory.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
    }

    $After = Get-Item -LiteralPath $FullPath -Force -ErrorAction Stop
    if (
        [int64]$Before.Length -ne [int64]$After.Length -or
        [int64]$Before.LastWriteTimeUtc.Ticks -ne [int64]$After.LastWriteTimeUtc.Ticks -or
        [int64]$Before.CreationTimeUtc.Ticks -ne [int64]$After.CreationTimeUtc.Ticks
    ) {
        throw "匯入來源在讀取期間被修改：$FullPath"
    }

    $Utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $Text = $Utf8Strict.GetString($Bytes)
    }
    catch {
        throw "匯入來源不是有效 UTF-8：$($_.Exception.Message)"
    }

    if ($Text.Length -gt 0 -and $Text[0] -eq [char]0xFEFF) {
        $Text = $Text.Substring(1)
    }

    try {
        $null = $Text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "匯入來源不是有效 JSON：$($_.Exception.Message)"
    }

    return [pscustomobject]@{
        Path = $FullPath
        Bytes = $Bytes
        Text = $Text
        Length = [int64]$After.Length
        LastWriteTimeUtcTicks = [int64]$After.LastWriteTimeUtc.Ticks
        CreationTimeUtcTicks = [int64]$After.CreationTimeUtc.Ticks
        Sha256 = Get-JpnoteSha256Hex -Bytes $Bytes
    }
}

function Get-JpnoteSshArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Check', 'Import')]
        [string]$Mode,

        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [string]$PreflightToken
    )

    if ($SshHost -notmatch '^[A-Za-z0-9_.@-]+$') {
        throw 'SSH host／alias 只能包含英數、底線、句點、@ 與連字號。'
    }

    if (
        -not [string]::IsNullOrWhiteSpace($PreflightToken) -and
        $PreflightToken -notmatch '^[0-9a-f]{64}$'
    ) {
        throw 'preflight token 格式不正確。'
    }

    $Arguments = @(
        $SshHost,
        'jpnote',
        'import',
        '--stdin',
        '--protocol',
        '1',
        '--all',
        '--yes'
    )

    if ($Mode -eq 'Check') {
        $Arguments += '--check'
    }
    elseif ([string]::IsNullOrWhiteSpace($PreflightToken)) {
        throw '正式匯入必須帶入剛才預檢取得的 preflight token。'
    }
    else {
        $Arguments += @(
            '--preflight-token',
            $PreflightToken
        )
    }

    return $Arguments
}

function Invoke-JpnoteRemoteProtocol {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Snapshot,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Check', 'Import')]
        [string]$Mode,

        [string]$SshHost = 'jpnote',

        [string]$PreflightToken
    )

    $Ssh = Get-Command ssh.exe, ssh -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $Arguments = Get-JpnoteSshArguments `
        -Mode $Mode `
        -SshHost $SshHost `
        -PreflightToken $PreflightToken

    $Info = New-Object System.Diagnostics.ProcessStartInfo
    $Info.FileName = $Ssh.Source
    $Info.Arguments = ($Arguments -join ' ')
    $Info.UseShellExecute = $false
    $Info.CreateNoWindow = $false
    $Info.RedirectStandardInput = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $false

    try {
        $Info.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    }
    catch {
        # Older .NET Framework builds can lack this setter.  The protocol wire
        # format is ASCII-safe, so legacy console code pages still cannot corrupt it.
    }

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $Info

    try {
        if (-not $Process.Start()) {
            throw '無法啟動 ssh.exe。'
        }

        $OutputTask = $Process.StandardOutput.ReadToEndAsync()
        try {
            $Process.StandardInput.BaseStream.Write(
                $Snapshot.Bytes,
                0,
                $Snapshot.Bytes.Length
            )
            $Process.StandardInput.BaseStream.Flush()
        }
        finally {
            $Process.StandardInput.Close()
        }

        $Process.WaitForExit()
        $Stdout = $OutputTask.Result
        $ExitCode = $Process.ExitCode
    }
    finally {
        $Process.Dispose()
    }

    if ([string]::IsNullOrWhiteSpace($Stdout)) {
        throw (
            "Arch jpnote 沒有回傳 import protocol JSON（SSH exit code $ExitCode）。" +
            '請確認遠端已安裝 jpnote 0.7.2 以上，且 SSH alias 可用。'
        )
    }

    try {
        $Response = $Stdout | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw (
            '無法解析遠端 import protocol JSON；' +
            "請確認遠端 jpnote 版本與 shell 啟動輸出。原始輸出：$Stdout"
        )
    }

    if (
        $Response.protocol -ne $script:JpnoteProtocol -or
        [int]$Response.protocol_version -ne $script:JpnoteProtocolVersion
    ) {
        throw (
            "不支援的遠端 import protocol：$($Response.protocol) " +
            "version $($Response.protocol_version)"
        )
    }

    try {
        $RemoteVersion = [version]([string]$Response.jpnote_version)
    }
    catch {
        throw "遠端 jpnote version 格式無法辨識：$($Response.jpnote_version)"
    }
    if ($RemoteVersion -lt [version]'0.7.2') {
        throw "遠端 jpnote 版本過舊：$RemoteVersion；需要 0.7.2 以上。"
    }

    $ExpectedStatus = if ([bool]$Response.ok) { 'success' } else { 'error' }
    if ([string]$Response.status -ne $ExpectedStatus) {
        throw (
            "遠端 protocol status／ok 不一致：" +
            "status=$($Response.status), ok=$($Response.ok)"
        )
    }

    if (-not [bool]$Response.ok) {
        $Message = [string]$Response.error.message
        $Type = [string]$Response.error.type
        throw "Arch jpnote 拒絕匯入 [$Type]：$Message"
    }

    if ($ExitCode -ne 0) {
        throw "Arch jpnote 回傳成功 JSON，但 SSH exit code 為 $ExitCode；拒絕繼續。"
    }

    $ExpectedMode = if ($Mode -eq 'Check') { 'check' } else { 'import' }
    if ([string]$Response.mode -ne $ExpectedMode) {
        throw "遠端 protocol mode 不符：預期 $ExpectedMode，收到 $($Response.mode)"
    }

    $ResponseToken = [string]$Response.preflight_token
    if ($ResponseToken -notmatch '^[0-9a-f]{64}$') {
        throw '遠端 protocol 沒有回傳有效的 preflight token。'
    }
    if (
        $Mode -eq 'Import' -and
        -not [string]::IsNullOrWhiteSpace($PreflightToken) -and
        $ResponseToken -ne $PreflightToken
    ) {
        throw '遠端匯入結果的 preflight token 不一致；拒絕處理來源檔。'
    }

    return $Response
}

function Show-JpnotePreflightSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Response
    )

    $Summary = $Response.preflight.summary
    Write-Host (
        '預檢完成：' +
        "項目 $($Summary.items)｜" +
        "新增 $($Summary.new_items)｜" +
        "更新 $($Summary.update_items)｜" +
        "未變更 $($Summary.unchanged_items)｜" +
        "需確認 $($Summary.review_items)｜" +
        "衝突 $($Summary.conflicts)｜" +
        "作答 $($Summary.attempts)"
    )

    if (
        [int]$Summary.review_items -gt 0 -or
        [int]$Summary.conflicts -gt 0
    ) {
        throw (
            '預檢仍有需要人工處理的項目；Windows client 不會自動略過。' +
            '請先在 Arch 執行 jpnote import --check --all 並處理衝突。'
        )
    }
}

function Show-JpnoteImportSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Response
    )

    $Result = $Response.result
    Write-Host (
        '匯入完成：' +
        "新增 $($Result.added_entries)、" +
        "更新 $($Result.updated_entries)、" +
        "未變更 $($Result.unchanged_entries) 個項目；" +
        "新增 $($Result.added_attempts)、" +
        "略過 $($Result.skipped_attempts) 筆作答。"
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$Response.backup)) {
        Write-Host "Arch 自動備份：$($Response.backup)"
    }
}

function Test-JpnoteSourceUnchanged {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Snapshot
    )

    if (-not (Test-Path -LiteralPath $Snapshot.Path -PathType Leaf)) {
        return $false
    }

    $Current = Get-Item -LiteralPath $Snapshot.Path -Force -ErrorAction Stop
    if (($Current.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        return $false
    }
    if (
        [int64]$Current.Length -ne [int64]$Snapshot.Length -or
        [int64]$Current.LastWriteTimeUtc.Ticks -ne [int64]$Snapshot.LastWriteTimeUtcTicks -or
        [int64]$Current.CreationTimeUtc.Ticks -ne [int64]$Snapshot.CreationTimeUtcTicks
    ) {
        return $false
    }

    $Bytes = [System.IO.File]::ReadAllBytes($Snapshot.Path)
    return (Get-JpnoteSha256Hex -Bytes $Bytes) -eq [string]$Snapshot.Sha256
}

function Remove-JpnoteSourceIfUnchanged {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Snapshot
    )

    if (-not (Test-JpnoteSourceUnchanged -Snapshot $Snapshot)) {
        Write-Warning (
            '匯入已成功，但 Windows 來源檔已消失、被修改、被替換，' +
            "或變成連結；為避免誤刪，已保留：$($Snapshot.Path)"
        )
        return $false
    }

    try {
        Remove-Item -LiteralPath $Snapshot.Path -ErrorAction Stop
    }
    catch {
        Write-Warning (
            '匯入已成功，但刪除 Windows 來源檔失敗；' +
            "檔案已保留：$($_.Exception.Message)"
        )
        return $false
    }

    Write-Host "已刪除 Windows 匯入來源檔：$($Snapshot.Path)"
    return $true
}

function Select-JpnoteJsonFile {
    [CmdletBinding()]
    param()

    Add-Type -AssemblyName System.Windows.Forms
    $Dialog = New-Object System.Windows.Forms.OpenFileDialog
    $Dialog.Title = '選擇 jpnote JSON 匯入檔'
    $Dialog.Filter = 'jpnote JSON (*.json)|*.json|所有檔案 (*.*)|*.*'
    $Dialog.Multiselect = $false
    $Dialog.CheckFileExists = $true
    $Dialog.CheckPathExists = $true

    $Downloads = Join-Path $HOME 'Downloads'
    if (Test-Path -LiteralPath $Downloads -PathType Container) {
        $Dialog.InitialDirectory = $Downloads
    }

    try {
        if ($Dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            return $null
        }
        return $Dialog.FileName
    }
    finally {
        $Dialog.Dispose()
    }
}

function Test-JpnoteFile {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('FullName')]
        [string]$Path,

        [string]$SshHost = 'jpnote'
    )

    process {
        if ([string]::IsNullOrWhiteSpace($Path)) {
            $Path = Select-JpnoteJsonFile
            if ([string]::IsNullOrWhiteSpace($Path)) {
                Write-Host '已取消選擇檔案。'
                return
            }
        }

        $Snapshot = Get-JpnoteFileSnapshot -Path $Path
        Write-Host 'Windows 本機 UTF-8／JSON 檢查通過。'
        Write-Host "正在執行 Arch jpnote 預檢：$($Snapshot.Path)"
        $Response = Invoke-JpnoteRemoteProtocol -Snapshot $Snapshot -Mode Check -SshHost $SshHost
        Show-JpnotePreflightSummary -Response $Response
    }
}

function Import-JpnoteFile {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('FullName')]
        [string]$Path,

        [switch]$DeleteSource,
        [switch]$KeepSource,
        [string]$SshHost = 'jpnote'
    )

    process {
        if ($DeleteSource -and $KeepSource) {
            throw '不能同時使用 -DeleteSource 與 -KeepSource。'
        }
        if ([string]::IsNullOrWhiteSpace($Path)) {
            $Path = Select-JpnoteJsonFile
            if ([string]::IsNullOrWhiteSpace($Path)) {
                Write-Host '已取消選擇檔案。'
                return
            }
        }

        $Snapshot = Get-JpnoteFileSnapshot -Path $Path
        Write-Host 'Windows 本機 UTF-8／JSON 檢查通過。'
        Write-Host '正在執行 Arch jpnote 匯入預檢……'
        $Check = Invoke-JpnoteRemoteProtocol -Snapshot $Snapshot -Mode Check -SshHost $SshHost
        Show-JpnotePreflightSummary -Response $Check

        $PreflightToken = [string]$Check.preflight_token
        if ($PreflightToken -notmatch '^[0-9a-f]{64}$') {
            throw '遠端預檢沒有回傳有效的 preflight token；拒絕繼續。'
        }

        Write-Warning '下一步會修改 Arch 上的正式 jpnote 資料庫。'
        $Confirmation = Read-Host '確認預檢內容後，輸入 IMPORT'
        if ($Confirmation -cne 'IMPORT') {
            Write-Host '已取消匯入；Windows 來源檔未刪除。'
            return
        }

        if (-not (Test-JpnoteSourceUnchanged -Snapshot $Snapshot)) {
            throw 'Windows 來源檔在預檢後已變更；請重新執行匯入。'
        }

        $Response = Invoke-JpnoteRemoteProtocol `
            -Snapshot $Snapshot `
            -Mode Import `
            -SshHost $SshHost `
            -PreflightToken $PreflightToken

        Show-JpnoteImportSummary -Response $Response

        if ($KeepSource) {
            Write-Host "已保留 Windows 匯入來源檔：$($Snapshot.Path)"
            return
        }
        if ($DeleteSource) {
            $null = Remove-JpnoteSourceIfUnchanged -Snapshot $Snapshot
            return
        }

        Write-Host ''
        Write-Host '是否刪除 Windows 匯入來源檔？'
        Write-Host $Snapshot.Path
        $DeleteAnswer = Read-Host '[y/N]'
        if ($DeleteAnswer -match '^(?i:y|yes)$') {
            $null = Remove-JpnoteSourceIfUnchanged -Snapshot $Snapshot
        }
        else {
            Write-Host "已保留 Windows 匯入來源檔：$($Snapshot.Path)"
        }
    }
}

Export-ModuleMember -Function Test-JpnoteFile, Import-JpnoteFile
