$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'docker-command.ps1')
$filename = 'survey-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.sqlite3'
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'backups') -Force | Out-Null
Invoke-NbsDocker compose exec -T app python data_transfer.py /data/survey.sqlite3 ('/data/backups/' + $filename)
Invoke-NbsDocker compose cp ('app:/data/backups/' + $filename) (Join-Path $PSScriptRoot ('backups/' + $filename))
Write-Output ('バックアップを保存しました: backups/' + $filename)
