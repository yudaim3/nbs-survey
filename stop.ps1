$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'docker-command.ps1')
Invoke-NbsDocker compose stop
Write-Output 'Docker版を停止しました。回答データは保存されています。'
