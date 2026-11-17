$ErrorActionPreference = 'Stop'
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) { $script:NbsDocker = $dockerCommand.Source }
else {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe')
    )
    $script:NbsDocker = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $script:NbsDocker) { throw 'Dockerが見つかりません。Docker導入手順.txtを確認してください。' }
function Invoke-NbsDocker {
    & $script:NbsDocker @args
    if ($LASTEXITCODE -ne 0) { throw "Dockerの処理に失敗しました（終了コード $LASTEXITCODE）。" }
}
