#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="qoder2api-hub"
INSTALL_DIR="/opt/$SERVICE_NAME"
DATA_DIR="/var/lib/$SERVICE_NAME"
DEFAULT_FILE="/etc/default/$SERVICE_NAME"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
PURGE_DATA=0

if [[ "${1:-}" == "--purge-data" ]]; then
    PURGE_DATA=1
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--purge-data]" >&2
    exit 2
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] uninstall-systemd.sh must run as root" >&2
    exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
fi

rm -f "$UNIT_FILE"
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
fi

rm -rf -- "$INSTALL_DIR"
if id "$SERVICE_NAME" >/dev/null 2>&1; then
    userdel "$SERVICE_NAME" 2>/dev/null || true
fi

echo "[OK] systemd service removed"
echo "     Preserved: $DATA_DIR"
echo "     Preserved: $DEFAULT_FILE"

if [[ "$PURGE_DATA" -eq 1 ]]; then
    case "$DATA_DIR" in
        "/var/lib/$SERVICE_NAME") rm -rf -- "$DATA_DIR" ;;
        *) echo "[ERROR] refusing to purge unexpected path: $DATA_DIR" >&2; exit 3 ;;
    esac
    rm -f "$DEFAULT_FILE"
    echo "[OK] runtime data and environment file deleted"
fi
