#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:?PYTHON_BIN is required}"
VENV_DIR="${VENV_DIR:-/tmp/qoder-nuitka-venv}"
NUITKA_VERSION="${NUITKA_VERSION:-4.3.1}"

compiler_dir="$(find /opt/rh -path '*/root/usr/bin/gcc' -type f 2>/dev/null | sort -V | tail -n1 || true)"
if [[ -n "$compiler_dir" ]]; then
    export PATH="$(dirname "$compiler_dir"):$PATH"
fi
command -v gcc
gcc --version | head -n1
export CC="$(command -v gcc)"
export CXX="$(command -v g++)"
export LINK="$CC"
export SHLINK="$CC"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --disable-pip-version-check "nuitka==$NUITKA_VERSION"

# Nuitka 4.3.1 bundles SCons 4.10.1. Its POSIX fallback still names the
# removed OS/2 "ilink" tool, so force the GNU linker tool when detection
# cannot resolve gcc/g++ inside the manylinux container.
"$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path
import nuitka

root = Path(nuitka.__file__).resolve().parent / "build" / "inline_copy" / "lib"
for path in root.glob("scons-*/SCons/Tool/__init__.py"):
    text = path.read_text(encoding="utf-8")
    patched = text.replace(
        "linkers = ['gnulink', 'ilink']",
        "linkers = ['gnulink']",
    )
    if patched != text:
        path.write_text(patched, encoding="utf-8")
        print("patched SCons POSIX linker fallback:", path)
PY

data_args=(
    --include-data-file=baseprompt.json=baseprompt.json
    --include-data-file=dashboard.html=dashboard.html
    --include-data-file=qoder_catalog_cn.json=qoder_catalog_cn.json
    --include-data-file=qoder_catalog_intl.json=qoder_catalog_intl.json
    --include-data-file=qoder_agents.py=qoder_agents.py
    --include-data-file=LICENSE=LICENSE
)
if [[ -d umid ]]; then
    data_args+=(--include-data-dir=umid=umid)
fi

"$VENV_DIR/bin/python" -m nuitka \
    --standalone \
    --assume-yes-for-downloads \
    --remove-output \
    --jobs=4 \
    --lto=no \
    --output-dir=dist/nuitka-linux \
    --output-filename=qoder2api-hub \
    --include-module=qoder_accounts \
    --include-module=qoder_activity \
    --include-module=qoder_agents \
    --include-module=qoder_anthropic \
    --include-module=qoder_catalog \
    --include-module=qoder_fingerprint \
    --include-module=qoder_pricing \
    --include-module=qoder_scheduler \
    --include-module=qoder_settings \
    --include-module=qoder_sign \
    --include-module=qoder_tasks \
    --include-module=qoder_updater \
    --include-module=qoder_webtools \
    "${data_args[@]}" \
    qoder_proxy.py
