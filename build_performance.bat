@echo off
REM Build script for MLB ticker Cython optimizations
REM Run this to compile the performance-critical code

set PYTHON_EXE=C:\Users\prc\AppData\Local\Programs\Python\Python313\python.exe
set PIP_EXE=C:\Users\prc\AppData\Local\Programs\Python\Python313\Scripts\pip.exe

echo ========================================
echo MLB-TCKR Performance Build Script
echo ========================================
echo.

REM Check if Python is available
"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found at %PYTHON_EXE%
    echo Please verify Python 3.13 installation path
    pause
    exit /b 1
)

echo [1/5] Checking Cython installation...
"%PYTHON_EXE%" -c "import Cython" >nul 2>&1
if errorlevel 1 (
    echo Cython not found. Installing...
    "%PIP_EXE%" install cython numpy
) else (
    echo Cython is already installed
)

echo.
echo [2/5] Checking NumPy installation...
"%PYTHON_EXE%" -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo NumPy not found. Installing...
    "%PIP_EXE%" install numpy
) else (
    echo NumPy is already installed
)

echo.
echo [3/5] Building MLB ticker Cython module...
"%PYTHON_EXE%" setup_mlb_cython.py build_ext --inplace

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    echo.
    echo This could be because:
    echo   1. Visual C++ Build Tools are not installed
    echo   2. Missing dependencies
    echo.
    echo SOLUTION: Install Visual C++ Build Tools 2022
    echo   Download from: https://visualstudio.microsoft.com/downloads/
    echo   Select "Desktop development with C++"
    echo.
    pause
    exit /b 1
)

echo.
echo [4/5] Cleaning up build artifacts...
if exist mlb_ticker_utils_cython.c del mlb_ticker_utils_cython.c

echo.
echo [5/6] Rebuilding PyInstaller EXEs with Cython bundled...

REM Confirm PyInstaller is available
"%PYTHON_EXE%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: PyInstaller not found. EXEs not rebuilt.
    echo Run: pip install pyinstaller
    echo Then rebuild manually:
    echo   pyinstaller MLB-TCKR-console.spec
    echo   pyinstaller MLB-TCKR.spec
    goto :done
)

echo   Building MLB-TCKR-console.exe  (console visible)...
"%PYTHON_EXE%" -m PyInstaller MLB-TCKR-console.spec --noconfirm
if not exist dist\MLB-TCKR-console.exe goto :fail_console

echo.
echo [6/6] Building MLB-TCKR.exe  (console hidden)...
"%PYTHON_EXE%" -m PyInstaller MLB-TCKR.spec --noconfirm
if not exist dist\MLB-TCKR.exe goto :fail_nogui

goto :done

:fail_console
echo.
echo ========================================
echo PYINSTALLER BUILD FAILED! (console build)
echo ========================================
pause
exit /b 1

:fail_nogui
echo.
echo ========================================
echo PYINSTALLER BUILD FAILED! (no-console build)
echo ========================================
pause
exit /b 1

:done
echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo.
echo The MLB ticker will now run with Cython optimizations
echo for ultra-smooth 60 FPS scrolling.
echo.
echo EXE locations:
echo   dist\MLB-TCKR-console.exe  (console window visible)
echo   dist\MLB-TCKR.exe          (console window hidden)
echo.
pause
