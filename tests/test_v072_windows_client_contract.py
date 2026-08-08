from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "clients" / "windows"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_powershell_files_are_bom_encoded_for_windows_powershell_51() -> None:
    files = [
        WINDOWS / "Install-JpnoteWindowsClient.ps1",
        WINDOWS / "Uninstall-JpnoteWindowsClient.ps1",
        WINDOWS / "JpnoteFileImport" / "JpnoteFileImport.psm1",
        WINDOWS / "JpnoteFileImport" / "JpnoteFileImport.psd1",
        WINDOWS / "tests" / "Test-JpnoteWindowsClient.ps1",
        WINDOWS / "tests" / "Run-JpnoteWindowsRealSmoke.ps1",
    ]
    for path in files:
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path


def test_module_uses_stdin_protocol_without_base64_or_remote_temp_file() -> None:
    module = read(WINDOWS / "JpnoteFileImport" / "JpnoteFileImport.psm1")
    lowered = module.lower()
    assert "--stdin" in module
    assert "--protocol" in module
    assert "jpnote.import.v1" in module
    assert "base64" not in lowered
    assert "mktemp" not in lowered
    assert "redirectstandardinput" in lowered
    assert "standardinput.basestream.write" in lowered


def test_module_has_local_source_safety_and_utf8_guards() -> None:
    module = read(WINDOWS / "JpnoteFileImport" / "JpnoteFileImport.psm1")
    lowered = module.lower()
    assert "reparsepoint" in lowered
    assert "utf8encoding]::new($false, $true)" in lowered
    assert "sha256" in lowered
    assert "test-jpnotesourceunchanged" in lowered
    assert "remove-jpnotesourceifunchanged" in lowered
    assert "preflight_token" in lowered
    assert "--preflight-token" in lowered
    assert "expectedstatus" in lowered
    assert "[version]'0.7.2'" in lowered
    assert "review_items" in lowered
    assert "[y/n]" in lowered


def test_manifest_and_installer_are_versioned() -> None:
    manifest = read(WINDOWS / "JpnoteFileImport" / "JpnoteFileImport.psd1")
    installer = read(WINDOWS / "Install-JpnoteWindowsClient.ps1")
    assert "ModuleVersion = '0.7.2'" in manifest
    assert "PowerShellVersion = '5.1'" in manifest
    assert "$Version = '0.7.2'" in installer
    assert "Modules\\JpnoteFileImport" in installer
    assert "_backups" in installer


def test_windows_ci_runs_both_powershell_generations() -> None:
    workflow = read(ROOT / ".github" / "workflows" / "windows-client.yml")
    assert "powershell51:" in workflow
    assert "name: Windows PowerShell 5.1" in workflow
    assert "shell: powershell" in workflow
    assert "powershell7:" in workflow
    assert "name: PowerShell 7" in workflow
    assert "shell: pwsh" in workflow
    assert "matrix.shell" not in workflow
    assert "runs-on: windows-latest" in workflow
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow


def test_real_windows_smoke_is_noop_and_exercises_source_delete() -> None:
    script = read(WINDOWS / "tests" / "Run-JpnoteWindowsRealSmoke.ps1")
    sample = read(WINDOWS / "tests" / "jpnote-windows-import-smoke-noop.json")
    assert "Import-JpnoteFile" in script
    assert "PASS：Windows client" in script
    assert "Test-Path -LiteralPath $SmokePath" in script
    assert "vocab:動作確認" in sample
    assert "Windows 匯入測試 2026-08-03" in sample
