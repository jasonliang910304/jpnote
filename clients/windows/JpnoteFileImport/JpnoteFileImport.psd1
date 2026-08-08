@{
    RootModule = 'JpnoteFileImport.psm1'
    ModuleVersion = '0.7.2'
    GUID = '44f971f8-3c0a-4f5e-9c5b-9837cd56849f'
    Author = 'Jason Liang / OpenAI ChatGPT'
    CompanyName = 'jpnote'
    Copyright = '(c) 2026 Jason Liang'
    Description = 'Windows PowerShell client for safe jpnote import over SSH.'
    PowerShellVersion = '5.1'
    FunctionsToExport = @('Test-JpnoteFile', 'Import-JpnoteFile')
    CmdletsToExport = @()
    VariablesToExport = @()
    AliasesToExport = @()
    PrivateData = @{
        PSData = @{
            Tags = @('jpnote', 'Japanese', 'SSH', 'Import')
            ProjectUri = 'https://github.com/jasonliang910304/jpnote'
        }
    }
}
