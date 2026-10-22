[CmdletBinding()]
param(
    [string]$Binary = "release\windows-x64\qoder2api-hub\qoder2api-hub.exe",
    [int]$Port = 18792
)

$ErrorActionPreference = "Stop"
$Binary = (Resolve-Path -LiteralPath $Binary).Path
$TempBase = $env:RUNNER_TEMP
if (-not $TempBase) {
    $TempBase = [IO.Path]::GetTempPath()
}
$TempRoot = Join-Path $TempBase ("qoder-binary-smoke-" + [guid]::NewGuid().ToString("N"))
$AccountsDir = Join-Path $TempRoot "accounts"
$UsageDir = Join-Path $TempRoot "usage"
$Stdout = Join-Path $TempRoot "stdout.log"
$Stderr = Join-Path $TempRoot "stderr.log"
New-Item -ItemType Directory -Force -Path $AccountsDir, $UsageDir | Out-Null
$env:QD_UPDATE_DISABLE = "1"

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -gt 0) {
        & taskkill.exe /PID $ProcessId /T /F *> $null
    }
}

function Get-HttpStatus([string]$Uri, [hashtable]$Headers = @{}) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Uri `
            -Headers $Headers -TimeoutSec 5).StatusCode
    } catch {
        return [int]$_.Exception.Response.StatusCode
    }
}

& $Binary --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "binary --help failed"
}

$Arguments = @(
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--accounts-dir", $AccountsDir,
    "--usage-dir", $UsageDir
)
$Process = Start-Process -FilePath $Binary -ArgumentList $Arguments `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr

try {
    $Ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $Ping = (Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$Port/ping" -TimeoutSec 2).Content.Trim()
            if ($Ping -eq "pong") {
                $Ready = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) {
        Get-Content -LiteralPath $Stdout, $Stderr -ErrorAction SilentlyContinue
        throw "server failed to start"
    }

    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 10
    if ($Health.version -ne "1.6.12") {
        throw "unexpected version: $($Health.version)"
    }
    $Models = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 15
    if ($Models.object -ne "list" -or $Models.data.Count -lt 1) {
        throw "models endpoint failed"
    }
    $Dashboard = (Invoke-WebRequest -UseBasicParsing `
        -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5).Content
    if ($Dashboard -notmatch "Qoder") {
        throw "dashboard failed"
    }
    $AgentsCli = (Invoke-WebRequest -UseBasicParsing `
        -Uri "http://127.0.0.1:$Port/agents/cli" -TimeoutSec 5).Content
    if ($AgentsCli -notmatch "qoder_agents") {
        throw "agents CLI data file missing"
    }
} finally {
    Stop-ProcessTree $Process.Id
}

$LanPort = $Port + 1
$LanAccounts = Join-Path $TempRoot "lan-accounts"
$LanUsage = Join-Path $TempRoot "lan-usage"
New-Item -ItemType Directory -Force -Path $LanAccounts, $LanUsage | Out-Null
$LanArguments = @(
    "--host", "0.0.0.0",
    "--port", "$LanPort",
    "--lan",
    "--api-key", "qd-smoke-test-key",
    "--accounts-dir", $LanAccounts,
    "--usage-dir", $LanUsage
)
$LanProcess = Start-Process -FilePath $Binary -ArgumentList $LanArguments `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $TempRoot "lan-stdout.log") `
    -RedirectStandardError (Join-Path $TempRoot "lan-stderr.log")

try {
    $LanReady = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $Ping = (Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$LanPort/ping" -TimeoutSec 2).Content.Trim()
            if ($Ping -eq "pong") {
                $LanReady = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $LanReady) {
        Get-Content -LiteralPath (Join-Path $TempRoot "lan-stdout.log"),
            (Join-Path $TempRoot "lan-stderr.log") -ErrorAction SilentlyContinue
        throw "LAN server failed to start"
    }
    $NoKey = Get-HttpStatus "http://127.0.0.1:$LanPort/v1/models"
    $WrongKey = Get-HttpStatus "http://127.0.0.1:$LanPort/v1/models" `
        @{ Authorization = "Bearer wrong-key" }
    $GoodKey = Get-HttpStatus "http://127.0.0.1:$LanPort/v1/models" `
        @{ Authorization = "Bearer qd-smoke-test-key" }
    if ($NoKey -ne 401 -or $WrongKey -ne 401 -or $GoodKey -ne 200) {
        throw "LAN auth matrix failed: no-key=$NoKey wrong=$WrongKey good=$GoodKey"
    }
    Write-Host "windows smoke OK"
} finally {
    Stop-ProcessTree $LanProcess.Id
}
