# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "baseprompt.json"), "."),
    (str(ROOT / "dashboard.html"), "."),
    (str(ROOT / "qoder_catalog_cn.json"), "."),
    (str(ROOT / "qoder_catalog_intl.json"), "."),
    (str(ROOT / "qoder_agents.py"), "."),
    (str(ROOT / "LICENSE"), "."),
]

umid_dir = ROOT / "umid"
if umid_dir.is_dir():
    datas.append((str(umid_dir), "umid"))

a = Analysis(
    [str(ROOT / "qoder_proxy.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="qoder2api-hub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
