@echo off
setlocal EnableExtensions

set "HERE=%~dp0"
set "PIDFILE=%HERE%data\qoder2api-hub.pid"

if not exist "%PIDFILE%" goto no_pid
set /p PID=<"%PIDFILE%"
if "%PID%"=="" goto no_pid
set "QODER_PID=%PID%"

powershell -NoProfile -Command "$id=[int]$env:QODER_PID; $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id) -ErrorAction SilentlyContinue; if(-not $p){Write-Host '[INFO] not running (stale PID file)'; exit 2}; if($p.CommandLine -notmatch 'qoder2api-hub'){Write-Host ('[WARN] PID '+$id+' is not qoder2api-hub; refusing to stop'); exit 3}; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500; if(Get-Process -Id $id -ErrorAction SilentlyContinue){Write-Host '[ERROR] still running'; exit 4}; Write-Host ('[OK] stopped PID '+$id)"
set "RC=%ERRORLEVEL%"
if exist "%PIDFILE%" del "%PIDFILE%" >nul 2>nul
if "%RC%"=="3" goto end
if "%RC%"=="4" goto end
goto end

:no_pid
echo [INFO] qoder2api-hub is not running or was started without a PID file.

:end
echo.
if not "%QD_NO_PAUSE%"=="1" pause
