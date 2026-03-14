# FastCollageCreator.spec
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect everything from pillow_jxl (native libs + data + hidden imports)
jxl_datas, jxl_binaries, jxl_hidden = collect_all("pillow_jxl")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=jxl_binaries,
    datas=jxl_datas,
    hiddenimports=[
        "pillow_jxl",
        *jxl_hidden,
        "PySide6.QtSvg",
        "PySide6.QtXml",
    ],
    hookspath=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_icon = (
    "icons/icon.ico"   if sys.platform == "win32"  else
    "icons/icon.icns"  if sys.platform == "darwin" else
    None
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FastCollageCreator",
    console=False,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="FastCollageCreator",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FastCollageCreator.app",
        icon="icons/icon.icns",
        bundle_identifier="com.quirin053.fastcollagecreator",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
