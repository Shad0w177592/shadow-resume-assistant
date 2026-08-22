# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("uvicorn")
datas += [(str(Path(SPECPATH) / "migrations"), "migrations")]

a = Analysis(
    ["app/__main__.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["app.main"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="shadow-resume-backend",
    console=False,
    onefile=True,
)
