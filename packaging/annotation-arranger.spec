# PyInstaller single-file executable, built natively on each target runner.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=[],
    datas=copy_metadata("annotation-arranger"),
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="annotation-arranger", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
