@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
REM ================================================================
REM  UTFW Environment Bootstrap (Windows, Python version agnostic)
REM
REM  Usage:
REM    setup_utfw_env.bat [REPO_DIR] [PY_VER]
REM
REM  Examples:
REM    setup_utfw_env.bat                           (uses script folder as REPO_DIR, latest Python 3)
REM    setup_utfw_env.bat "G:\_GitHub\SW_Universal-Test-Framework"   (latest Python 3)
REM    setup_utfw_env.bat "G:\repo" 3.12            (explicit Python 3.12)
REM
REM  What it does:
REM    - pip editable-installs UTFW from REPO_DIR
REM    - writes a .pth into site-packages so `import UTFW` works anywhere
REM    - verifies the import
REM    - OPTIONAL: installs sigrok-cli on request
REM    - Ensures tshark is available (PATH or offers to add or install)
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
  echo [WARN] Python launcher fallback: trying "python" on PATH...
  set "PY_CALL=python"
  %PY_CALL% -c "import sys; print(sys.version)" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] No working Python found. Install Python or adjust arguments.
    exit /b 1
  )
)

echo [INFO] Using interpreter: %PY_CALL%

REM --- Upgrade pip/setuptools/wheel ------------------------------
echo [INFO] Upgrading pip, setuptools, wheel...
%PY_CALL% -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip, setuptools or wheel.
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
%PY_CALL% -c "import UTFW, sys; print(sys.version); print(UTFW.__file__)"
if errorlevel 1 (
  echo [ERROR] Import verification failed.
  exit /b 1
)

echo.
echo [SUCCESS] UTFW is installed and importable.
echo          Interpreter : %PY_CALL%
echo          Site-packages: %PURELIB%
echo          .pth file    : %PTH_FILE%
echo.

REM ================================================================
REM  Optional: Install sigrok-cli (prompt)
REM ================================================================
call :ASK_YN "Install sigrok-cli y/N" N
if /i "%_ANS%"=="Y" (
  call :INSTALL_SIGROK
) else (
  echo [INFO] Skipping sigrok-cli install.
)

REM ================================================================
REM  Ensure tshark availability (PATH or install)
REM ================================================================
call :ENSURE_TSHARK

echo.
echo [DONE] Environment bootstrap complete.
echo You can now run your UTFW testcases.
echo.
goto :EOF

REM ========================= SUBROUTINES ===========================

:ASK_YN
REM Usage: call :ASK_YN "Question text without parentheses + default marker like Y/n or y/N" [DefaultY|DefaultN]
REM Sets _ANS to Y or N
set "_Q=%~1"
set "_D=%~2"
if /i "%_D%"=="Y" ( set "_DEF=Y" ) else ( set "_DEF=N" )
if /i "%_DEF%"=="Y" ( set "_SUFFIX= [Y/n]" ) else ( set "_SUFFIX= [y/N]" )
echo %_Q%%_SUFFIX%
set /p "_ANS=> "
if "%_ANS%"=="" set "_ANS=%_DEF%"
if /i "%_ANS%"=="Y" ( set "_ANS=Y" & exit /b 0 )
if /i "%_ANS%"=="N" ( set "_ANS=N" & exit /b 0 )
echo Please answer Y or N.
goto :ASK_YN

:INSTALL_SIGROK
set "SIGROK_DIR=G:\_Development"
set "SIGROK_INSTALLER=%SIGROK_DIR%\sigrok-cli-installer.exe"
set "SIGROK_URL=https://sigrok.org/download/binary/sigrok-cli/sigrok-cli-NIGHTLY-x86_64-release-installer.exe"

echo [INFO] Installing sigrok-cli...
if not exist "%SIGROK_DIR%" mkdir "%SIGROK_DIR%" >nul 2>&1

echo [INFO] Downloading sigrok-cli installer...
powershell -Command "try { (New-Object Net.WebClient).DownloadFile('%SIGROK_URL%','%SIGROK_INSTALLER%') } catch { exit 1 }"
if errorlevel 1 (
  echo [ERROR] Failed to download sigrok-cli installer.
  exit /b 1
)

echo [INFO] Running sigrok-cli installer...
start "" "%SIGROK_INSTALLER%"
if errorlevel 1 (
  echo [ERROR] sigrok-cli installer failed to start.
  exit /b 1
)
echo [INFO] sigrok-cli installer launched. Follow the installer UI.
exit /b 0

