@echo off
rem Start Xcelord on Windows:  run.bat   (or double-click it; first run sets everything up)
rem Options: --local-whisper  --reinstall  --port 9000  --no-browser
rem
rem Uses Python 3.10+ if one is installed. Otherwise downloads uv and a private
rem Python into .tools (nothing is installed system-wide, PATH is untouched).
setlocal
cd /d "%~dp0"
set "TOOLS=%CD%\.tools"
set "UV_PYTHON_INSTALL_DIR=%TOOLS%\python"

set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY call :private_python
if not defined PY goto nopython

%PY% scripts\launch.py %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  pause
)
exit /b %RC%

:private_python
if not exist "%TOOLS%\uv.exe" (
  echo [xcelord] Python 3.10+ not found. Downloading a private copy into .tools ^(one time^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_INSTALL_DIR='%TOOLS%'; $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex" >nul
)
if not exist "%TOOLS%\uv.exe" exit /b 1
"%TOOLS%\uv.exe" python install 3.12 --quiet
for /f "delims=" %%p in ('call "%TOOLS%\uv.exe" python find 3.12') do set PY="%%p"
exit /b 0

:nopython
echo [xcelord] Couldn't set up Python automatically.
echo           Check your internet connection and run this again, or install
echo           Python 3.10+ from https://www.python.org/downloads/
echo.
pause
exit /b 1
