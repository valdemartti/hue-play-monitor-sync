# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Desktop Lights macOS app."""

a = Analysis(
    ["app_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "src",
        "src.config_manager",
        "src.color_processing",
        "src.credentials",
        "src.hue_bridge",
        "src.screen_capture",
        "src.sync_engine",
        "src.zone_mapper",
        "ui",
        "ui.tray_app",
        "keyring",
        "keyring.backends",
        "keyring.backends.macOS",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PIL", "test", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Desktop Lights",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Desktop Lights",
)

app = BUNDLE(
    coll,
    name="Desktop Lights.app",
    icon=None,
    bundle_identifier="com.desktoplights.app",
    info_plist={
        "CFBundleName": "Desktop Lights",
        "CFBundleDisplayName": "Desktop Lights",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,
        "NSScreenCaptureUsageDescription": (
            "Desktop Lights needs screen recording access to capture "
            "monitor colors for syncing to your Hue lightstrips."
        ),
    },
)
