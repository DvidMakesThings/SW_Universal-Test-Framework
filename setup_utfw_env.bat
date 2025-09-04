@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
REM ================================================================
REM  UTFW Environment Bootstrap (Windows, Python version agnostic)
REM
REM  Usage:
REM    setup_utfw_env.bat [REPO_DIR] [PY_VER]
REM
REM  Examples:
REM    setup_utfw_env.bat                           (uses this script's folder as REPO_DIR, latest Python 3)
REM    setup_utfw_env.bat "G:\_GitHub\SW_Universal-Test-Framework"   (latest Python 3)
REM    setup_utfw_env.bat "G:\repo" 3.12            (explicit Python 3.12)
REM
REM  What it does:
REM    - pip editable-installs UTFW from REPO_DIR
REM    - creates a .pth in the chosen interpreter’s site-packages so `import UTFW` works anywhere
REM    - verifies the import
REM ================================================================

REM --- Defaults ---------------------------------------------------
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR:~0,-1%") do set "SCRIPT_DIR=%%~fI"

if "%~1"=="" (
  set "REPO_DIR=%SCRIPT_DIR%"
) else (
  set "REPO_DIR=%~1"
)

if "%~2"=="" (
  set "PY_VER=3"
) else (
  set "PY_VER=%~2"
)

set "PY_CALL=py -%PY_VER%"

REM --- Validate repo path ----------------------------------------
if not exist "%REPO_DIR%\UTFW\__init__.py" (
  echo [ERROR] UTFW repo not found at: "%REPO_DIR%"
  echo         Pass the correct path as the first argument.
  exit /b 1
)

REM --- Check Python via launcher ---------------------------------
%PY_CALL% -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo [WARN] Python launcher fallback: trying ^"python^" on PATH...
  set "PY_CALL=python"
  %PY_CALL% -c "import sys; print(sys.version)" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] No working Python found. Install Python or adjust arguments.
    exit /b 1
  )
)

echo [INFO] Using interpreter: %PY_CALL%

REM --- Upgrade pip/setuptools/wheel ------------------------------
echo [INFO] Upgrading pip/setuptools/wheel...
%PY_CALL% -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip/setuptools/wheel.
  exit /b 1
)

REM --- Editable install of UTFW ----------------------------------
echo [INFO] Installing UTFW in editable mode from:
echo        "%REPO_DIR%"
%PY_CALL% -m pip install -e "%REPO_DIR%"
if errorlevel 1 (
  echo [ERROR] pip install -e failed.
  exit /b 1
)

REM --- Compute site-packages path --------------------------------
for /f "usebackq delims=" %%I in (`%PY_CALL% -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"`) do set "PURELIB=%%~I"

if not defined PURELIB (
  echo [ERROR] Could not determine site-packages path.
  exit /b 1
)

if not exist "%PURELIB%" (
  echo [ERROR] Site-packages path does not exist: "%PURELIB%"
  exit /b 1
)

REM --- Write .pth file so UTFW is importable globally ------------
set "PTH_FILE=%PURELIB%\utfw_repo.pth"
echo [INFO] Writing path file:
echo        "%PTH_FILE%"
> "%PTH_FILE%" echo %REPO_DIR%

if not exist "%PTH_FILE%" (
  echo [ERROR] Failed to create "%PTH_FILE%".
  exit /b 1
)

REM --- Verify import ---------------------------------------------
echo [INFO] Verifying import...
%PY_CALL% -c "import UTFW, sys; print(sys.version); print(UTFW.__file__)" || (
  echo [ERROR] Import verification failed.
  exit /b 1
)

echo.
echo [SUCCESS] UTFW is installed and importable.
echo          Interpreter : %PY_CALL%
echo          Site-packages: %PURELIB%
echo          .pth file    : %PTH_FILE%
echo.

REM --- Download and install sigrok-cli (Windows) ---------------
set "SIGROK_DIR=G:\_Development"
set "SIGROK_INSTALLER=%SIGROK_DIR%\sigrok-cli-installer.exe"
set "SIGROK_URL=https://sigrok.org/download/binary/sigrok-cli/sigrok-cli-NIGHTLY-x86_64-release-installer.exe"

echo [INFO] Downloading sigrok-cli installer...
if not exist "%SIGROK_DIR%" (
  mkdir "%SIGROK_DIR%"
)
powershell -Command "Invoke-WebRequest -Uri '%SIGROK_URL%' -OutFile '%SIGROK_INSTALLER%'"
if not exist "%SIGROK_INSTALLER%" (
  echo [ERROR] Failed to download sigrok-cli installer.
  exit /b 1
)

echo [INFO] Running sigrok-cli installer...
start "" "%SIGROK_INSTALLER%"
if errorlevel 1 (
  echo [ERROR] sigrok-cli installer failed.
  exit /b 1
)

echo [INFO] sigrok-cli installed. You may need to restart your terminal for PATH changes to take effect.
REM Optional: del "%SIGROK_INSTALLER%" to clean up installer file

ENDLOCAL
