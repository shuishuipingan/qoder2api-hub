@echo off
setlocal EnableExtensions

set "HERE=%~dp0"
set "BIN=%HERE%qoder2api-hub.exe"
set "DATA=%HERE%data"
set "ACCOUNTS=%DATA%\accounts"
set "USAGE=%DATA%\usage"
set "PIDFILE=%DATA%\qoder2api-hub.pid"
set "LOGFILE=%DATA%\qoder2api-hub.log"
set "ERRFILE=%DATA%\qoder2api-hub.err.log"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8790"

if not exist "%BIN%" (
    echo [ERROR] qoder2api-hub.exe not found next to this script.
    pause
    exit /b 1
)
if not exist "%ACCOUNTS%" mkdir "%ACCOUNTS%"
if not exist "%USAGE%" mkdir "%USAGE%"

if exist "%PIDFILE%" (
    set /p OLDPID=<"%PIDFILE%"
    if not "%OLDPID%"=="" (
        set "QODER_OLDPID=%OLDPID%"
        powershell -NoProfile -Command "$id=[int]$env:QODER_OLDPID; $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id) -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match 'qoder2api-hub'){exit 0}else{exit 1}"
        if not errorlevel 1 (
            echo [INFO] qoder2api-hub is already running ^(PID %OLDPID%^).
            echo        Dashboard: http://127.0.0.1:%PORT%/
            goto end
        )
    )
)

set "QODER_BIN=%BIN%"
set "QODER_ACCOUNTS=%ACCOUNTS%"
set "QODER_USAGE=%USAGE%"
set "QODER_PIDFILE=%PIDFILE%"
set "QODER_LOGFILE=%LOGFILE%"
set "QODER_ERRFILE=%ERRFILE%"
set "QODER_PORT=%PORT%"
set "QD_UPDATE_DISABLE=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $a=@('--host','127.0.0.1','--port',$env:QODER_PORT,'--accounts-dir',($q+$env:QODER_ACCOUNTS+$q),'--usage-dir',($q+$env:QODER_USAGE+$q),'--pid-file',($q+$env:QODER_PIDFILE+$q)); $p=Start-Process -FilePath $env:QODER_BIN -ArgumentList $a -WindowStyle Hidden -RedirectStandardOutput $env:QODER_LOGFILE -RedirectStandardError $env:QODER_ERRFILE -PassThru; Start-Sleep -Milliseconds 1800; if($p.HasExited){ Write-Host '[ERROR] process exited early'; exit 1 }; Write-Host ('[OK] started, PID ' + $p.Id)"
if errorlevel 1 (
    if exist "%ERRFILE%" type "%ERRFILE%"
    pause
    exit /b 1
)

echo   API      : http://127.0.0.1:%PORT%/v1
echo   Dashboard: http://127.0.0.1:%PORT%/
echo   Data     : %DATA%
echo   Log      : %LOGFILE%

:end
echo.
if not "%QD_NO_PAUSE%"=="1" pause
