@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating venv...
    python -m venv .venv
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem PySide6 / shiboken6 DLL 을 PATH 최우선으로 — Anaconda Qt 등 시스템 라이브러리와 충돌 회피
set "PATH=%~dp0.venv\Lib\site-packages\PySide6;%~dp0.venv\Lib\site-packages\shiboken6;%~dp0.venv\Scripts;%PATH%"

".venv\Scripts\python.exe" main.py
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo [ExcelView] 종료 코드: %EXITCODE%
    pause
)
endlocal
