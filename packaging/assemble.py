#!/usr/bin/env python3
"""Assemble a PyInstaller binary into a quick-deploy package."""

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
    parser.add_argument("--binary", required=True)
    args = parser.parse_args()

    version = read_version()
    binary = Path(args.binary).resolve()
    if not binary.is_file():
        raise SystemExit(f"binary not found: {binary}")

    platform_slug = f"{args.platform}-{args.arch}"
    release_dir = ROOT / "release" / platform_slug
    stage = release_dir / PACKAGE_NAME
    reset_dir(stage)

    binary_name = PACKAGE_NAME + (".exe" if args.platform == "windows" else "")
    copy_file(binary, stage / binary_name, 0o755 if args.platform == "linux" else 0o644)
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

    archive_name = f"{PACKAGE_NAME}-{version}-{platform_slug}"
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
