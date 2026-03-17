# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

# Collect all *.json files within the unicode_codes folder of the emoji module
emoji_datas = collect_data_files('emoji.unicode_codes', includes=['*.json'])
extra_datas = [
    ('data/stt/google-cloud-stt-v2_supported-languages.txt', 'data/stt'),
    ('data/stt/silero/silero_vad.onnx', 'data/stt/silero'),
]

a = Analysis(
    ['twitchbot.py'],
    pathex=['.'],
    binaries=[],
    datas=emoji_datas + extra_datas,
    hiddenimports=[
        "google.cloud.speech",
        "google.cloud.speech_v2",
        "onnxruntime",
        "onnxruntime.capi.onnxruntime_pybind11_state",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='twitchbot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir='./',
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
