$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'docker-command.ps1')
Invoke-NbsDocker compose -f compose.test.yaml config --quiet
try {
    Invoke-NbsDocker compose -f compose.test.yaml up -d --build --wait --wait-timeout 180 app
    Invoke-NbsDocker compose -f compose.test.yaml run --rm check seed
    Invoke-NbsDocker compose -f compose.test.yaml down
    Invoke-NbsDocker compose -f compose.test.yaml up -d --no-build --wait --wait-timeout 120 app
    Invoke-NbsDocker compose -f compose.test.yaml run --rm check verify
    Write-Output 'Docker検証成功: ログイン・回答登録・集計・Excel・コンテナ作り直し後のデータ保持。'
} finally {
    & $script:NbsDocker compose -f compose.test.yaml down
}
