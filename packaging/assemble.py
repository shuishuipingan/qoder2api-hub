#!/usr/bin/env python3
"""Assemble a Nuitka standalone bundle into a quick-deploy package."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import tarfile
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "qoder2api-hub"


def read_version() -> str:
    text = (ROOT / "qoder_proxy.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("cannot read VERSION from qoder_proxy.py")
    return match.group(1)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copy_file(src: Path, dst: Path, mode: int = 0o644) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    os.chmod(dst, mode)


def copy_text(src: Path, dst: Path, mode: int, newline: bytes) -> None:
    data = src.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    os.chmod(dst, mode)


def copy_script_tree(src_dir: Path, stage: Path, suffix: str) -> None:
    for src in sorted(src_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() != suffix:
            continue
        if suffix == ".sh":
            copy_text(src, stage / src.name, 0o755, b"\n")
        elif suffix == ".bat":
            copy_text(src, stage / src.name, 0o644, b"\r\n")
        else:
            copy_text(src, stage / src.name, 0o644, b"\r\n")


def make_linux_package(stage: Path) -> None:
    copy_script_tree(ROOT / "packaging" / "linux", stage, ".sh")


def make_windows_package(stage: Path) -> None:
    copy_script_tree(ROOT / "packaging" / "windows", stage, ".bat")
    copy_script_tree(ROOT / "packaging" / "windows", stage, ".ps1")


def write_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_tree_to_tar(tar: tarfile.TarFile, root: Path, base: str) -> None:
    stamp = int(time.time())
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        name = f"{base}/{rel}"
        stat = path.stat()
        info = tarfile.TarInfo(name)
        info.mtime = stamp
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        if path.is_dir():
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(info)
            continue
        info.type = tarfile.REGTYPE
        info.size = stat.st_size
        info.mode = stat.st_mode & 0o777
        with path.open("rb") as fh:
            tar.addfile(info, fh)


def add_tree_to_zip(archive: zipfile.ZipFile, root: Path, base: str) -> None:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        name = f"{base}/{rel}"
        if path.is_dir():
            continue
        archive.write(path, name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--bundle-dir", required=True)
    args = parser.parse_args()

    version = read_version()
    platform_slug = f"{args.platform}-{args.arch}"
    release_slug = f"nuitka-{platform_slug}"
    release_dir = ROOT / "release" / release_slug
    stage = release_dir / PACKAGE_NAME
    reset_dir(stage)

    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.is_dir():
        raise SystemExit(f"Nuitka bundle directory not found: {bundle_dir}")
    shutil.copytree(bundle_dir, stage, dirs_exist_ok=True)
    if args.platform == "linux":
        native_bin = stage / f"{PACKAGE_NAME}.bin"
        if native_bin.is_file():
            launcher = stage / PACKAGE_NAME
            launcher.write_bytes(
                b"#!/bin/sh\nexec \"$(dirname \"$0\")/"
                + PACKAGE_NAME.encode("ascii")
                + b".bin\" \"$@\"\n"
            )
            os.chmod(launcher, 0o755)
        elif not (stage / PACKAGE_NAME).is_file():
            raise SystemExit(
                f"Nuitka Linux binary not found: {stage / PACKAGE_NAME}"
            )
    else:
        native_bin = stage / f"{PACKAGE_NAME}.exe"
        if not native_bin.is_file():
            raise SystemExit(f"Nuitka Windows binary not found: {native_bin}")
    copy_file(ROOT / "LICENSE", stage / "LICENSE")
    copy_file(ROOT / "README.md", stage / "README.md")
    copy_file(
        ROOT / "packaging" / f"README-{args.platform.upper()}.md",
        stage / "START-HERE.md",
    )

    if args.platform == "linux":
        make_linux_package(stage)
    else:
        make_windows_package(stage)

    (stage / "data" / "accounts").mkdir(parents=True)
    (stage / "data" / "usage").mkdir(parents=True)
    copy_file(ROOT / "accounts" / "README.txt", stage / "data" / "accounts" / "README.txt")
    (stage / "data" / "usage" / ".gitkeep").write_bytes(b"")

    archive_name = f"{PACKAGE_NAME}-{version}-nuitka-{platform_slug}"
    if args.platform == "linux":
        archive = release_dir / f"{archive_name}.tar.gz"
        with tarfile.open(archive, "w:gz", format=tarfile.GNU_FORMAT, compresslevel=9) as tar:
            add_tree_to_tar(tar, stage, PACKAGE_NAME)
    else:
        archive = release_dir / f"{archive_name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            add_tree_to_zip(zf, stage, PACKAGE_NAME)

    checksum = write_sha256(archive)
    checksum_file = release_dir / "SHA256SUMS"
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")

    print(f"package: {archive}")
    print(f"sha256: {checksum}")
    print(f"bytes: {archive.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
