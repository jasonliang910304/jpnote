# jpnote Windows client 0.7.2

這是 jpnote repository 正式維護的 Windows client。它透過既有 SSH
host／alias（預設 `jpnote`）把 strict UTF-8 JSON bytes 直接送到 Arch 的
`jpnote import --stdin --protocol 1`；不使用剪貼簿、Base64 或遠端暫存檔。

遠端需先安裝 jpnote 0.7.2 以上。client 會驗證 `jpnote.import.v1`、遠端版本、
mode、status、exit code 與 preflight token；任何不一致都 fail closed。

## 安裝

在解壓後的 `clients\windows` 目錄執行：

```powershell
powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File .\Install-JpnoteWindowsClient.ps1
```

預設同時安裝到 Windows PowerShell 5.1 與 PowerShell 7 的使用者 module
路徑。只安裝目前 shell 可加 `-CurrentShellOnly`。

## 使用

```powershell
Test-JpnoteFile
Import-JpnoteFile
```

不指定路徑會開啟 JSON 選檔器；也可直接指定：

```powershell
Test-JpnoteFile "$HOME\Downloads\jpnote.json"
Import-JpnoteFile "$HOME\Downloads\jpnote.json"
```

正式匯入會：

1. 在 Windows 以 strict UTF-8／JSON 讀取一次來源快照。
2. 遠端執行完整 preflight，並取得 `preflight_token`。
3. 仍有 review／conflict 時停止；否則要求輸入大寫 `IMPORT`。
4. 重新確認 Windows 檔案未變，帶 token 執行正式匯入。
5. 只有遠端明確成功且 token 相同後，才詢問是否刪除本機來源檔。

刪除預設 `[y/N]` 保留，也可明確指定：

```powershell
Import-JpnoteFile "$HOME\Downloads\jpnote.json" -DeleteSource
Import-JpnoteFile "$HOME\Downloads\jpnote.json" -KeepSource
```

來源上限 16 MiB。directory、reparse point、讀取／預檢後被修改或替換的檔案
都會被拒絕；刪除失敗只保留來源，不會把已成功的 Arch DB transaction 誤報為失敗。

## 自訂 SSH alias

```powershell
Import-JpnoteFile .\jpnote.json -SshHost user@arch-host
```

host／alias 只接受英數、底線、句點、`@` 與連字號。

## 移除

```powershell
powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File .\Uninstall-JpnoteWindowsClient.ps1
```

預設移除兩種 PowerShell 的精確 0.7.2 目錄，不刪 `_backups` 或其他版本。
