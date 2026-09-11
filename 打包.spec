# PyInstaller spec for the standalone Windows floating-ball build.
import os
import shutil
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)


def find_node() -> str:
    configured = os.environ.get("CCSWITCH_NODE_PATH", "").strip()
    candidates = [configured] if configured else []
    candidates.append(shutil.which("node") or shutil.which("node.exe") or "")
    candidates.append(
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe")
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


node_path = find_node()
if node_path:
    print(f"Bundling Node.js runtime: {node_path}")
else:
    print("WARNING: node.exe not found; the EXE will need Node.js on PATH at runtime.")

a = Analysis(
    [str(root / "widget.py")],
    pathex=[str(root)],
    binaries=[(node_path, "runtime")] if node_path else [],
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
    name="CC-Switch-Ball",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
