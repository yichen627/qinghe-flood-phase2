# 用本机Word导出PDF；不修改用户正在编辑的Word文档。
$ErrorActionPreference = 'Stop'
$reportFiles = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot '..\reports') -Filter '*.docx')
if ($reportFiles.Count -ne 1) { throw 'Expected exactly one report DOCX' }
$reportSource = $reportFiles[0].FullName
$reportPdf = [IO.Path]::ChangeExtension($reportSource, '.pdf')
$wordApp = $null
$reportDocument = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $reportDocument = $wordApp.Documents.Open($reportSource, $false, $true)
    $reportDocument.Repaginate()
    $reportDocument.ExportAsFixedFormat($reportPdf, 17)
    Write-Output $reportPdf
    Write-Output "Pages: $($reportDocument.ComputeStatistics(2))"
}
finally {
    if ($null -ne $reportDocument) { $reportDocument.Close(0) }
    if ($null -ne $wordApp) { $wordApp.Quit() }
}