:ENSURE_TSHARK
REM 0) Quick PATH check
where tshark >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('where tshark') do set "TSHARK_EXE=%%~fP"
  echo [INFO] tshark found: "%TSHARK_EXE%"
  exit /b 0
)

echo [WARN] tshark was not found in PATH.

REM 1) Registry App Paths check for tshark.exe Path
for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tshark.exe" /v Path 2^>nul ^| find /i "Path"') do set "WS_DIR=%%B"
if not defined WS_DIR (
  for /f "tokens=2,*" %%A in ('reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tshark.exe" /v Path 2^>nul ^| find /i "Path"') do set "WS_DIR=%%B"
)
if defined WS_DIR (
  if exist "%WS_DIR%\tshark.exe" (
    echo [INFO] Found Wireshark via registry: "%WS_DIR%\tshark.exe"
    set "PATH=%PATH%;%WS_DIR%"
    where tshark >nul 2>&1
    if not errorlevel 1 (
      echo [INFO] Added registry path to session PATH.
      exit /b 0
    )
  )
)

REM 2) Default install locations
set "WS_DEF1=%ProgramFiles%\Wireshark"
set "WS_DEF2=%ProgramFiles(x86)%\Wireshark"
if exist "%WS_DEF1%\tshark.exe" (
  set "WS_DIR=%WS_DEF1%"
) else if exist "%WS_DEF2%\tshark.exe" (
  set "WS_DIR=%WS_DEF2%"
) else (
  set "WS_DIR="
)

if defined WS_DIR (
  echo [INFO] Detected Wireshark install: "%WS_DIR%\tshark.exe"
  call :ASK_YN "Add Wireshark to current PATH - session Y/n" Y
  if /i "%_ANS%"=="Y" (
    set "PATH=%PATH%;%WS_DIR%"
    echo [INFO] Added to session PATH: %WS_DIR%
    where tshark >nul 2>&1
    if not errorlevel 1 (
      echo [INFO] tshark is now available in this session.
      exit /b 0
    )
  )
  call :ASK_YN "Persistently add Wireshark to user PATH with setx y/N" N
  if /i "%_ANS%"=="Y" (
    for /f "usebackq tokens=2,*" %%a in (`reg query "HKCU\Environment" /v PATH 2^>nul ^| find /i "PATH"`) do set "CUR_USER_PATH=%%b"
    if not defined CUR_USER_PATH set "CUR_USER_PATH="
    echo [INFO] Updating user PATH via setx...
    setx PATH "%CUR_USER_PATH%;%WS_DIR%" >nul
    echo [INFO] You may need to restart the terminal for persistent PATH to take effect.
    exit /b 0
  )
)

REM 3) Ask user for a folder where tshark.exe exists
echo tshark.exe not found automatically.
echo If you have Wireshark installed, enter its folder path now.
echo Example: C:\Program Files\Wireshark
set /p "USER_WS_DIR=Wireshark folder path or leave blank to skip: "
if not "%USER_WS_DIR%"=="" (
  if exist "%USER_WS_DIR%\tshark.exe" (
    set "PATH=%PATH%;%USER_WS_DIR%"
    echo [INFO] Added user provided folder to PATH: %USER_WS_DIR%
    where tshark >nul 2>&1
    if not errorlevel 1 (
      echo [INFO] tshark is now available in this session.
      exit /b 0
    )
  ) else (
    echo [WARN] No tshark.exe in: %USER_WS_DIR%
  )
)

REM 4) winget install or download page
where winget >nul 2>&1
if errorlevel 1 (
  echo [WARN] winget not found. Opening Wireshark download page...
  start "" "https://www.wireshark.org/download.html"
  echo [INFO] Please install Wireshark manually, ensure tshark is in PATH, then re-run this script.
  exit /b 0
)

call :ASK_YN "Install Wireshark tshark via winget now y/N" N
if /i "%_ANS%"=="Y" (
  echo [INFO] Installing Wireshark via winget silent...
  winget install --id WiresharkFoundation.Wireshark -e --source winget --accept-package-agreements --silent
  if errorlevel 1 (
    echo [ERROR] winget install failed. Opening download page...
    start "" "https://www.wireshark.org/download.html"
    exit /b 0
  )
  where tshark >nul 2>&1
  if not errorlevel 1 (
    echo [INFO] tshark is now available.
    exit /b 0
  ) else (
    echo [WARN] Wireshark installed but PATH not updated. Open a new terminal and re-run.
    exit /b 0
  )
) else (
  echo [INFO] Skipping Wireshark install. tshark-dependent features may not work until you install Wireshark.
)
exit /b 0
