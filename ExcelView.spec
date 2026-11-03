# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('resources/excel.qss', 'resources')]
binaries = []
hiddenimports = []
# PySide6 전체 대신 PyInstaller 훅이 실제로 쓰는 모듈만 넣음 (QtWebEngine 포함)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='ExcelView',
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
# 폴더형 빌드는 dist\ExcelView 를 통째로 지우고 다시 만든다 — 그 안의 사용자 설정
# (ExcelViewAPPDATA: 비밀번호·즐겨찾기·위장 시트)이 지워지지 않게 빌드 동안 따로 보관했다가 되돌림
import os, shutil, tempfile
_appdata = os.path.join(DISTPATH, 'ExcelView', 'ExcelViewAPPDATA')
_running_exe = os.path.join(DISTPATH, 'ExcelView', 'ExcelView.exe')

# 실행 중이면 파일이 잠겨 폴더를 지우다 중간에 실패한다 — 아무것도 지우기 전에 멈춤
if os.path.exists(_running_exe):
    try:
        with open(_running_exe, 'ab'):
            pass
    except PermissionError:
        raise SystemExit('ExcelView.exe 가 실행 중입니다 — 프로그램을 종료한 뒤 다시 빌드하세요.')

_backup = None
if os.path.isdir(_appdata):
    _backup = os.path.join(tempfile.mkdtemp(prefix='excelview_appdata_'), 'ExcelViewAPPDATA')
    shutil.copytree(_appdata, _backup)
    print('ExcelViewAPPDATA 보관:', _backup)

try:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name='ExcelView',
    )
finally:
    # 빌드가 중간에 실패해도 반드시 되돌린다
    if _backup:
        shutil.copytree(_backup, _appdata, dirs_exist_ok=True)
        shutil.rmtree(os.path.dirname(_backup), ignore_errors=True)
        print('ExcelViewAPPDATA 복원:', _appdata)
