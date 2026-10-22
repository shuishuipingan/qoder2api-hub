[CmdletBinding()]
param(
    [switch]$PurgeData
)

$ErrorActionPreference = "Stop"
$ServiceName = "qoder2api-hub"
$TaskName = "Qoder2APIHub"
$InstallDir = Join-Path $env:ProgramFiles $ServiceName
$DataDir = Join-Path $env:ProgramData $ServiceName

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "uninstall-service.ps1 must run as Administrator"
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

Write-Host "[OK] scheduled task removed"
Write-Host "     Preserved: $DataDir"

if ($PurgeData -and (Test-Path -LiteralPath $DataDir)) {
    $resolved = (Resolve-Path -LiteralPath $DataDir).Path
    $expected = [IO.Path]::GetFullPath((Join-Path $env:ProgramData $ServiceName))
    if ($resolved -ne $expected) {
        throw "refusing to purge unexpected path: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
    Write-Host "[OK] runtime data deleted"
}
