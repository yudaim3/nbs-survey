$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'docker-command.ps1')
Invoke-NbsDocker info --format '{{.ServerVersion}}'
Invoke-NbsDocker compose -f compose.https-test.yaml config --quiet
$resultDirectory = Join-Path $PSScriptRoot 'test-results'
New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
$resultLog = Join-Path $resultDirectory ('publication-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -LiteralPath $resultLog | Out-Null
try {
    Invoke-NbsDocker compose -f compose.https-test.yaml build app
    Invoke-NbsDocker compose -f compose.https-test.yaml run --rm --no-deps init
    Invoke-NbsDocker compose -f compose.https-test.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile
    Invoke-NbsDocker compose -f compose.https-test.yaml up -d --no-build --wait --wait-timeout 180 proxy
    Invoke-NbsDocker compose -f compose.https-test.yaml run --rm --no-deps check seed
    Invoke-NbsDocker compose -f compose.https-test.yaml down
    Invoke-NbsDocker compose -f compose.https-test.yaml run --rm --no-deps --entrypoint python init /checks/backup_roundtrip.py
    Invoke-NbsDocker compose -f compose.https-test.yaml up -d --no-build --wait --wait-timeout 120 proxy
    Invoke-NbsDocker compose -f compose.https-test.yaml run --rm --no-deps check verify
    Write-Output 'PASS: HTTPS, login, answers, categories, templates, Excel, and data after container recreation.'
    Write-Output 'This validates the local test stack, not AWS/DNS/public certificate issuance.'
} catch {
    & $script:NbsDocker compose -f compose.https-test.yaml logs --tail 60
    throw
} finally {
    & $script:NbsDocker compose -f compose.https-test.yaml down
    Stop-Transcript | Out-Null
    Write-Output ('Test log: ' + $resultLog)
}
