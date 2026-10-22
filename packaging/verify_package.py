#!/usr/bin/env python3
"""Verify archive contents, modes, checksums, and runtime-data hygiene."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(release_dir: Path, archive: Path) -> None:
    checksum_file = release_dir / "SHA256SUMS"
    expected_line = checksum_file.read_text(encoding="ascii").strip()
    expected_hash, expected_name = expected_line.split(None, 1)
    if expected_name.strip() != archive.name:
        raise SystemExit(f"checksum names {expected_name!r}, expected {archive.name!r}")
    actual = sha256(archive)
    if actual != expected_hash:
        raise SystemExit(f"checksum mismatch: {actual} != {expected_hash}")


def verify_linux(archive: Path, engine: str) -> None:
    required = {
        "qoder2api-hub/qoder2api-hub",
        "qoder2api-hub/qoder2api-hub.sh",
        "qoder2api-hub/start-qoder-proxy.sh",
        "qoder2api-hub/stop-qoder-proxy.sh",
        "qoder2api-hub/restart-qoder-proxy.sh",
        "qoder2api-hub/status-qoder-proxy.sh",
        "qoder2api-hub/logs-qoder-proxy.sh",
        "qoder2api-hub/install-systemd.sh",
        "qoder2api-hub/uninstall-systemd.sh",
        "qoder2api-hub/data/accounts/README.txt",
        "qoder2api-hub/data/usage/.gitkeep",
    }
    if engine == "nuitka":
        required.add("qoder2api-hub/umid/runtime-info")
    executable = {
        "qoder2api-hub/qoder2api-hub",
        "qoder2api-hub/qoder2api-hub.sh",
        "qoder2api-hub/start-qoder-proxy.sh",
        "qoder2api-hub/stop-qoder-proxy.sh",
        "qoder2api-hub/restart-qoder-proxy.sh",
        "qoder2api-hub/status-qoder-proxy.sh",
        "qoder2api-hub/logs-qoder-proxy.sh",
        "qoder2api-hub/install-systemd.sh",
        "qoder2api-hub/uninstall-systemd.sh",
    }
    with tarfile.open(archive, "r:gz") as tar:
        members = {member.name: member for member in tar.getmembers()}
        missing = sorted(required - set(members))
        if missing:
            raise SystemExit("missing Linux package entries: " + ", ".join(missing))
        for name in executable:
            if not (members[name].mode & 0o111):
                raise SystemExit(f"{name} is not executable: {members[name].mode:o}")
        native_names = (
            ("qoder2api-hub/qoder2api-hub", "qoder2api-hub/qoder2api-hub.bin")
            if engine == "nuitka"
            else ("qoder2api-hub/qoder2api-hub",)
        )
        native_name = next((name for name in native_names if name in members), "")
        if not native_name:
            raise SystemExit("Linux native binary is missing")
        minimum = 1024 * 1024 if engine == "nuitka" else 5 * 1024 * 1024
        if members[native_name].size < minimum:
            raise SystemExit(f"{native_name} is unexpectedly small")


def verify_windows(archive: Path, engine: str) -> None:
    required = {
        "qoder2api-hub/qoder2api-hub.exe",
        "qoder2api-hub/start-qoder-proxy.bat",
        "qoder2api-hub/start-qoder-proxy-lan.bat",
        "qoder2api-hub/stop-qoder-proxy.bat",
        "qoder2api-hub/install-service.ps1",
        "qoder2api-hub/uninstall-service.ps1",
        "qoder2api-hub/data/accounts/README.txt",
        "qoder2api-hub/data/usage/.gitkeep",
    }
    if engine == "nuitka":
        required.update({
            "qoder2api-hub/umid/runtime-info.exe",
            "qoder2api-hub/umid/sgsdk.dll",
        })
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        missing = sorted(required - names)
        if missing:
            raise SystemExit("missing Windows package entries: " + ", ".join(missing))
        if zf.getinfo("qoder2api-hub/qoder2api-hub.exe").file_size < 5 * 1024 * 1024:
            raise SystemExit("Windows executable is unexpectedly small")
        bat = zf.read("qoder2api-hub/start-qoder-proxy.bat")
        if b"\r\n" not in bat or b"\n" in bat.replace(b"\r\n", b""):
            raise SystemExit("Windows batch file is not consistently CRLF")


def verify_clean_entries(names: set[str]) -> None:
    forbidden_suffixes = (
        "/accounts/settings.json",
        "/accounts/active_realm.json",
        "/usage/usage.jsonl",
        "/usage/activity.jsonl",
        "/scheduler/state.json",
        "/qoder-proxy.pid",
    )
    hits = [name for name in names if name.endswith(forbidden_suffixes)]
    if hits:
        raise SystemExit("runtime data leaked into package: " + ", ".join(hits[:10]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--engine", choices=("pyinstaller", "nuitka"), default="pyinstaller")
    args = parser.parse_args()

    release_slug = f"{args.platform}-{args.arch}"
    if args.engine == "nuitka":
        release_slug = f"nuitka-{release_slug}"
    release_dir = ROOT / "release" / release_slug
    suffix = ".tar.gz" if args.platform == "linux" else ".zip"
    archives = sorted(release_dir.glob(f"qoder2api-hub-*{suffix}"))
    if len(archives) != 1:
        raise SystemExit(f"expected one {suffix} archive in {release_dir}")
    archive = archives[0]
    verify_checksum(release_dir, archive)

    if args.platform == "linux":
        with tarfile.open(archive, "r:gz") as tar:
            verify_clean_entries({member.name for member in tar.getmembers()})
        verify_linux(archive, args.engine)
    else:
        with zipfile.ZipFile(archive) as zf:
            verify_clean_entries(set(zf.namelist()))
        verify_windows(archive, args.engine)

    print(f"verified: {archive}")
    print(f"sha256: {sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
