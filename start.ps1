param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Get-AppxPackage -Name '*CodexPrimaryRuntime*' | Sort-Object Version -Descending | ForEach-Object { Get-Item -LiteralPath (Join-Path $_.InstallLocation 'dependencies') -ErrorAction SilentlyContinue } | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'python/python.exe') } | Select-Object -First 1
if (-not $runtime) { throw 'Codexの実行環境が見つかりません。Codexを起動してから再度お試しください。' }
$taskPython = Join-Path $runtime.FullName 'python/python.exe'
$env:AWAJI_NODE = Join-Path $runtime.FullName 'node/bin/node.exe'
$env:PYTHONIOENCODING = 'utf-8'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules/@oai/artifact-tool'))) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules')) { throw 'node_modulesの参照を修復する必要があります。Codexに依頼してください。' }
    New-Item -ItemType Junction -Path (Join-Path $PSScriptRoot 'node_modules') -Target (Join-Path $runtime.FullName 'node/node_modules') | Out-Null
}
try { $existing = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/surveys' -TimeoutSec 5 -UseBasicParsing; if ($existing.StatusCode -eq 200) { if (-not $NoBrowser) { Start-Process 'http://localhost:8765/admin' }; exit } } catch {}
Start-Process -FilePath $taskPython -ArgumentList @('server.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'server-error.log') -PassThru | Select-Object -ExpandProperty Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'server.pid')
for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try { $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/surveys' -TimeoutSec 5 -UseBasicParsing; if ($response.StatusCode -eq 200) { if (-not $NoBrowser) { Start-Process 'http://localhost:8765/admin' }; exit } } catch {}
}
throw '起動できませんでした。server-error.logを確認してください。'
