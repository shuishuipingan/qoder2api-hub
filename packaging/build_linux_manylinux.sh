#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/opt/python/cp312-cp312/bin/python}"
VENV_DIR="${VENV_DIR:-/tmp/qoder-pyinstaller-venv}"
PYINSTALLER_VERSION="${PYINSTALLER_VERSION:-6.22.3}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --disable-pip-version-check "pyinstaller==$PYINSTALLER_VERSION"
"$VENV_DIR/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --workpath build/pyinstaller-linux \
    --distpath dist/linux \
    qoder2api-hub.spec
