# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH)

a = Analysis(
    [str(PROJECT_ROOT / 'gui.py')],
    pathex=[
        str(PROJECT_ROOT),
        str(PROJECT_ROOT / 'backend'),
        str(PROJECT_ROOT / 'gui'),
        str(PROJECT_ROOT / 'scripts'),
    ],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / 'config'), 'config'),
    ],
    hiddenimports=[
        'backend.config_manager',
        'backend.llm_client',
        'backend.data_fetcher',
        'backend.factor_engine',
        'backend.llm_decision',
        'backend.position_fetcher',
        'backend.batch_parser',
        'backend.single_parser',
        'backend.single_summary_client',
        'backend.parsed_records',
        'backend.task_queue_manager',
        'backend.time_price_judge',
        'backend.valley_scheduler',
        'backend.up_manager',
        'backend.notifier',
        'backend.feishu_notifier',
        'gui.timeline',
        'gui.utils',
        'gui.pages.page_etf',
        'gui.pages.page_parse',
        'gui.pages.page_batch',
        'gui.pages.page_config',
        'gui.pages.tray',
        'scripts.step1_fetch_videos',
        'scripts.step2_download_audio',
        'scripts.step3_transcribe',
        'scripts.step4_extract_stocks',
        'scripts.step5_analyze',
        'scripts.run_pipeline',
        'cryptography',
        'openpyxl',
        'requests',
        'PIL',
    ],
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
    name='gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
