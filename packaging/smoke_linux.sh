#!/usr/bin/env bash
set -euo pipefail

BIN="${1:-release/linux-x86_64/qoder2api-hub/qoder2api-hub}"
PYTHON_BIN="${PYTHON_BIN:-/opt/python/cp312-cp312/bin/python}"
PORT="${SMOKE_PORT:-18791}"
TMP="$(mktemp -d)"
PID=""

cleanup() {
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    rm -rf -- "$TMP"
}
trap cleanup EXIT

"$BIN" --help >/dev/null
mkdir -p "$TMP/accounts" "$TMP/usage"
QD_UPDATE_DISABLE=1 "$BIN" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --accounts-dir "$TMP/accounts" \
    --usage-dir "$TMP/usage" \
    >"$TMP/server.log" 2>&1 &
PID=$!

ok=0
for _ in $(seq 1 60); do
    if "$PYTHON_BIN" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:'"$PORT"'/ping", timeout=2).read()' >/dev/null 2>&1; then
        ok=1
        break
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done
if [[ "$ok" -ne 1 ]]; then
    echo "server failed to start"
    cat "$TMP/server.log"
    exit 1
fi

"$PYTHON_BIN" -c '
import json
import sys
import urllib.request

base = sys.argv[1]
assert urllib.request.urlopen(base + "/ping", timeout=5).read().strip() == b"pong"
health = json.load(urllib.request.urlopen(base + "/health", timeout=10))
assert health["version"] == "1.6.12", health
models = json.load(urllib.request.urlopen(base + "/v1/models", timeout=15))
assert models["object"] == "list", models
dashboard = urllib.request.urlopen(base + "/", timeout=5).read()
assert b"Qoder" in dashboard
print("linux smoke OK")
' "http://127.0.0.1:$PORT"

kill -TERM "$PID"
wait "$PID" || true
PID=""

CONTROL_PORT="$((PORT + 2))"
CONTROL_DATA="$TMP/control-data"
QODER_DATA_DIR="$CONTROL_DATA" PORT="$CONTROL_PORT" \
    "$(dirname "$BIN")/qoder2api-hub.sh" start
ok=0
for _ in $(seq 1 60); do
    if "$PYTHON_BIN" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:'"$CONTROL_PORT"'/ping", timeout=2).read()' >/dev/null 2>&1; then
        ok=1
        break
    fi
    sleep 1
done
if [[ "$ok" -ne 1 ]]; then
    echo "control script failed to start the server"
    exit 1
fi
QODER_DATA_DIR="$CONTROL_DATA" PORT="$CONTROL_PORT" \
    "$(dirname "$BIN")/qoder2api-hub.sh" status
QODER_DATA_DIR="$CONTROL_DATA" PORT="$CONTROL_PORT" \
    "$(dirname "$BIN")/qoder2api-hub.sh" stop

LAN_PORT="$((PORT + 1))"
mkdir -p "$TMP/lan-accounts" "$TMP/lan-usage"
QD_UPDATE_DISABLE=1 "$BIN" \
    --host 0.0.0.0 \
    --port "$LAN_PORT" \
    --lan \
    --api-key qd-smoke-test-key \
    --accounts-dir "$TMP/lan-accounts" \
    --usage-dir "$TMP/lan-usage" \
    >"$TMP/lan-server.log" 2>&1 &
PID=$!

ok=0
for _ in $(seq 1 60); do
    if "$PYTHON_BIN" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:'"$LAN_PORT"'/ping", timeout=2).read()' >/dev/null 2>&1; then
        ok=1
        break
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done
if [[ "$ok" -ne 1 ]]; then
    echo "LAN server failed to start"
    cat "$TMP/lan-server.log"
    exit 1
fi

"$PYTHON_BIN" -c '
import sys
import urllib.error
import urllib.request

base = sys.argv[1]

def status(headers=None):
    request = urllib.request.Request(base + "/v1/models", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code

statuses = (
    status(),
    status({"Authorization": "Bearer wrong-key"}),
    status({"Authorization": "Bearer qd-smoke-test-key"}),
)
assert statuses == (401, 401, 200), statuses
print("linux LAN auth matrix OK")
' "http://127.0.0.1:$LAN_PORT"

kill -TERM "$PID"
wait "$PID" || true
PID=""
