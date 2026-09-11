# PyInstaller spec for the standalone Windows floating-ball build.
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)
node_path = Path(r"D:\study\nodejs\node.exe")

a = Analysis(
    [str(root / "widget.py")],
    pathex=[str(root)],
    binaries=[(str(node_path), "runtime")] if node_path.exists() else [],
    datas=[(str(root / "quota_query.js"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CC Switch 悬浮球",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
