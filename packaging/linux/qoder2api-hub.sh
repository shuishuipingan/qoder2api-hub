#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="qoder2api-hub"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR"
BIN="${QODER_BIN:-$PACKAGE_DIR/$SERVICE_NAME}"
DATA_DIR="${QODER_DATA_DIR:-$PACKAGE_DIR/data}"
PID_FILE="$DATA_DIR/$SERVICE_NAME.pid"
LOG_DIR="${QODER_LOG_DIR:-$DATA_DIR/logs}"
LOG_FILE="$LOG_DIR/$SERVICE_NAME.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8790}"
ACCOUNTS_DIR="${ACCOUNTS_DIR:-$DATA_DIR/accounts}"
USAGE_DIR="${QD_PROXY_USAGE_DIR:-$DATA_DIR/usage}"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|stop|restart|status|logs}

Environment:
  QODER_DATA_DIR       runtime data directory (default: $PACKAGE_DIR/data)
  QODER_LOG_DIR        log directory (default: DATA_DIR/logs)
  HOST                 listen host (default: 127.0.0.1)
  PORT                 listen port (default: 8790)
  ACCOUNTS_DIR         account directory override
  QD_PROXY_USAGE_DIR   usage directory override
EOF
}

systemd_installed() {
    [[ -f "$UNIT_FILE" ]] && command -v systemctl >/dev/null 2>&1
}

read_pid() {
    [[ -f "$PID_FILE" ]] || return 1
    local pid
    pid="$(tr -cd '0-9' < "$PID_FILE")"
    [[ -n "$pid" ]] || return 1
    printf '%s\n' "$pid"
}

is_running() {
    local pid
    pid="$(read_pid)" || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    [[ -r "/proc/$pid/cmdline" ]] || return 0
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq "$SERVICE_NAME"
}

direct_start() {
    [[ -x "$BIN" ]] || {
        echo "[ERROR] binary not executable: $BIN" >&2
        return 1
    }
    if is_running; then
        echo "[INFO] $SERVICE_NAME is already running (PID $(read_pid))"
        return 0
    fi
    mkdir -p "$ACCOUNTS_DIR" "$USAGE_DIR" "$LOG_DIR"
    chmod 700 "$DATA_DIR" "$ACCOUNTS_DIR" "$USAGE_DIR" 2>/dev/null || true
    rm -f "$PID_FILE"
    nohup env \
        QD_UPDATE_DISABLE=1 \
        "$BIN" \
        --host "$HOST" \
        --port "$PORT" \
        --accounts-dir "$ACCOUNTS_DIR" \
        --usage-dir "$USAGE_DIR" \
        --pid-file "$PID_FILE" \
        >>"$LOG_FILE" 2>&1 &
    local launched=$!
    for _ in $(seq 1 50); do
        if is_running; then
            echo "[OK] $SERVICE_NAME started (PID $(read_pid))"
            echo "     API:       http://$HOST:$PORT/v1"
            echo "     Dashboard: http://$HOST:$PORT/"
            echo "     Log:       $LOG_FILE"
            return 0
        fi
        if ! kill -0 "$launched" 2>/dev/null; then
            break
        fi
        sleep 0.2
    done
    echo "[ERROR] $SERVICE_NAME failed to start" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
    return 1
}

direct_stop() {
    local pid
    if ! pid="$(read_pid)"; then
        echo "[INFO] $SERVICE_NAME is not running (no PID file)"
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "[INFO] stale PID file removed"
        return 0
    fi
    if [[ -r "/proc/$pid/cmdline" ]] && \
            ! tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq "$SERVICE_NAME"; then
        echo "[WARN] PID $pid is not $SERVICE_NAME; refusing to stop it" >&2
        return 3
    fi
    kill -TERM "$pid"
    for _ in $(seq 1 50); do
        kill -0 "$pid" 2>/dev/null || {
            rm -f "$PID_FILE"
            echo "[OK] $SERVICE_NAME stopped"
            return 0
        }
        sleep 0.2
    done
    echo "[WARN] graceful shutdown timed out; sending SIGKILL" >&2
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "[OK] $SERVICE_NAME stopped"
}

direct_status() {
    if is_running; then
        echo "$SERVICE_NAME is running (PID $(read_pid))"
        echo "Dashboard: http://$HOST:$PORT/"
        return 0
    fi
    echo "$SERVICE_NAME is stopped"
    return 3
}

direct_logs() {
    mkdir -p "$LOG_DIR"
    touch "$LOG_FILE"
    tail -n 200 -f "$LOG_FILE"
}

cmd="${1:-}"
case "$cmd" in
    start)
        if systemd_installed; then
            systemctl start "$SERVICE_NAME"
            systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,12p'
        else
            direct_start
        fi
        ;;
    stop)
        if systemd_installed; then
            systemctl stop "$SERVICE_NAME"
            echo "[OK] $SERVICE_NAME stopped"
        else
            direct_stop
        fi
        ;;
    restart)
        if systemd_installed; then
            systemctl restart "$SERVICE_NAME"
            systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,12p'
        else
            direct_stop
            direct_start
        fi
        ;;
    status)
        if systemd_installed; then
            systemctl --no-pager --full status "$SERVICE_NAME"
        else
            direct_status
        fi
        ;;
    logs)
        if systemd_installed; then
            journalctl -u "$SERVICE_NAME" -n 200 -f
        else
            direct_logs
        fi
        ;;
    *)
        usage
        exit 2
        ;;
esac
