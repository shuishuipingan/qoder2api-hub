# Qoder2API Hub binary package for Windows

This package contains a PyInstaller executable and does not require Python.

## Run directly

Double-click `start-qoder-proxy.bat`, or run it from a terminal:

```bat
start-qoder-proxy.bat
stop-qoder-proxy.bat
```

Runtime data is stored in `data\accounts` and `data\usage` by default.

Open `http://127.0.0.1:8790/` after startup. The initial panel password is
`admin`; change it before exposing the service to a network.

## Start at boot

Run PowerShell as Administrator:

```powershell
.\install-service.ps1
```

This installs a Task Scheduler job running as SYSTEM and stores data in
`C:\ProgramData\qoder2api-hub`.

Remove the task while preserving data:

```powershell
.\uninstall-service.ps1
```

Delete service data explicitly:

```powershell
.\uninstall-service.ps1 -PurgeData
```

The package intentionally disables the source-tree updater. Replace the
package with a newer build instead.
