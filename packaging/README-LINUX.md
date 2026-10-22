# Qoder2API Hub binary package for Linux

This package contains a Nuitka-compiled standalone executable and bundled
CPython runtime. It does not require an installed Python interpreter.
It is built for glibc 2.17 or newer.

Keep all extracted files together. The executable depends on the adjacent
runtime libraries, data files, and UMID component.

## Direct run

```bash
./start-qoder-proxy.sh
./status-qoder-proxy.sh
./logs-qoder-proxy.sh
./restart-qoder-proxy.sh
./stop-qoder-proxy.sh
```

Runtime data is stored in `./data/accounts` and `./data/usage` by default.
Set `QODER_DATA_DIR` to use another directory.

Open `http://127.0.0.1:8790/` after startup. The initial panel password is
`admin`; change it before exposing the service to a network.

## systemd

Install and start the service:

```bash
sudo ./install-systemd.sh
```

The installed service uses:

- binary: `/opt/qoder2api-hub/qoder2api-hub`
- data: `/var/lib/qoder2api-hub`
- environment: `/etc/default/qoder2api-hub`
- unit: `/etc/systemd/system/qoder2api-hub.service`

Uninstall the service while preserving data:

```bash
sudo ./uninstall-systemd.sh
```

Delete service data explicitly:

```bash
sudo ./uninstall-systemd.sh --purge-data
```

The package intentionally disables the source-tree updater. Replace the
package with a newer build instead.
