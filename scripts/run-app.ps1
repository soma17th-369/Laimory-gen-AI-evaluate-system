<#
.SYNOPSIS
    Laimory 평가 도구를 실행하고 브라우저를 연다(더블클릭 실행용).

.DESCRIPTION
    저장소 위치와 상관없이 이 스크립트 기준으로 루트를 잡고 `uv run streamlit` 을 띄운다.
    이미 같은 포트에 떠 있으면 새로 실행하지 않고 브라우저만 연다.
    창을 닫거나 Ctrl+C 를 누르면 앱이 종료된다.

    streamlit 은 headless 로 띄운다. headless 가 아니면 첫 실행 때 이메일을 묻는 프롬프트에서
    멈춰버린다. 대신 포트가 열리는 것을 확인한 뒤 이 스크립트가 브라우저를 연다.
#>

$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$port = 8501
$url = "http://localhost:$port"

$Host.UI.RawUI.WindowTitle = "Laimory 평가 도구 - $url (닫으면 종료)"

function Test-Listening {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# 이미 떠 있으면 중복 실행하지 않고 브라우저만 연다.
if (Test-Listening) {
    Write-Host "이미 실행 중입니다. 브라우저만 엽니다: $url" -ForegroundColor Yellow
    Start-Process $url
    exit 0
}

# uv 가 PATH 에 없을 수 있어 기본 설치 위치까지 확인한다.
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $uv)) {
    Write-Host "uv 를 찾지 못했습니다. https://docs.astral.sh/uv 설치 후 다시 실행하세요." -ForegroundColor Red
    exit 1
}

# AGENT.md 규칙: Windows 에서는 로컬 캐시를 쓴다.
$env:UV_CACHE_DIR = ".uv-cache"

Write-Host "Laimory 평가 도구를 시작합니다... ($url)" -ForegroundColor Cyan
Write-Host "이 창을 닫으면 앱이 종료됩니다." -ForegroundColor DarkGray

$args = @(
    "run", "streamlit", "run", "app/main.py",
    "--server.port", $port,
    "--server.headless", "true"
)
$proc = Start-Process -FilePath $uv -ArgumentList $args -NoNewWindow -PassThru

# 서버가 뜨면 브라우저를 연다(최대 60초 대기).
for ($i = 0; $i -lt 120; $i++) {
    if ($proc.HasExited) { break }
    if (Test-Listening) {
        Start-Process $url
        break
    }
    Start-Sleep -Milliseconds 500
}

$proc.WaitForExit()
exit $proc.ExitCode
