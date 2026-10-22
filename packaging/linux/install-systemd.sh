#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="qoder2api-hub"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_BIN="$SCRIPT_DIR/$SERVICE_NAME"
INSTALL_DIR="/opt/$SERVICE_NAME"
DATA_DIR="/var/lib/$SERVICE_NAME"
DEFAULT_FILE="/etc/default/$SERVICE_NAME"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
SYSTEM_USER="$SERVICE_NAME"
PORT="${PORT:-8790}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] install-systemd.sh must run as root" >&2
    exit 1
fi
command -v systemctl >/dev/null 2>&1 || {
    echo "[ERROR] systemctl is not available" >&2
    exit 1
}
[[ -x "$SOURCE_BIN" ]] || {
    echo "[ERROR] binary not found or not executable: $SOURCE_BIN" >&2
    exit 1
}

if systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi

if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SYSTEM_USER"
fi

install -d -m 0755 -o root -g root "$INSTALL_DIR"
while IFS= read -r -d '' entry; do
    base="$(basename "$entry")"
    case "$base" in
        data|START-HERE.md|LICENSE|*.sh)
            continue
            ;;
    esac
    cp -a "$entry" "$INSTALL_DIR/"
done < <(find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 -print0)
install -m 0755 "$SOURCE_BIN" "$INSTALL_DIR/$SERVICE_NAME"
install -m 0755 "$SCRIPT_DIR/qoder2api-hub.sh" "$INSTALL_DIR/qoder2api-hub.sh"
install -m 0644 "$SCRIPT_DIR/START-HERE.md" "$INSTALL_DIR/START-HERE.md" 2>/dev/null || true
install -m 0644 "$SCRIPT_DIR/LICENSE" "$INSTALL_DIR/LICENSE" 2>/dev/null || true

install -d -m 0750 -o "$SYSTEM_USER" -g "$SYSTEM_USER" "$DATA_DIR"
install -d -m 0700 -o "$SYSTEM_USER" -g "$SYSTEM_USER" "$DATA_DIR/accounts"
install -d -m 0700 -o "$SYSTEM_USER" -g "$SYSTEM_USER" "$DATA_DIR/usage"

if [[ ! -f "$DEFAULT_FILE" ]]; then
    cat >"$DEFAULT_FILE" <<'EOF'
HOST=127.0.0.1
PORT=8790
QD_PROXY_DEFAULT_REALM=cn
QD_AUTO_REALM=1
QD_UPDATE_DISABLE=1
EOF
    chmod 0644 "$DEFAULT_FILE"
fi

cat >"$UNIT_FILE" <<EOF
[Unit]
Description=Qoder2API Hub gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SYSTEM_USER
Group=$SYSTEM_USER
WorkingDirectory=$DATA_DIR
EnvironmentFile=-$DEFAULT_FILE
Environment=QD_UPDATE_DISABLE=1
ExecStart=$INSTALL_DIR/$SERVICE_NAME --accounts-dir $DATA_DIR/accounts --usage-dir $DATA_DIR/usage --pid-file $DATA_DIR/$SERVICE_NAME.pid
Restart=on-failure
RestartSec=3
TimeoutStopSec=25
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,14p'
echo
echo "[OK] systemd service installed"
echo "     Config:    $DEFAULT_FILE"
echo "     Data:      $DATA_DIR"
echo "     Dashboard: http://127.0.0.1:$PORT/"
