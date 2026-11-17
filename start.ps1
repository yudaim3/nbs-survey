param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'docker-command.ps1')
Invoke-NbsDocker info --format '{{.ServerVersion}}'
Invoke-NbsDocker compose config --quiet
Invoke-NbsDocker compose build
& (Join-Path $PSScriptRoot 'stop-python.ps1')
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data/survey.sqlite3')) {
    # Consistent snapshot of the existing DB, only if Docker has no DB yet.
    # The local source, including its admin account and survey IDs, is never changed.
    $sourceMount = (Join-Path $PSScriptRoot 'data') + ':/source:ro'
    Invoke-NbsDocker compose run --rm --no-deps --volume $sourceMount app python data_transfer.py /source/survey.sqlite3 /data/survey.sqlite3 --if-empty --offline-source
}
Invoke-NbsDocker compose up -d --wait --wait-timeout 120
$configuration = (& $script:NbsDocker compose config --format json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw '起動先ポートを読み取れませんでした。' }
$port = $configuration.services.app.ports[0].published
$url = 'http://localhost:' + $port + '/admin'
Write-Output ('起動しました: ' + $url)
if (-not $NoBrowser) { Start-Process $url }
