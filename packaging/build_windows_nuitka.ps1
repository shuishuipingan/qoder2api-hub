[CmdletBinding()]
param(
    [string]$NuitkaVersion = "4.3.1"
)

$ErrorActionPreference = "Stop"
python -m pip install --disable-pip-version-check "nuitka==$NuitkaVersion"
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka installation failed"
}

$Arguments = @(
    "-m", "nuitka",
    "--standalone",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--jobs=4",
    "--msvc=latest",
    "--windows-console-mode=force",
    "--output-dir=dist/nuitka-windows",
    "--output-filename=qoder2api-hub.exe",
    "--file-version=1.6.12.0",
    "--product-version=1.6.12.0",
    "--include-module=qoder_accounts",
    "--include-module=qoder_activity",
    "--include-module=qoder_agents",
    "--include-module=qoder_anthropic",
    "--include-module=qoder_catalog",
    "--include-module=qoder_fingerprint",
    "--include-module=qoder_pricing",
    "--include-module=qoder_scheduler",
    "--include-module=qoder_settings",
    "--include-module=qoder_sign",
    "--include-module=qoder_tasks",
    "--include-module=qoder_updater",
    "--include-module=qoder_webtools",
    "--include-data-file=baseprompt.json=baseprompt.json",
    "--include-data-file=dashboard.html=dashboard.html",
    "--include-data-file=qoder_catalog_cn.json=qoder_catalog_cn.json",
    "--include-data-file=qoder_catalog_intl.json=qoder_catalog_intl.json",
    "--include-data-file=qoder_agents.py=qoder_agents.py",
    "--include-data-file=LICENSE=LICENSE"
)
if (Test-Path -LiteralPath "umid") {
    $Arguments += "--include-data-dir=umid=umid"
}
$Arguments += "qoder_proxy.py"

& python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka build failed"
}
