[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ServiceName = "qoder2api-hub"
$TaskName = "Qoder2APIHub"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceBin = Join-Path $SourceRoot "qoder2api-hub.exe"
$InstallDir = Join-Path $env:ProgramFiles $ServiceName
$InstalledBin = Join-Path $InstallDir "qoder2api-hub.exe"
$DataDir = Join-Path $env:ProgramData $ServiceName
$AccountsDir = Join-Path $DataDir "accounts"
$UsageDir = Join-Path $DataDir "usage"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "install-service.ps1 must run as Administrator"
}
if (-not (Test-Path -LiteralPath $SourceBin)) {
    throw "binary not found: $SourceBin"
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AccountsDir | Out-Null
New-Item -ItemType Directory -Force -Path $UsageDir | Out-Null
Copy-Item -LiteralPath $SourceBin -Destination $InstalledBin -Force

& icacls.exe $DataDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null

$arguments = @(
    "--host", "127.0.0.1",
    "--port", "8790",
    "--accounts-dir", "`"$AccountsDir`"",
    "--usage-dir", "`"$UsageDir`"",
    "--pid-file", "`"$(Join-Path $DataDir 'qoder2api-hub.pid')`""
) -join " "

$action = New-ScheduledTaskAction -Execute $InstalledBin -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description "Qoder2API Hub gateway" | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
$state = (Get-ScheduledTask -TaskName $TaskName).State

Write-Host "[OK] scheduled task installed: $TaskName"
Write-Host "     Binary: $InstalledBin"
Write-Host "     Data:   $DataDir"
Write-Host "     State:  $state"
Write-Host "     Dashboard: http://127.0.0.1:8790/"
